#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hanging Man / Hammer + CCI Strategy
Ported from: HangingMan Hammer CCI.mq5 (MetaQuotes Ltd.)

Strategy:
  SELL → Hanging Man detected + CCI > 50  (uptrend reversal)
  BUY  → Hammer detected    + CCI < -50  (downtrend reversal)
  Close → CCI crosses ±80 level
"""

import logging
import numpy as np

log = logging.getLogger(__name__)

# ── Parameters (same as MQL5 defaults) ───────────────────────────────────────
AVG_BODY_PERIOD = 12    # average candle body size period
MA_PERIOD       = 5     # SMA trend period
CCI_PERIOD      = 37    # CCI period
CCI_CONFIRM_BUY  = -50  # CCI threshold to confirm BUY
CCI_CONFIRM_SELL =  50  # CCI threshold to confirm SELL
CCI_CLOSE_LEVEL  =  80  # CCI level to close positions

# ── TF mapping ────────────────────────────────────────────────────────────────
_TF_MAP = {
    "M5":        "M5",
    "M15":       "M15",
    "H1":        "H1",
    "H4":        "H4",
    "M15_H1_H4": "M15",   # default multi-TF: M15 as entry candle
    "ALL":       "M15",   # ALL 5-TF: M15 as entry candle
}

def _get_primary_tf(cfg: dict) -> str:
    """Return the entry-candle timeframe from config (M5/M15/H1/H4)."""
    tf_mode = cfg.get("strategy", {}).get("tf_mode", "M15_H1_H4")
    return _TF_MAP.get(tf_mode, "M15")


# ── Indicator calculations ────────────────────────────────────────────────────

def calc_sma(closes: list, period: int) -> list:
    """Simple Moving Average"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i-period+1:i+1]) / period)
    return result


def calc_cci(highs: list, lows: list, closes: list, period: int) -> list:
    """
    Commodity Channel Index
    CCI = (TP - SMA(TP)) / (0.015 * MeanDeviation)
    TP = (High + Low + Close) / 3
    """
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    result = []
    for i in range(len(tp)):
        if i < period - 1:
            result.append(None)
        else:
            window = tp[i-period+1:i+1]
            sma_tp = sum(window) / period
            mean_dev = sum(abs(x - sma_tp) for x in window) / period
            if mean_dev == 0:
                result.append(0.0)
            else:
                result.append((tp[i] - sma_tp) / (0.015 * mean_dev))
    return result


def avg_body(opens: list, closes: list, index: int, period: int = AVG_BODY_PERIOD) -> float:
    """Average candle body size over last N bars"""
    total = 0.0
    count = 0
    for i in range(index, min(index + period, len(opens))):
        total += abs(opens[i] - closes[i])
        count += 1
    return total / count if count > 0 else 0.0


def mid_point(high: float, low: float) -> float:
    """Candle midpoint"""
    return (high + low) / 2.0


# ── Pattern detection ─────────────────────────────────────────────────────────

def detect_hanging_man(candles: list, sma: list, index: int = 1) -> bool:
    """
    Hanging Man (SELL signal — bearish reversal at top):
    1. MidPoint(1) > SMA(2)  → uptrend
    2. Body in upper 1/3 of candle
    3. Close(1) > Close(2) AND Open(1) > Open(2)  → gap up
    """
    if index + 1 >= len(candles) or sma[index+1] is None:
        return False

    c1 = candles[index]      # current candle
    c2 = candles[index + 1]  # previous candle

    h1, l1 = c1["high"], c1["low"]
    o1, cl1 = c1["open"], c1["close"]
    cl2, o2 = c2["close"], c2["open"]
    sma2 = sma[index + 1]

    # 1. Uptrend
    if mid_point(h1, l1) <= sma2:
        return False

    # 2. Body in upper 1/3
    upper_third = h1 - (h1 - l1) / 3.0
    if min(o1, cl1) <= upper_third:
        return False

    # 3. Gap up (body above previous)
    if not (cl1 > cl2 and o1 > o2):
        return False

    return True


def detect_hammer(candles: list, sma: list, index: int = 1) -> bool:
    """
    Hammer (BUY signal — bullish reversal at bottom):
    1. MidPoint(1) < SMA(2)  → downtrend
    2. Body in upper 1/3 of candle
    3. Close(1) < Close(2) AND Open(1) < Open(2)  → gap down
    """
    if index + 1 >= len(candles) or sma[index+1] is None:
        return False

    c1 = candles[index]
    c2 = candles[index + 1]

    h1, l1 = c1["high"], c1["low"]
    o1, cl1 = c1["open"], c1["close"]
    cl2, o2 = c2["close"], c2["open"]
    sma2 = sma[index + 1]

    # 1. Downtrend
    if mid_point(h1, l1) >= sma2:
        return False

    # 2. Body in upper 1/3
    upper_third = h1 - (h1 - l1) / 3.0
    if min(o1, cl1) <= upper_third:
        return False

    # 3. Gap down (body below previous)
    if not (cl1 < cl2 and o1 < o2):
        return False

    return True


