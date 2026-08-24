#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMBO Strategy: Hanging Man/Hammer + Three Crows/Soldiers + CCI

Logic:
  SUPER BUY:
    Step 1: Hammer detected (reversal candle — trend change signal)
    Step 2: Followed by 3 White Soldiers (momentum confirmation)
    Step 3: CCI < -50 (momentum confirmed)
    = Strongest BUY signal

  SUPER SELL:
    Step 1: Hanging Man detected (reversal candle)
    Step 2: Followed by 3 Black Crows (momentum confirmation)
    Step 3: CCI > 50 (momentum confirmed)
    = Strongest SELL signal

  MEDIUM BUY (partial match):
    - Only Hammer + CCI (no soldiers yet) = score 6-7
    - Only 3 Soldiers + CCI (no hammer)  = score 6-7

  FULL COMBO (both match):
    - Hammer + 3 Soldiers + CCI           = score 8-10
"""

import logging
import numpy as np
log = logging.getLogger(__name__)

# Import from existing strategies
from strategy_mql5  import (calc_sma as _sma, calc_cci as _cci,
                             mid_point, CCI_PERIOD as MQL5_CCI,
                             MA_PERIOD as MQL5_MA)
from strategy_crows import (calc_cci, is_bullish, is_bearish,
                             body_size, candle_range, body_ratio,
                             upper_wick_ratio, lower_wick_ratio,
                             detect_three_white_soldiers,
                             detect_three_black_crows,
                             get_cci_close_signal, CCI_PERIOD)
from strategy import adx as _calc_adx, rsi as _calc_rsi

try:
    import patterns_ml as _pml
    _HAS_ML = True
except Exception as _e:
    _HAS_ML = False
    log.warning("patterns_ml not available, ML filter disabled: %s", _e)

# ── Parameters ────────────────────────────────────────────────────────────────
HAMMER_LOOKBACK  = 8    # look back N bars for hammer/hanging man
CCI_BUY_CONFIRM  = -50  # CCI for FULL combo hammer confirm (strict)
CCI_SELL_CONFIRM =  50  # CCI for FULL combo hanging man confirm (strict)
CCI_BUY_PARTIAL  = -30  # CCI for PARTIAL signals (looser)
CCI_SELL_PARTIAL =  30  # CCI for PARTIAL signals (looser)
MIN_BODY_RATIO   = 0.3  # minimum body ratio for soldiers/crows
MA_PERIOD        = 10   # trend SMA
ADX_TREND_MIN    = 25   # ADX above this = an established trend is in force.
                         # Weak/partial-tier signals that fight this trend
                         # (e.g. BUY while ADX shows a strong established
                         # downtrend) are vetoed — catching a falling knife
                         # on a low-confidence pattern is the riskiest trade
                         # this strategy can take.

# ── TF mapping ────────────────────────────────────────────────────────────────
_TF_MAP = {
    "M5":        "M5",
    "M15":       "M15",
    "H1":        "H1",
    "H4":        "H4",
    "M15_H1_H4": "M15",
    "ALL":       "M15",
}

def _get_primary_tf(cfg: dict) -> str:
    tf_mode = cfg.get("strategy", {}).get("tf_mode", "M15_H1_H4")
    return _TF_MAP.get(tf_mode, "M15")


def _detect_hammer_in_range(candles, sma_vals, start, end):
    """
    Look for Hammer in candles[start:end] (recent bars).
    Returns (found: bool, bar_index: int)
    """
    for i in range(start, min(end, len(candles)-1)):
        c = candles[i]
        c_prev = candles[i+1] if i+1 < len(candles) else None
        sma = sma_vals[i+1] if i+1 < len(sma_vals) else None

        if c_prev is None or sma is None:
            continue

        h, l = c["high"], c["low"]
        o, cl = c["open"], c["close"]
        upper_third = h - (h - l) / 3.0

        # Hammer: downtrend, body upper 1/3, gap down
        if (mid_point(h, l) < sma and
            min(o, cl) > upper_third and
            cl < c_prev["close"] and
            o  < c_prev["open"]):
            return True, i

    return False, -1


def _detect_hanging_man_in_range(candles, sma_vals, start, end):
    """
    Look for Hanging Man in candles[start:end].
    Returns (found: bool, bar_index: int)
    """
    for i in range(start, min(end, len(candles)-1)):
        c = candles[i]
        c_prev = candles[i+1] if i+1 < len(candles) else None
        sma = sma_vals[i+1] if i+1 < len(sma_vals) else None

        if c_prev is None or sma is None:
            continue

        h, l = c["high"], c["low"]
        o, cl = c["open"], c["close"]
        upper_third = h - (h - l) / 3.0

        # Hanging Man: uptrend, body upper 1/3, gap up
        if (mid_point(h, l) > sma and
            min(o, cl) > upper_third and
            cl > c_prev["close"] and
            o  > c_prev["open"]):
            return True, i

    return False, -1


def _get_combo_signal_raw(connector, symbol, cfg):
    """
    Combined Hammer/Hanging Man + 3Crows/Soldiers + CCI signal.
    """
    result = {
        "symbol": symbol, "direction": "WAIT", "score": 0.0,
        "confidence": 0, "regime": "NEUTRAL",
        "veto_reason": "", "vetoed": False,
        "m15": "NEUTRAL", "h1": "NEUTRAL", "h4": "NEUTRAL",
        "rsi": 50.0, "adx": 0.0,
        "entry": 0.0, "sl": 0.0, "tp": 0.0, "atr": 0.0,
        "pattern": "", "cci_value": 0.0, "signal_time": "",
    }

    s_cfg   = cfg.get("strategy", {})
    sl_mult = float(s_cfg.get("sl_atr_multiplier", 1.5))
    tp_mult = float(s_cfg.get("tp_atr_multiplier", 4.5))
    entry_tf = _get_primary_tf(cfg)

    try:
        # Need enough candles for lookback
        needed  = max(CCI_PERIOD, MA_PERIOD) + HAMMER_LOOKBACK + 10
        candles = connector.get_candles(symbol, entry_tf, needed)
        if not candles or len(candles) < needed // 2:
            result["veto_reason"] = "Not enough data"
            return result

        n      = len(candles)
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        closes = [c["close"] for c in candles]

        # ── Real ADX / RSI / trend direction ────────────────────────────
        # Previously this whole function reported adx=0.0 and rsi=50.0 as
        # static placeholders that were NEVER actually computed — meaning
        # there was no real trend-strength awareness at all, and weak/
        # partial-tier signals could (and did) fire straight into a strong
        # established trend against them. Compute it for real now.
        h_arr, l_arr, c_arr = np.array(highs, dtype=float), np.array(lows, dtype=float), np.array(closes, dtype=float)
        adx_arr, pdi_arr, ndi_arr = _calc_adx(h_arr, l_arr, c_arr)
        rsi_arr = _calc_rsi(c_arr)
        cur_adx = float(adx_arr[-2]) if len(adx_arr) > 1 else 0.0
        cur_rsi = float(rsi_arr[-2]) if len(rsi_arr) > 1 else 50.0
        # trend direction implied by DI+/DI- (only meaningful once ADX shows
        # a real trend — see ADX_TREND_MIN below)
        trend_dir = "UP" if (len(pdi_arr) > 1 and pdi_arr[-2] > ndi_arr[-2]) else "DOWN"
        result["adx"] = round(cur_adx, 1)
        result["rsi"] = round(cur_rsi, 1)

        # Indicators
        cci_vals = calc_cci(highs, lows, closes, CCI_PERIOD)
        sma_vals = _sma(closes, MA_PERIOD)

        # CCI at recent bars
        cci1 = cci_vals[n-2]   # latest completed bar
        cci2 = cci_vals[n-3]
        if cci1 is None:
            result["veto_reason"] = "CCI not ready"
            return result

        result["cci_value"] = round(cci1, 1)

        # Last 3 completed bars for pattern check
        # c1=most recent, c2=prev, c3=oldest
        c1 = candles[n-2]
        c2 = candles[n-3]
        c3 = candles[n-4] if n >= 4 else None

        if c3 is None:
            result["veto_reason"] = "Not enough candles"
            return result

        # Check 3 pattern (most recent 3 bars)
        tws, tws_msg = detect_three_white_soldiers(c1, c2, c3)
        tbc, tbc_msg = detect_three_black_crows(c1, c2, c3)

        # Look for Hammer/Hanging Man in bars 4-11 (before the 3 pattern)
        # Index n-5 to n-12 (older bars, before the 3 soldiers/crows)
        hammer_found, hammer_idx = _detect_hammer_in_range(
            candles, sma_vals, n-5, n-5+HAMMER_LOOKBACK)
        hanging_found, hanging_idx = _detect_hanging_man_in_range(
            candles, sma_vals, n-5, n-5+HAMMER_LOOKBACK)

        # Current price
        bid, ask = connector.get_symbol_price(symbol)
        atr = sum(c["high"] - c["low"] for c in candles[-14:]) / 14

        # ── Trend-following confirmation ────────────────────────────────
        # The user wants BUY trades taken only when price is ALREADY moving
        # up (green candles forming), not as a bet that a decline is about
        # to reverse. Two checks enforce that for the lower-confidence
        # (partial/weakest) signal tiers:
        #   1. Price must be above its own short-term average for BUY
        #      (below it for SELL) — i.e. price is already on that side
        #      of its recent trend, not still on the opposite side hoping
        #      to cross over.
        #   2. If ADX shows an established trend, that trend must actually
        #      match the trade direction (not just "not oppose" it).
        last_close = closes[n-2]
        last_sma   = sma_vals[n-2] if len(sma_vals) > n-2 else None
        price_confirms_buy  = last_sma is not None and last_close > last_sma
        price_confirms_sell = last_sma is not None and last_close < last_sma

        trend_confirms_buy  = cur_adx < ADX_TREND_MIN or trend_dir == "UP"
        trend_confirms_sell = cur_adx < ADX_TREND_MIN or trend_dir == "DOWN"

        # Combined gate used below for PARTIAL/WEAKEST tiers only. FULL
        # COMBO (hammer+soldiers+strict CCI together) is left as-is since
        # it already requires genuine multi-signal agreement.
        adx_veto_buy  = not (price_confirms_buy  and trend_confirms_buy)
        adx_veto_sell = not (price_confirms_sell and trend_confirms_sell)

        # ── For accurate fallback messaging only ────────────────────────
        # adx_veto_buy/sell above is TRUE almost always for one side or the
        # other (price is on one side of its SMA or the other — never
        # neither), so it must NOT be shown as "a signal was vetoed" unless
        # a real pattern actually existed underneath it. Otherwise every
        # single symbol shows a misleading "ADX trend veto" message even
        # when there was no pattern at all to trade in the first place.
        would_buy  = bool(tws or hammer_found)
        would_sell = bool(tbc or hanging_found)
        pattern_vetoed_buy  = would_buy  and adx_veto_buy
        pattern_vetoed_sell = would_sell and adx_veto_sell

        # ══════════════════════════════════════════════════════════════════════
        # SUPER BUY: Hammer → 3 White Soldiers → CCI < -50
        # ══════════════════════════════════════════════════════════════════════
        if tws and hammer_found and cci1 < CCI_BUY_CONFIRM:
            bars_between = hammer_idx - (n-5)
            score = _combo_score(cci1, "BUY", True, True, bars_between)
            conf  = min(99, int(80 + abs(cci1 + 50) / 3))
            result.update({
                "direction":  "BUY",
                "score":      score,
                "confidence": conf,
                "regime":     "BULL",
                "entry":      round(ask, 5),
                "sl":         round(ask - sl_mult * atr, 5),
                "tp":         round(ask + tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"🔥 COMBO: Hammer + 3 Soldiers (CCI={cci1:.0f})",
                "m15": "BUY", "h1": "BUY",
            })
            log.info("[COMBO] SUPER BUY %s sc=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            return result

        # ══════════════════════════════════════════════════════════════════════
        # SUPER SELL: Hanging Man → 3 Black Crows → CCI > 50
        # ══════════════════════════════════════════════════════════════════════
        if tbc and hanging_found and cci1 > CCI_SELL_CONFIRM:
            bars_between = hanging_idx - (n-5)
            score = _combo_score(cci1, "SELL", True, True, bars_between)
            conf  = min(99, int(80 + abs(cci1 - 50) / 3))
            result.update({
                "direction":  "SELL",
                "score":      score,
                "confidence": conf,
                "regime":     "BEAR",
                "entry":      round(bid, 5),
                "sl":         round(bid + sl_mult * atr, 5),
                "tp":         round(bid - tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"🔥 COMBO: Hanging Man + 3 Crows (CCI={cci1:.0f})",
                "m15": "SELL", "h1": "SELL",
            })
            log.info("[COMBO] SUPER SELL %s sc=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            return result

        # ══════════════════════════════════════════════════════════════════════
        # PARTIAL: Only 3 Soldiers + CCI (no hammer — medium signal)
        # ══════════════════════════════════════════════════════════════════════
        if tws and cci1 < CCI_BUY_PARTIAL and not adx_veto_buy:
            score = _combo_score(cci1, "BUY", False, True, 0)
            result.update({
                "direction":  "BUY",
                "score":      score,
                "confidence": min(99, int(70 + abs(cci1 + 50) / 4)),
                "regime":     "BULL",
                "entry":      round(ask, 5),
                "sl":         round(ask - sl_mult * atr, 5),
                "tp":         round(ask + tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"3 White Soldiers (CCI={cci1:.0f})",
                "m15": "BUY", "h1": "BUY",
            })
            log.info("[COMBO] Partial BUY %s sc=%.1f TF=%s", symbol, score, entry_tf)
            return result

        # ══════════════════════════════════════════════════════════════════════
        # PARTIAL: Only 3 Crows + CCI (no hanging man)
        # ══════════════════════════════════════════════════════════════════════
        if tbc and cci1 > CCI_SELL_PARTIAL and not adx_veto_sell:
            score = _combo_score(cci1, "SELL", False, True, 0)
            result.update({
                "direction":  "SELL",
                "score":      score,
                "confidence": min(99, int(70 + abs(cci1 - 50) / 4)),
                "regime":     "BEAR",
                "entry":      round(bid, 5),
                "sl":         round(bid + sl_mult * atr, 5),
                "tp":         round(bid - tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"3 Black Crows (CCI={cci1:.0f})",
                "m15": "SELL", "h1": "SELL",
            })
            log.info("[COMBO] Partial SELL %s sc=%.1f TF=%s", symbol, score, entry_tf)
            return result

        # ══════════════════════════════════════════════════════════════════════
        # PARTIAL: Only Hammer + CCI (3 soldiers not yet formed)
        # ══════════════════════════════════════════════════════════════════════
        if hammer_found and cci1 < CCI_BUY_PARTIAL and not adx_veto_buy:
            score = _combo_score(cci1, "BUY", True, False, 0)
            result.update({
                "direction":  "BUY",
                "score":      score,
                "confidence": min(99, int(65 + abs(cci1 + 50) / 4)),
                "regime":     "NEUTRAL",
                "entry":      round(ask, 5),
                "sl":         round(ask - sl_mult * atr, 5),
                "tp":         round(ask + tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"Hammer (CCI={cci1:.0f}) — waiting soldiers",
                "m15": "BUY", "h1": "NEUTRAL",
            })
            return result

        if hanging_found and cci1 > CCI_SELL_PARTIAL and not adx_veto_sell:
            score = _combo_score(cci1, "SELL", True, False, 0)
            result.update({
                "direction":  "SELL",
                "score":      score,
                "confidence": min(99, int(65 + abs(cci1 - 50) / 4)),
                "regime":     "NEUTRAL",
                "entry":      round(bid, 5),
                "sl":         round(bid + sl_mult * atr, 5),
                "tp":         round(bid - tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"Hanging Man (CCI={cci1:.0f}) — waiting crows",
                "m15": "SELL", "h1": "NEUTRAL",
            })
            return result

        # ══════════════════════════════════════════════════════════════════════
        # WEAKEST TIER: pattern found but CCI not extreme enough — still worth
        # a low-confidence signal instead of a flat WAIT, so the scanner has
        # something to rank instead of sitting at 0.0 all day.
        # ══════════════════════════════════════════════════════════════════════
        if (tws or hammer_found) and not adx_veto_buy:
            score = 4.5 + (0.5 if tws and hammer_found else 0.0)
            result.update({
                "direction":  "BUY",
                "score":      round(score, 1),
                "confidence": 55,
                "regime":     "NEUTRAL",
                "entry":      round(ask, 5),
                "sl":         round(ask - sl_mult * atr, 5),
                "tp":         round(ask + tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"Weak BUY setup (CCI={cci1:.0f}, no strong confirm)",
                "m15": "BUY", "h1": "NEUTRAL",
            })
            return result

        if (tbc or hanging_found) and not adx_veto_sell:
            score = 4.5 + (0.5 if tbc and hanging_found else 0.0)
            result.update({
                "direction":  "SELL",
                "score":      round(score, 1),
                "confidence": 55,
                "regime":     "NEUTRAL",
                "entry":      round(bid, 5),
                "sl":         round(bid + sl_mult * atr, 5),
                "tp":         round(bid - tp_mult * atr, 5),
                "atr":        round(atr, 5),
                "pattern":    f"Weak SELL setup (CCI={cci1:.0f}, no strong confirm)",
                "m15": "SELL", "h1": "NEUTRAL",
            })
            return result

        # No pattern at all — or a pattern existed but was ADX-trend-vetoed
        reasons = []
        if pattern_vetoed_buy or pattern_vetoed_sell:
            reasons.append("ADX/trend veto: price+trend don't confirm {} "
                            "(ADX={:.0f})".format(
                                "BUY" if pattern_vetoed_buy else "SELL", cur_adx))
        if not hammer_found and not hanging_found:
            reasons.append("No Hammer/Hanging Man")
        if not tws and not tbc:
            reasons.append(tws_msg if not is_bearish(c1) else tbc_msg)
        result["veto_reason"] = " | ".join(reasons) if reasons else "No pattern"

    except Exception as e:
        log.error("COMBO strategy %s: %s", symbol, e)
        result["veto_reason"] = f"Error: {str(e)[:40]}"

    return result


def _combo_score(cci_val, direction, has_reversal, has_momentum, bars_apart):
    """
    Score calculation:
    - Both patterns = 8-10 (strong)
    - Only one pattern = 6-7 (medium)
    - CCI extremity adds points
    - Closer patterns = better
    """
    if has_reversal and has_momentum:
        score = 7.5  # strong base for combo
        # Bars apart (closer = better — within 3 bars ideal)
        if bars_apart <= 3:   score += 1.5
        elif bars_apart <= 5: score += 1.0
        else:                 score += 0.5
    elif has_reversal:
        score = 5.5  # only reversal
    elif has_momentum:
        score = 6.0  # only momentum
    else:
        score = 4.0

    # CCI extremity
    cci_abs = abs(cci_val)
    if cci_abs > 150:  score += 1.0
    elif cci_abs > 100: score += 0.7
    elif cci_abs > 50:  score += 0.4

    return min(10.0, round(score, 1))


def get_combo_signal(connector, symbol, cfg):
    """
    Wrapper around _get_combo_signal_raw(): runs the existing pattern +
    CCI + ADX-trend-veto logic unchanged, then adds one more check — the
    trained candlestick-pattern ML model's next-candle prediction. If the
    model actively expects the OPPOSITE candle color from the trade
    direction, the signal is downgraded to WAIT instead of taken. If the
    model isn't ready yet (still training / not enough history), this
    fails OPEN — it never blocks a trade just because ML hasn't warmed up.
    """
    result = _get_combo_signal_raw(connector, symbol, cfg)

    if result["direction"] not in ("BUY", "SELL"):
        return result

    s_cfg = cfg.get("strategy", {})
    if not s_cfg.get("ml_filter_enabled", True) or not _HAS_ML:
        return result

    try:
        entry_tf = _get_primary_tf(cfg)
        # ML needs more history than the pattern logic to train a decent
        # model — ask for extra candles specifically for this.
        needed  = max(CCI_PERIOD, MA_PERIOD) + HAMMER_LOOKBACK + 200
        candles = connector.get_candles(symbol, entry_tf, needed)
        prob_bull, info = _pml.predict_latest(candles, symbol, entry_tf)
    except Exception as e:
        log.warning("ML filter %s: prediction failed (%s) — allowing trade "
                     "through unchecked", symbol, e)
        return result

    if prob_bull is None:
        result["ml_prob"] = None
        return result

    result["ml_prob"] = round(prob_bull * 100, 1)
    if info:
        result["ml_accuracy"] = info.get("accuracy")

    veto_margin = float(s_cfg.get("ml_veto_margin", 0.10))

    if result["direction"] == "BUY" and prob_bull < (0.5 - veto_margin):
        msg = ("ML veto: model predicts next candle BEARISH ({:.0f}% bullish), "
                "contradicts BUY").format(prob_bull * 100)
        log.info("[COMBO] %s — %s (was score=%.1f)", symbol, msg, result["score"])
        result = dict(result, direction="WAIT", score=0.0,
                      veto_reason=msg, vetoed=True)
        return result

    if result["direction"] == "SELL" and prob_bull > (0.5 + veto_margin):
        msg = ("ML veto: model predicts next candle BULLISH ({:.0f}% bullish), "
                "contradicts SELL").format(prob_bull * 100)
        log.info("[COMBO] %s — %s (was score=%.1f)", symbol, msg, result["score"])
        result = dict(result, direction="WAIT", score=0.0,
                      veto_reason=msg, vetoed=True)
        return result

    return result


def scan_all_combo(connector, symbols, cfg):
    """Scan all symbols with COMBO strategy."""
    results = []
    for sym in symbols:
        try:
            sig = get_combo_signal(connector, sym, cfg)
            results.append(sig)
        except Exception as e:
            log.error("COMBO scan %s: %s", sym, e)
    return results
