#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forex Bot V5 Elite - MT5 Connector
Auto-resolves XM micro account symbol names (XAUUSDm, EURUSDm etc.)
"""

import logging
import time
import random
from datetime import datetime

log = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    log.warning("MetaTrader5 not installed - Simulation Mode active")


# Auto-detect broker symbol names (XM, IC Markets, Pepperstone etc.)
# Standard name -> [variants to try in order]
SYMBOL_VARIANTS = {
    # Gold - XM uses "GOLD", others use XAUUSD
    "XAUUSD": ["XAUUSD", "XAUUSDm", "GOLD", "GOLDm", "GOLD.cash",
                "XAU/USD", "XAUUSD+", "XAUUSDpro"],
    # Silver
    "XAGUSD": ["XAGUSD", "XAGUSDm", "SILVER", "SILVERm",
                "XAG/USD", "XAGUSD+"],
    # Major Forex pairs
    "EURUSD": ["EURUSD", "EURUSDm", "EUR/USD", "EURUSD+", "EURUSDpro"],
    "GBPUSD": ["GBPUSD", "GBPUSDm", "GBP/USD", "GBPUSD+"],
    "USDJPY": ["USDJPY", "USDJPYm", "USD/JPY", "USDJPY+"],
    "USDCHF": ["USDCHF", "USDCHFm", "USD/CHF", "USDCHF+"],
    "AUDUSD": ["AUDUSD", "AUDUSDm", "AUD/USD", "AUDUSD+"],
    "NZDUSD": ["NZDUSD", "NZDUSDm", "NZD/USD", "NZDUSD+"],
    "USDCAD": ["USDCAD", "USDCADm", "USD/CAD", "USDCAD+"],
    # Cross pairs
    "EURJPY": ["EURJPY", "EURJPYm", "EUR/JPY", "EURJPY+"],
    "GBPJPY": ["GBPJPY", "GBPJPYm", "GBP/JPY", "GBPJPY+"],
    "EURGBP": ["EURGBP", "EURGBPm", "EUR/GBP", "EURGBP+"],
    "AUDJPY": ["AUDJPY", "AUDJPYm", "AUD/JPY"],
    "EURAUD": ["EURAUD", "EURAUDm", "EUR/AUD"],
}

# Reverse map: "GOLD" -> "XAUUSD" (for display)
DISPLAY_NAMES = {}
for std, variants in SYMBOL_VARIANTS.items():
    for v in variants:
        DISPLAY_NAMES[v] = std


class MT5Connector:
    """Manages connection to MetaTrader5 terminal."""

    def __init__(self):
        self._connected = False
        self._sim_mode = not MT5_AVAILABLE
        self._account = {}
        self._sim_balance = 10000.0
        self._sim_equity = 10000.0
        self._resolved = {}  # symbol cache: "XAUUSD" -> "XAUUSDm"

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, login: int, password: str, server: str):
        if not MT5_AVAILABLE:
            self._connected = True
            self._sim_mode = True
            self._account = self._make_sim_account(login, server)
            return True, "Connected [Simulation Mode - MetaTrader5 not installed]"

        try:
            if not mt5.initialize():
                return False, "MT5 initialize failed: {}".format(mt5.last_error())

            ok = mt5.login(login, password=password, server=server)
            if not ok:
                err = mt5.last_error()
                mt5.shutdown()
                return False, "Login failed: {}".format(err)

            info = mt5.account_info()
            if info is None:
                return False, "Could not read account info"

            self._connected = True
            self._sim_mode = False
            self._resolved = {}  # clear cache on new connection
            self._account = {
                "login":       info.login,
                "server":      server,
                "name":        info.name,
                "balance":     round(info.balance, 2),
                "equity":      round(info.equity, 2),
                "margin":      round(info.margin, 2),
                "margin_free": round(info.margin_free, 2),
                "profit":      round(info.profit, 2),
                "currency":    info.currency,
                "leverage":    info.leverage,
                "mode":        "DEMO" if info.trade_mode == 0 else "LIVE",
            }
            log.info("Connected: %s | Balance: %.2f %s | Mode: %s",
                     info.name, info.balance, info.currency, self._account["mode"])
            return True, "Connected! Balance: {:.2f} {} [{}]".format(
                info.balance, info.currency, self._account["mode"])

        except Exception as exc:
            return False, "Connection error: {}".format(exc)

    def disconnect(self):
        if MT5_AVAILABLE and self._connected:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self._connected = False
        self._resolved = {}
        log.info("Disconnected")

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        if self._sim_mode:
            return True
        try:
            return mt5.account_info() is not None
        except Exception:
            self._connected = False
            return False

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        if self._sim_mode:
            self._account["balance"] = round(self._sim_balance, 2)
            self._account["equity"]  = round(self._sim_equity, 2)
            self._account["profit"]  = round(self._sim_equity - self._sim_balance, 2)
            return dict(self._account)
        try:
            info = mt5.account_info()
            if info:
                self._account.update({
                    "balance":     round(info.balance, 2),
                    "equity":      round(info.equity, 2),
                    "margin":      round(info.margin, 2),
                    "margin_free": round(info.margin_free, 2),
                    "profit":      round(info.profit, 2),
                })
        except Exception as exc:
            log.error("get_account_info: %s", exc)
        return dict(self._account)

    # ── Symbol Resolution ─────────────────────────────────────────────────────

    def resolve_symbol(self, symbol: str) -> str:
        """
        Auto-detect the correct broker symbol name.
        e.g. XAUUSD -> GOLD (on XM), XAUUSDm (on other brokers)
        Caches result so detection happens only once per session.
        """
        if self._sim_mode:
            return symbol

        # Check if already resolved (cached)
        if symbol in self._resolved:
            return self._resolved[symbol]

        # Maybe the input IS the broker name (e.g. "GOLD" passed directly)
        # Try to find standard name first
        std_name = DISPLAY_NAMES.get(symbol, symbol)

        # Get variants to try for the standard name
        variants = SYMBOL_VARIANTS.get(std_name, SYMBOL_VARIANTS.get(symbol, [symbol]))

        for v in variants:
            try:
                info = mt5.symbol_info(v)
                if info is not None:
                    mt5.symbol_select(v, True)
                    # Cache both the standard name and the variant
                    self._resolved[symbol]   = v
                    self._resolved[std_name] = v
                    if v != symbol:
                        log.info("Symbol auto-detected: %s -> %s", symbol, v)
                    return v
            except Exception:
                continue

        # Static list failed - fall back to a wildcard search of the
        # broker's full symbol database. This catches any suffix the
        # static list doesn't know about (.a, _i, pro, m, .cash, etc).
        try:
            # Metals often don't contain "XAUUSD"/"XAGUSD" at all on the
            # broker's side (e.g. XM's raw names can be "GOLD", "GOLDm",
            # "Gold Spot", etc) so use dedicated search terms for them.
            metal_terms = {
                "XAUUSD": ["XAUUSD", "GOLD", "XAU"],
                "XAGUSD": ["XAGUSD", "SILVER", "XAG"],
            }
            search_terms = metal_terms.get(std_name)
            if search_terms is None:
                base = std_name.replace("USD", "") if "USD" in std_name else std_name
                search_terms = [std_name] if base == std_name else [std_name, base]

            candidates = []
            for term in search_terms:
                candidates = mt5.symbols_get(f"*{term}*") or []
                if candidates:
                    break

            if candidates:
                # Prefer the shortest matching name (usually the plainest variant)
                best = min(candidates, key=lambda s: len(s.name))
                v = best.name
                mt5.symbol_select(v, True)
                self._resolved[symbol]   = v
                self._resolved[std_name] = v
                log.info("Symbol wildcard-detected: %s -> %s (candidates: %s)",
                         symbol, v, [c.name for c in candidates][:10])
                return v
            else:
                log.error("Symbol NOT FOUND on broker at all: %s (std=%s, tried terms=%s). "
                          "last_error=%s. This symbol may not be offered on "
                          "this account/server.", symbol, std_name, search_terms, mt5.last_error())
        except Exception as exc:
            log.error("Wildcard symbol search failed for %s: %s", symbol, exc)

        # Fallback: return as-is
        self._resolved[symbol] = symbol
        return symbol

    def display_name(self, broker_symbol: str) -> str:
        """Convert broker symbol back to standard name for display."""
        return DISPLAY_NAMES.get(broker_symbol, broker_symbol)

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe, count: int = 150):
        """
        Returns list of OHLCV dicts. Auto-resolves symbol variants.
        """
        if self._sim_mode:
            return _generate_sim_candles(count)

        tf_map = {
            "M5":  mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1":  mt5.TIMEFRAME_H1,
            "H4":  mt5.TIMEFRAME_H4,
            "D1":  mt5.TIMEFRAME_D1,
        }
        tf = tf_map.get(timeframe, timeframe)
        real_sym = self.resolve_symbol(symbol)

        try:
            mt5.symbol_select(real_sym, True)
            rates = mt5.copy_rates_from_pos(real_sym, tf, 0, count)
            if rates is None or len(rates) == 0:
                log.warning("No candles for %s (%s) %s", real_sym, symbol, timeframe)
                return None
            return [{
                "time":   int(r["time"]),
                "open":   float(r["open"]),
                "high":   float(r["high"]),
                "low":    float(r["low"]),
                "close":  float(r["close"]),
                "volume": int(r["tick_volume"]),
            } for r in rates]
        except Exception as exc:
            log.error("get_candles %s %s: %s", real_sym, timeframe, exc)
            return None

    def get_symbol_price(self, symbol: str):
        """Returns (bid, ask) tuple."""
        if self._sim_mode:
            return 1.10000, 1.10015
        real_sym = self.resolve_symbol(symbol)
        try:
            tick = mt5.symbol_info_tick(real_sym)
            if tick:
                return tick.bid, tick.ask
        except Exception:
            pass
        return None, None

    def get_volume_constraints(self, symbol: str):
        """
        Returns (volume_min, volume_max, volume_step) as reported by the
        broker for this symbol. Falls back to (0.01, 1.0, 0.01) if unknown.
        Passing the wrong lot size (e.g. below the broker's real minimum,
        or not a multiple of its step) is a common cause of
        retcode=10014 "Invalid volume".
        """
        default = (0.01, 1.0, 0.01)
        if self._sim_mode:
            return default
        try:
            real_sym = self.resolve_symbol(symbol)
            info = mt5.symbol_info(real_sym)
            if info is None:
                return default
            vmin  = getattr(info, "volume_min", 0.01) or 0.01
            vmax  = getattr(info, "volume_max", 1.0) or 1.0
            vstep = getattr(info, "volume_step", 0.01) or 0.01
            return (vmin, vmax, vstep)
        except Exception as exc:
            log.warning("get_volume_constraints %s: %s", symbol, exc)
            return default

    def get_filling_mode_order(self, symbol: str):
        """
        Returns the list of ORDER_FILLING type names to try, in the order
        the broker actually supports for this specific symbol (read from
        symbol_info().filling_mode), instead of blindly trying all three.

        IMPORTANT: ORDER_FILLING_RETURN only works on exchange-style/
        "Request execution" accounts. Retail "Market Execution" accounts
        (which is what most XM real/demo accounts are) reject it with
        retcode=10030 "Unsupported filling mode" every time. So RETURN is
        always tried LAST, never first, regardless of what the bitmask says.
        """
        # Default when we can't read the bitmask at all: IOC first (works on
        # the overwhelming majority of retail brokers), then FOK, RETURN last.
        default_order = ["FILLING_IOC", "FILLING_FOK", "FILLING_RETURN"]
        if self._sim_mode:
            return default_order
        try:
            real_sym = self.resolve_symbol(symbol)
            info = mt5.symbol_info(real_sym)
            if info is None:
                return default_order
            fm = getattr(info, "filling_mode", 0)  # bitmask: 1=FOK, 2=IOC
            supported = []
            if fm & 2:  # SYMBOL_FILLING_IOC
                supported.append("FILLING_IOC")
            if fm & 1:  # SYMBOL_FILLING_FOK
                supported.append("FILLING_FOK")
            if not supported:
                # Bitmask gave us nothing (very common — many brokers report
                # 0 here even though IOC works fine). Use the safe default
                # instead of falling back to RETURN-first.
                supported = list(default_order)
            else:
                supported.append("FILLING_RETURN")
            log.info("Symbol %s filling_mode bitmask=%s -> try order %s",
                     real_sym, fm, supported)
            return supported
        except Exception as exc:
            log.warning("get_filling_mode_order %s: %s", symbol, exc)
            return default_order

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list:
        if self._sim_mode:
            return []
        try:
            pos = mt5.positions_get()
            return list(pos) if pos else []
        except Exception:
            return []

    def modify_position_sl_tp(self, ticket: int, sl: float = None, tp: float = None) -> bool:
        """
        Move the SL and/or TP of an already-open position. Used for
        break-even / profit-protection — pass only the value(s) you want
        changed, the other stays as-is on the position.
        """
        if self._sim_mode:
            return True
        try:
            pos = mt5.positions_get(ticket=ticket)
            if not pos:
                return False
            p = pos[0]
            req = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol":   p.symbol,
                "sl":       sl if sl is not None else p.sl,
                "tp":       tp if tp is not None else p.tp,
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            log.warning("modify_position_sl_tp #%s failed: %s", ticket,
                        res.comment if res else "no result")
            return False
        except Exception as exc:
            log.error("modify_position_sl_tp #%s: %s", ticket, exc)
            return False

    def get_history_deals(self, from_date, to_date) -> list:
        if self._sim_mode:
            return []
        try:
            deals = mt5.history_deals_get(from_date, to_date)
            return list(deals) if deals else []
        except Exception:
            return []

    # ── Order Execution ───────────────────────────────────────────────────────

    def send_order(self, req: dict):
        if self._sim_mode:
            fake = {
                "retcode": 10009,
                "order":   random.randint(100000, 999999),
                "ticket":  random.randint(100000, 999999),
                "volume":  req.get("volume", 0.01),
                "price":   req.get("price", 1.1000),
                "comment": "SIM_FILL",
            }
            return fake, None
        try:
            res = mt5.order_send(req)
            if res is None:
                err = mt5.last_error()
                log.error("order_send returned None: %s", err)
                return None, str(err)
            result_dict = {
                "retcode": res.retcode,
                "order":   res.order,
                "ticket":  getattr(res, "deal", res.order),
                "volume":  res.volume,
                "price":   res.price,
                "comment": res.comment,
            }
            if res.retcode != mt5.TRADE_RETCODE_DONE:
                log.warning("Order retcode %d: %s", res.retcode, res.comment)
            return result_dict, None
        except Exception as exc:
            log.error("send_order exception: %s", exc)
            return None, str(exc)

    def close_position(self, position_or_ticket) -> bool:
        """
        Close a position. Accepts either a position object (from
        get_positions()) or a raw ticket number (int).
        """
        if self._sim_mode:
            return True

        # Resolve to a position object if a ticket int was passed
        if isinstance(position_or_ticket, (int, float)):
            pos = mt5.positions_get(ticket=int(position_or_ticket))
            if not pos:
                log.warning("close_position: ticket %s not found", position_or_ticket)
                return False
            position = pos[0]
        else:
            position = position_or_ticket

        try:
            sym_info = mt5.symbol_info(position.symbol)
            if sym_info is None:
                log.warning("close_position: symbol info unavailable for %s", position.symbol)
                return False

            if position.type == mt5.ORDER_TYPE_BUY:
                price = sym_info.bid
                otype = mt5.ORDER_TYPE_SELL
            else:
                price = sym_info.ask
                otype = mt5.ORDER_TYPE_BUY

            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       position.symbol,
                "volume":       position.volume,
                "type":         otype,
                "position":     position.ticket,
                "price":        price,
                "deviation":    20,
                "magic":        505050,
                "comment":      "V5_CLOSE",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            msg = res.comment if res else "unknown"
            log.warning("close_position failed #%s: %s", position.ticket, msg)
            return False
        except Exception as exc:
            log.error("close_position exception: %s", exc)
            return False

    def close_all_positions(self) -> int:
        """Close all open positions. Returns count closed."""
        if self._sim_mode:
            return 0
        try:
            positions = mt5.positions_get()
        except Exception:
            positions = None
        closed = 0
        for p in (positions or []):
            if self.close_position(p):
                closed += 1
        return closed

    def mt5_constants(self):
        if not MT5_AVAILABLE:
            return {"BUY":0,"SELL":1,"DONE":10009,"GTC":1,
                    "DEAL":1,"FILLING_RETURN":2,"FILLING_FOK":0,"FILLING_IOC":1}
        return {
            "BUY":          mt5.ORDER_TYPE_BUY,
            "SELL":         mt5.ORDER_TYPE_SELL,
            "DONE":         mt5.TRADE_RETCODE_DONE,
            "GTC":          mt5.ORDER_TIME_GTC,
            "DEAL":         mt5.TRADE_ACTION_DEAL,
            "FILLING_RETURN": mt5.ORDER_FILLING_RETURN,
            "FILLING_FOK":  mt5.ORDER_FILLING_FOK,
            "FILLING_IOC":  mt5.ORDER_FILLING_IOC,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_sim_account(self, login, server):
        return {
            "login":       login,
            "server":      server,
            "name":        "Simulation Account",
            "balance":     10000.0,
            "equity":      10000.0,
            "margin":      0.0,
            "margin_free": 10000.0,
            "profit":      0.0,
            "currency":    "USD",
            "leverage":    500,
            "mode":        "SIMULATION",
        }


# ── Simulation Candles ────────────────────────────────────────────────────────

def _generate_sim_candles(count: int = 150) -> list:
    candles = []
    price = 1.1000 + random.uniform(-0.05, 0.05)
    ts = int(time.time()) - count * 900
    for i in range(count):
        chg = random.gauss(0, 0.0008)
        o = price
        c = price + chg
        h = max(o, c) + abs(random.gauss(0, 0.0003))
        l = min(o, c) - abs(random.gauss(0, 0.0003))
        v = random.randint(200, 2000)
        candles.append({"time": ts + i*900, "open": round(o,5),
                         "high": round(h,5), "low": round(l,5),
                         "close": round(c,5), "volume": v})
        price = c
    return candles