def check_close_signal(cci: list, index: int = 1) -> str:
    """
    Close signal when CCI crosses ±80:
    Returns: 'CLOSE_LONG', 'CLOSE_SHORT', or ''
    """
    if index + 1 >= len(cci) or cci[index] is None or cci[index+1] is None:
        return ''

    c1 = cci[index]
    c2 = cci[index + 1]

    # CCI crosses below ±80 → close LONG
    if (c1 < 80 and c2 > 80) or (c1 < -80 and c2 > -80):
        return 'CLOSE_LONG'

    # CCI crosses above ±80 → close SHORT
    if (c1 > -80 and c2 < -80) or (c1 > 80 and c2 < 80):
        return 'CLOSE_SHORT'

    return ''


# ── Main signal function ──────────────────────────────────────────────────────

def get_mql5_signal(connector, symbol: str, cfg: dict) -> dict:
    """
    Main function: get Hanging Man / Hammer + CCI signal.
    Returns dict compatible with V5 signal format.
    """
    result = {
        "symbol":      symbol,
        "direction":   "WAIT",
        "score":       0.0,
        "confidence":  0,
        "regime":      "NEUTRAL",
        "veto_reason": "",
        "vetoed":      False,
        "m15":         "NEUTRAL",
        "h1":          "NEUTRAL",
        "h4":          "NEUTRAL",
        "rsi":         50.0,
        "adx":         0.0,
        "entry":       0.0,
        "sl":          0.0,
        "tp":          0.0,
        "atr":         0.0,
        "pattern":     "",
        "cci_value":   0.0,
        "signal_time": "",
    }

    s_cfg = cfg.get("strategy", {})
    sl_mult = float(s_cfg.get("sl_atr_multiplier", 1.5))
    tp_mult = float(s_cfg.get("tp_atr_multiplier", 4.5))
    entry_tf = _get_primary_tf(cfg)

    try:
        # Get candles — need enough for CCI + SMA + pattern
        needed = CCI_PERIOD + AVG_BODY_PERIOD + 5
        candles = connector.get_candles(symbol, entry_tf, needed)
        if not candles or len(candles) < needed // 2:
            result["veto_reason"] = "Not enough candle data"
            return result

        # Reverse so index 0 = oldest, index -1 = newest (like Python lists)
        # But MQL5 uses index 0 = current, 1 = previous
        # Our candles are oldest→newest, so index -1 is current
        n = len(candles)

        opens  = [c["open"]  for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        closes = [c["close"] for c in candles]

        # Calculate indicators
        sma_vals = calc_sma(closes, MA_PERIOD)
        cci_vals  = calc_cci(highs, lows, closes, CCI_PERIOD)

        # MQL5 index 1 = second to last in our list (previous completed bar)
        # MQL5 index 2 = third to last
        # We use negative indexing: -2 = index 1 (previous bar), -3 = index 2

        # Build candle dicts for pattern functions (MQL5 style: 1=prev, 2=prev-prev)
        def get_mql_candle(mql_index):
            py_idx = n - 1 - mql_index  # convert MQL index to Python index
            if py_idx < 0 or py_idx >= n:
                return None
            return candles[py_idx]

        def get_mql_sma(mql_index):
            py_idx = n - 1 - mql_index
            if py_idx < 0 or py_idx >= n:
                return None
            return sma_vals[py_idx]

        def get_mql_cci(mql_index):
            py_idx = n - 1 - mql_index
            if py_idx < 0 or py_idx >= n:
                return None
            return cci_vals[py_idx]

        # Check patterns using MQL5 logic
        c1   = get_mql_candle(1)
        c2   = get_mql_candle(2)
        sma2 = get_mql_sma(2)
        cci1 = get_mql_cci(1)
        cci2 = get_mql_cci(2)

        if not c1 or not c2 or sma2 is None or cci1 is None:
            result["veto_reason"] = "Insufficient indicator data"
            return result

        h1, l1  = c1["high"], c1["low"]
        o1, cl1 = c1["open"], c1["close"]
        cl2, o2 = c2["close"], c2["open"]
        upper_third = h1 - (h1 - l1) / 3.0

        result["cci_value"] = round(cci1, 1)

        # ── Hanging Man (SELL) ────────────────────────────────────────────────
        hanging_man = (
            mid_point(h1, l1) > sma2          and  # uptrend
            min(o1, cl1) > upper_third         and  # body in upper 1/3
            cl1 > cl2 and o1 > o2                   # gap up
        )

        # ── Hammer (BUY) ──────────────────────────────────────────────────────
        hammer = (
            mid_point(h1, l1) < sma2          and  # downtrend
            min(o1, cl1) > upper_third         and  # body in upper 1/3
            cl1 < cl2 and o1 < o2                   # gap down
        )

        # Current price for entry/SL/TP
        bid, ask = connector.get_symbol_price(symbol)
        price = ask if hammer else bid

        # ATR for SL/TP
        atr = sum(c["high"] - c["low"] for c in candles[-14:]) / 14

        if hanging_man:
            # Confirm with CCI > 50
            if cci1 > CCI_CONFIRM_SELL:
                sl = round(price + sl_mult * atr, 5)
                tp = round(price - tp_mult * atr, 5)
                score = _calc_score(cci1, "SELL", sma2, c1)
                result.update({
                    "direction":  "SELL",
                    "score":      score,
                    "confidence": min(99, int(70 + abs(cci1 - 50) / 2)),
                    "regime":     "BEAR",
                    "entry":      round(price, 5),
                    "sl":         sl,
                    "tp":         tp,
                    "atr":        round(atr, 5),
                    "pattern":    f"Hanging Man (CCI={cci1:.0f})",
                    "m15":        "SELL",
                })
                log.info("[MQL5] Hanging Man SELL %s score=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            else:
                result["veto_reason"] = f"Hanging Man seen but CCI={cci1:.0f} < 50 (need >50)"

        elif hammer:
            # Confirm with CCI < -50
            if cci1 < CCI_CONFIRM_BUY:
                sl = round(price - sl_mult * atr, 5)
                tp = round(price + tp_mult * atr, 5)
                score = _calc_score(cci1, "BUY", sma2, c1)
                result.update({
                    "direction":  "BUY",
                    "score":      score,
                    "confidence": min(99, int(70 + abs(cci1 + 50) / 2)),
                    "regime":     "BULL",
                    "entry":      round(price, 5),
                    "sl":         sl,
                    "tp":         tp,
                    "atr":        round(atr, 5),
                    "pattern":    f"Hammer (CCI={cci1:.0f})",
                    "m15":        "BUY",
                })
                log.info("[MQL5] Hammer BUY %s score=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            else:
                result["veto_reason"] = f"Hammer seen but CCI={cci1:.0f} > -50 (need < -50)"

        else:
            result["veto_reason"] = "No Hanging Man / Hammer pattern"

    except Exception as e:
        log.error("MQL5 strategy error %s: %s", symbol, e)
        result["veto_reason"] = f"Error: {str(e)[:40]}"

    return result


def _calc_score(cci_val: float, direction: str, sma: float, candle: dict) -> float:
    """
    Score 0-10 based on signal strength:
    - CCI extremity
    - Body size vs range
    - Long wick (confirmation)
    """
    score = 5.0

    # CCI strength
    cci_dist = abs(cci_val) - 50
    if cci_dist > 100: score += 2.0
    elif cci_dist > 50: score += 1.5
    elif cci_dist > 20: score += 1.0
    else: score += 0.5

    # Body size (small body = stronger pattern)
    rng = candle["high"] - candle["low"]
    body = abs(candle["open"] - candle["close"])
    if rng > 0:
        body_pct = body / rng
        if body_pct < 0.2: score += 1.5  # tiny body = strong signal
        elif body_pct < 0.3: score += 1.0
        else: score += 0.5

    # Wick length (long lower wick for hammer = better)
    if direction == "BUY":
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        if rng > 0 and lower_wick / rng > 0.6: score += 1.5
        elif rng > 0 and lower_wick / rng > 0.4: score += 1.0
    elif direction == "SELL":
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        if rng > 0 and upper_wick / rng > 0.4: score += 1.0

    return min(10.0, round(score, 1))


def scan_all_mql5(connector, symbols: list, cfg: dict) -> list:
    """Scan all symbols with MQL5 strategy."""
    results = []
    for sym in symbols:
        try:
            sig = get_mql5_signal(connector, sym, cfg)
            results.append(sig)
        except Exception as e:
            log.error("MQL5 scan %s: %s", sym, e)
    return results
