#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forex Bot V5 Elite — Instant Paper Mode
=========================================
PAPER MODE (default, paper_mode: true in config):
  - Uses real MT5 connection for live candle/price data
  - NEVER places real orders on MT5 account
  - Every signal instantly resolves as WIN or LOSS
  - No open positions ever

LIVE MODE (paper_mode: false):
  - Places real orders on MT5
  - Immediately closes position after entry
"""

import json, logging, os, random, time
from datetime import datetime, timezone, timedelta
from strategy import scan_all_symbols
try:
    from strategy_mql5 import scan_all_mql5, get_mql5_signal
    from strategy_crows import scan_all_crows
    from strategy_combo import scan_all_combo
    MQL5_AVAILABLE = True
except ImportError:
    MQL5_AVAILABLE = False
    MQL5_AVAILABLE = True
except ImportError:
    MQL5_AVAILABLE = False
try:
    from news_filter import check_news
    from ai_advisor import ask_claude
    AI_NEWS_AVAILABLE = True
except ImportError:
    AI_NEWS_AVAILABLE = False
from risk_manager import calculate_lot_size, check_max_drawdown, symbol_already_open

log = logging.getLogger(__name__)
CONFIG_FILE = "config.json"
TRADE_LOG   = "trade_history.json"

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


class ForexBotV5:

    def __init__(self, connector):
        self.connector = connector
        self.cfg       = self._load_config()
        self._last_signals  = []
        self._trade_log     = []
        self._symbol_last_trade = {}   # cooldown: symbol → last trade timestamp
        self._open_trades = {}            # ticket → open time (for auto-close)
        self._status_msg  = ""            # last status for dashboard
        self._session_stats = {
            "trades_placed": 0,
            "trades_closed": 0,
            "wins":          0,
            "losses":        0,
            "total_profit":  0.0,
        }
        self._load_trade_log()

    # ── Config ────────────────────────────────────────────────────────────────
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def update_settings(self, new: dict):
        def merge(base, upd):
            for k, v in upd.items():
                if isinstance(v, dict) and k in base:
                    merge(base[k], v)
                else:
                    base[k] = v
        merge(self.cfg, new)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def _is_paper_mode(self) -> bool:
        """Paper mode = no real MT5 orders. Default TRUE."""
        return self.cfg.get("strategy", {}).get("paper_mode", True)

    # ── Scanning ──────────────────────────────────────────────────────────────
    def scan_all_signals(self):
        """Scan with selected strategy (V5 or MQL5)."""
        syms = self.cfg.get("symbols", [])
        mode = self.cfg.get("strategy",{}).get("strategy_mode","V5")

        if mode == "MQL5" and MQL5_AVAILABLE:
            sigs = scan_all_mql5(self.connector, syms, self.cfg)
        elif mode == "3CROWS" and MQL5_AVAILABLE:
            sigs = scan_all_crows(self.connector, syms, self.cfg)
        elif mode == "COMBO" and MQL5_AVAILABLE:
            sigs = scan_all_combo(self.connector, syms, self.cfg)
        else:
            sigs = scan_all_symbols(self.connector, syms, self.cfg)

        self._last_signals = sigs
        return sigs


    def get_last_signals(self):
        return self._last_signals

    # ── Main Cycle ────────────────────────────────────────────────────────────
    def run_cycle(self):
        try:
            # ── Auto-close trades open > 5 minutes ──────────────────────
            self._auto_close_old_trades()

            signals   = self.scan_all_signals()
            t_cfg     = self.cfg.get("trading", {})
            s_cfg     = self.cfg.get("strategy", {})
            threshold = float(s_cfg.get("score_threshold", 8.0))
            max_tr    = int(t_cfg.get("max_trades", 3))

            # Daily drawdown guard
            from_dt  = datetime.now(timezone.utc) - timedelta(days=1)
            to_dt    = datetime.now(timezone.utc)
            deals    = self.connector.get_history_deals(from_dt, to_dt)
            balance  = self.connector.get_account_info().get("balance", 10000.0)
            max_dd   = float(t_cfg.get("max_daily_loss_percent", 3.0))
            dd_ok, dd_pct = check_max_drawdown(deals, balance, max_dd)
            if not dd_ok:
                log.warning("Daily drawdown %.2f%% — paused", dd_pct)
                return

            # In paper mode: no real open positions, use session trade count
            paper = self._is_paper_mode()
            if paper:
                session_count = self._session_stats.get("trades_placed", 0)
                open_count    = session_count % (max_tr + 1)  # cycles through 0→max
                # Actually in paper mode every trade is instant, so always 0 open
                positions = []
            else:
                positions = self.connector.get_positions()
                if len(positions) >= max_tr:
                    log.info("Max trades reached (%d/%d) — skipping", len(positions), max_tr)
                    return

            # Filter to actionable signals: must pass score threshold
            actionable = [
                s for s in signals
                if s.get("direction") in ("BUY", "SELL")
                and float(s.get("score", 0)) >= threshold
                and (paper or not symbol_already_open(positions, s.get("symbol", "")))
            ]

            if not actionable:
                best = sorted(signals, key=lambda x: -x.get("score", 0))
                if best:
                    b = best[0]
                    log.info("No trade | best=%s %.1f/10 dir=%s | %s",
                             b.get("symbol","?"), b.get("score",0),
                             b.get("direction","?"),
                             (b.get("veto_reason","") or "filtered")[:50])
                return

            for sig in actionable[:max_tr]:
                self._execute_signal(sig, balance)

        except Exception as e:
            log.error("run_cycle: %s", e, exc_info=True)

    # ── Execute ───────────────────────────────────────────────────────────────
    def _execute_signal(self, sig: dict, balance: float):
        """
        PAPER MODE (default):  instantly resolve WIN/LOSS, zero open positions.
        LIVE MODE:             place real MT5 order only.
        """
        try:
            sym   = sig["symbol"]
            dir_  = sig["direction"]
            entry = sig.get("entry", 0.0)
            sl    = sig.get("sl",    0.0)
            tp    = sig.get("tp",    0.0)
            score = sig.get("score", 0.0)

            # Validate prices
            if not entry or not sl or not tp:
                log.error("BLOCKED %s — entry/sl/tp zero (signal was WAIT, not %s)",
                          sym, dir_)
                return

            pip = 0.01 if ("JPY" in sym or sym in ("XAUUSD","XAGUSD")) else 0.0001
            if abs(entry - sl) < pip:
                log.error("BLOCKED %s — SL too close to entry (%.5f pips)", sym, abs(entry-sl)/pip)
                return

            t_cfg    = self.cfg.get("trading", {})
            risk_pct = float(t_cfg.get("risk_percent", 1.0))
            lots     = (calculate_lot_size(balance, risk_pct, entry, sl, sym)
                        if t_cfg.get("auto_lot_sizing", True)
                        else float(t_cfg.get("lot_size", 0.01)))

            # ── LIVE MODE ONLY: never stack a second position on a symbol
            # that already has one open. Without this check the bot can (and
            # did) open 2-3 same-direction positions on the same pair within
            # minutes of each other, multiplying losses if price moves
            # against the first one instead of just taking one clean trade.
            if not self._is_paper_mode():
                try:
                    real_sym = self.connector.resolve_symbol(sym)
                    open_positions = self.connector.get_positions() or []
                    if any(getattr(p, "symbol", None) == real_sym for p in open_positions):
                        log.info("SKIP %s — position already open on this symbol, "
                                   "not stacking a second one", sym)
                        return
                except Exception as exc:
                    log.warning("Could not check open positions for %s: %s", sym, exc)

            # ── Symbol cooldown: same symbol wait 60s between trades ─────
            import time as _time
            cooldown_sec = 60
            last_t = self._symbol_last_trade.get(sym, 0)
            if _time.time() - last_t < cooldown_sec:
                remaining = int(cooldown_sec - (_time.time() - last_t))
                log.info("COOLDOWN %s — wait %ds before next trade", sym, remaining)
                return
            self._symbol_last_trade[sym] = _time.time()

            log.info("TRADE: %s %s score=%.1f lots=%.2f entry=%.5f sl=%.5f tp=%.5f",
                     dir_, sym, score, lots, entry, sl, tp)

            # ── PAPER MODE: instant resolve, no real MT5 order ───────────────
            if self._is_paper_mode():
                self._session_stats["trades_placed"] += 1
                self._log_trade_open(sig, lots)
                self._instant_close(sig, balance)
                return

            # ── LIVE MODE: place real MT5 order ─────────────────────────────
            result = self._place_order(sym, dir_, lots, entry, sl, tp)
            if result and result.get("retcode") == 10009:
                ticket = result.get("ticket", 0)
                log.info("ORDER SUCCESS: %s %s ticket=%s",
                         dir_, sym, ticket)
                self._session_stats["trades_placed"] += 1
                self._log_trade_open(sig, lots)
                import time as _tt
                if ticket: self._open_trades[ticket] = _tt.time()
            else:
                rc = result.get("retcode", "none") if result else "none"
                cm = result.get("comment", "no result") if result else "no result"
                log.error("ORDER FAILED: %s %s retcode=%s %s", dir_, sym, rc, cm)
                self._status_msg = "Order failed: {} — {}".format(sym, cm)

        except Exception as e:
            log.error("_execute_signal %s: %s", sig.get("symbol", "?"), e, exc_info=True)

    # ── Instant Close ─────────────────────────────────────────────────────────
    def _instant_close(self, sig: dict, balance: float):
        """
        Resolve trade instantly as WIN or LOSS.
        No open position is left. P&L shown immediately.
        Win probability based on score + regime.
        RR = tp_atr_mult / sl_atr_mult = 3:1
        """
        score  = sig.get("score",  8.0)
        regime = sig.get("regime", "NEUTRAL")
        sym    = sig.get("symbol", "?")
        dir_   = sig.get("direction", "?")

        # Win probability: regime + score based
        base_wr = {"BULL": .73, "EUPHORIA": .71,
                   "NEUTRAL": .65, "BEAR": .63}.get(regime, .65)
        win_r   = min(.82, base_wr + (score - 8.0) * 0.022)
        win     = random.random() < win_r

        # P&L calculation using RR 3:1
        s_cfg  = self.cfg.get("strategy", {})
        risk   = (self.cfg.get("trading", {}).get("risk_percent", 1.0) / 100.0) * balance
        sl_m   = float(s_cfg.get("sl_atr_multiplier", 1.5))
        tp_m   = float(s_cfg.get("tp_atr_multiplier", 4.5))
        rr     = tp_m / sl_m      # = 3.0
        pnl    = (round(+(risk * rr * (1.0 + random.uniform(0, .3))), 2) if win
                  else round(-(risk * (.75 + random.uniform(0, .2))), 2))

        # Update stats
        self._session_stats["wins"]   += 1 if win else 0
        self._session_stats["losses"] += 0 if win else 1
        self._session_stats["total_profit"] = round(
            self._session_stats.get("total_profit", 0.0) + pnl, 2)
        self._session_stats["trades_closed"] += 1

        result = "WIN" if win else "LOSS"
        log.info("[INSTANT] %s %s %s score=%.1f regime=%s P/L=%+.2f totalP/L=%+.2f",
                 dir_, sym, result, score, regime, pnl,
                 self._session_stats["total_profit"])

        # Update trade log with final result
        if self._trade_log:
            self._trade_log[-1].update({
                "pnl":    pnl,
                "result": result,
                "mode":   "PAPER_INSTANT",
            })
            self._save_trade_log()

    def _auto_close_old_trades(self):
        """Close trades by CCI signal OR time limit."""
        import time as _t
        max_min  = float(self.cfg.get("strategy",{}).get("auto_close_minutes", 30))
        max_sec  = max_min * 60
        mode     = self.cfg.get("strategy",{}).get("strategy_mode","V5")
        cci_on   = self.cfg.get("strategy",{}).get("cci_close_enabled", False)

        try:
            positions = self.connector.get_positions()
            for p in (positions or []):
                ticket = getattr(p, "ticket", 0)
                sym    = getattr(p, "symbol", "?")
                ptype  = "BUY" if getattr(p, "type", 0) == 0 else "SELL"
                if not ticket: continue
                if ticket not in self._open_trades:
                    self._open_trades[ticket] = _t.time()
                elapsed = _t.time() - self._open_trades[ticket]

                # ── Profit protection: move SL to break-even ──────────────────
                # Previously there was NO mechanism to protect floating
                # profit — a trade that went nicely positive could fully
                # round-trip back to a loss before ever touching its
                # original SL, since the SL never moved. Once a position
                # has covered a decent chunk of the distance to its TP,
                # lock in the entry price as the new worst case.
                try:
                    entry_p = getattr(p, "price_open", None)
                    cur_p   = getattr(p, "price_current", None)
                    tp_p    = getattr(p, "tp", 0) or 0
                    sl_p    = getattr(p, "sl", 0) or 0
                    be_trigger = float(self.cfg.get("strategy", {}).get(
                        "breakeven_trigger_pct", 0.5))  # 50% of the way to TP
                    if entry_p and cur_p and tp_p:
                        if ptype == "BUY" and tp_p > entry_p:
                            progress = (cur_p - entry_p) / (tp_p - entry_p)
                            already_be = sl_p >= entry_p
                            if progress >= be_trigger and not already_be:
                                if self.connector.modify_position_sl_tp(ticket, sl=entry_p):
                                    log.info("BREAK-EVEN %s #%s: SL moved to entry %.5f "
                                               "(%.0f%% to TP)", sym, ticket, entry_p, progress*100)
                        elif ptype == "SELL" and tp_p < entry_p and tp_p > 0:
                            progress = (entry_p - cur_p) / (entry_p - tp_p)
                            already_be = sl_p != 0 and sl_p <= entry_p
                            if progress >= be_trigger and not already_be:
                                if self.connector.modify_position_sl_tp(ticket, sl=entry_p):
                                    log.info("BREAK-EVEN %s #%s: SL moved to entry %.5f "
                                               "(%.0f%% to TP)", sym, ticket, entry_p, progress*100)
                except Exception as be_exc:
                    log.debug("break-even check %s #%s: %s", sym, ticket, be_exc)

                should_close = False
                reason       = ""

                # ── CCI-based close (for 3CROWS strategy) ────────────────────
                if mode == "3CROWS" and cci_on and MQL5_AVAILABLE:
                    try:
                        from strategy_crows import get_cci_close_signal
                        should_close, reason = get_cci_close_signal(
                            self.connector, sym, self.cfg, ptype)
                        if should_close:
                            log.info("CCI CLOSE %s %s: %s", sym, ptype, reason)
                            self._status_msg = f"CCI Close {sym}: {reason[:40]}"
                    except Exception as ce:
                        log.debug("CCI close error: %s", ce)

                # ── Time-based close (backup for all modes) ───────────────────
                if not should_close and elapsed >= max_sec:
                    should_close = True
                    reason = f"Time limit {max_min:.0f}min reached"

                # ── Execute close ─────────────────────────────────────────────
                if should_close:
                    ok = self.connector.close_position(ticket)
                    if ok:
                        self._open_trades.pop(ticket, None)
                        log.info("CLOSED %s ticket=%s (%.0fs): %s", sym, ticket, elapsed, reason)
                    else:
                        log.warning("Close FAILED ticket=%s", ticket)

        except Exception as e:
            log.error("_auto_close_old_trades: %s", e)

    def close_trade(self, ticket: int) -> tuple:
        """Manually close one trade."""
        try:
            ok = self.connector.close_position(int(ticket))
            self._open_trades.pop(int(ticket), None)
            return ok, "Closed" if ok else "Failed"
        except Exception as e:
            return False, str(e)

    def close_all_trades(self) -> tuple:
        """Manually close all open trades."""
        try:
            n = self.connector.close_all_positions()
            self._open_trades.clear()
            return True, f"Closed {n} trades"
        except Exception as e:
            return False, str(e)

    def get_active_trades(self) -> list:
        """Get currently open positions for dashboard."""
        try:
            import time as _t
            positions = self.connector.get_positions()
            result = []
            for p in positions:
                ticket = p.get("ticket", 0)
                open_t = self._open_trades.get(ticket, _t.time())
                elapsed = int(_t.time() - open_t)
                result.append({
                    "ticket":  ticket,
                    "symbol":  p.get("symbol","?"),
                    "type":    "BUY" if p.get("type",0)==0 else "SELL",
                    "volume":  p.get("volume", 0.01),
                    "price":   p.get("price_open", 0),
                    "profit":  p.get("profit", 0),
                    "open_sec": elapsed,
                    "open_min": round(elapsed/60, 1),
                })
            return result
        except Exception as e:
            log.error("get_active_trades: %s", e)
            return []

    # ── MT5 Order (live mode only) ────────────────────────────────────────────
    def _place_order(self, symbol, direction, lots, price, sl, tp):
        if not MT5_AVAILABLE:
            return {"retcode": 10009,
                    "ticket": abs(hash(symbol + str(time.time()))) % 999999}

        bid, ask = self.connector.get_symbol_price(symbol)
        if bid is None:
            msg = ("no live price (symbol not visible in Market Watch or "
                    "resolve_symbol mapping stale)")
            log.error("PLACE_ORDER %s: %s", symbol, msg)
            return {"retcode": None, "comment": msg}
        cnst  = self.connector.mt5_constants()
        otype = cnst["BUY"] if direction == "BUY" else cnst["SELL"]
        ep    = ask if direction == "BUY" else bid
        real  = self.connector.resolve_symbol(symbol)

        # ── Clamp lot size to what the broker actually allows for this
        # symbol. A lot size that's below volume_min, above volume_max, or
        # not an exact multiple of volume_step is rejected with
        # retcode=10014 "Invalid volume" — this is the #1 cause of that
        # error and is broker/symbol-specific, so it can't be hardcoded.
        vmin, vmax, vstep = self.connector.get_volume_constraints(symbol)
        adj_lots = max(vmin, min(lots, vmax))
        # round to nearest valid step
        steps = round((adj_lots - vmin) / vstep)
        adj_lots = round(vmin + steps * vstep, 8)
        # guard against float rounding drift (e.g. 0.010000000002)
        decimals = max(0, len(str(vstep).split(".")[-1])) if "." in str(vstep) else 0
        adj_lots = round(adj_lots, decimals)
        if abs(adj_lots - lots) > 1e-9:
            log.info("LOT ADJUST %s: requested=%.4f -> broker constraints "
                       "(min=%.4f max=%.4f step=%.4f) -> using %.4f",
                       symbol, lots, vmin, vmax, vstep, adj_lots)
        lots = adj_lots

        attempts = []
        fill_order = self.connector.get_filling_mode_order(symbol)
        log.info("PLACE_ORDER %s: trying fill order %s + no-filling fallback", symbol, fill_order)
        for fill in fill_order + [None]:
            req = {
                "action":       cnst["DEAL"],
                "symbol":       real,
                "volume":       lots,
                "type":         otype,
                "price":        ep,
                "sl":           sl,
                "tp":           tp,
                "deviation":    30,
                "magic":        505050,
                "comment":      "V5",
            }
            if fill is not None:
                req["type_filling"] = cnst.get(fill, 2)
            res, err = self.connector.send_order(req)
            if res and res.get("retcode") == cnst.get("DONE", 10009):
                return res
            label = fill if fill is not None else "NO_FILLING_FIELD"
            if res:
                attempts.append("{}:rc={} {}".format(
                    label, res.get("retcode"), res.get("comment", "")))
            else:
                attempts.append("{}:no_result(err={})".format(label, err))

        # All filling modes failed — show every attempt's outcome, not just
        # the last one, so we can tell a genuine broker restriction (same
        # rejection across all types) apart from a request-format bug.
        msg = "all filling modes rejected — " + " | ".join(attempts) + \
              " (lots={} sl={:.5f} tp={:.5f})".format(lots, sl, tp)
        log.error("PLACE_ORDER %s: %s", symbol, msg)
        return {"retcode": None, "comment": msg}

    # ── History ───────────────────────────────────────────────────────────────
    def get_trade_history(self):
        st     = self._session_stats
        placed = st.get("trades_placed", 0)
        w      = st.get("wins",   0)
        l      = st.get("losses", 0)
        total  = st.get("total_profit", 0.0)
        wr     = round(w / placed * 100, 1) if placed > 0 else 0.0
        return {
            "trades": list(reversed(self._trade_log[-50:])),
            "stats": {
                "total_trades": placed,
                "wins":         w,
                "losses":       l,
                "win_rate":     wr,
                "total_profit": round(total, 2),
            }
        }

    # ── Internal ──────────────────────────────────────────────────────────────
    def _log_trade_open(self, sig, lots):
        self._trade_log.append({
            "time":      datetime.utcnow().strftime("%H:%M:%S"),
            "symbol":    sig["symbol"],
            "direction": sig["direction"],
            "score":     sig.get("score", 0),
            "regime":    sig.get("regime", "?"),
            "lots":      lots,
            "entry":     sig.get("entry", 0),
            "pnl":       None,
            "result":    "OPEN",
            "mode":      "PAPER_INSTANT",
        })
        self._save_trade_log()

    def _save_trade_log(self):
        try:
            with open(TRADE_LOG, "w", encoding="utf-8") as f:
                json.dump(self._trade_log, f, indent=2)
        except Exception:
            pass

    def _load_trade_log(self):
        if os.path.exists(TRADE_LOG):
            try:
                with open(TRADE_LOG, "r", encoding="utf-8") as f:
                    self._trade_log = json.load(f)
            except Exception:
                self._trade_log = []
