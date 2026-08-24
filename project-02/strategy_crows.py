#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Three Black Crows / Three White Soldiers + CCI Strategy
Inspired by: BlackCrows_WhiteSoldiers_CCI.ex5

Strategy:
  BUY  → Three White Soldiers + CCI confirmation
  SELL → Three Black Crows   + CCI confirmation

Three White Soldiers (Bullish):
  - 3 consecutive green (bullish) candles
  - Each opens WITHIN body of previous candle
  - Each closes NEAR its high (small upper wick)
  - Each candle BIGGER than previous (momentum)
  - CCI rising and > 0

Three Black Crows (Bearish):
  - 3 consecutive red (bearish) candles
  - Each opens WITHIN body of previous candle
  - Each closes NEAR its low (small lower wick)
  - Each candle BIGGER than previous (momentum)
  - CCI falling and < 0
"""

import logging
log = logging.getLogger(__name__)

# ── Parameters ────────────────────────────────────────────────────────────────
CCI_PERIOD       = 14     # CCI period
MA_PERIOD        = 20     # Trend SMA period
MIN_BODY_RATIO   = 0.5    # Candle body must be >50% of total range
MAX_WICK_RATIO   = 0.25   # Upper wick for soldiers / lower wick for crows < 25%
MIN_BODY_SIZE    = 0.0002 # Minimum body size (filter doji candles)
CCI_CONFIRM_BUY  = 0      # CCI > 0 for White Soldiers confirmation
CCI_CONFIRM_SELL = 0      # CCI < 0 for Black Crows confirmation

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


# ── Indicators ────────────────────────────────────────────────────────────────

def calc_sma(values, period):
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i-period+1:i+1]) / period)
    return result


def calc_cci(highs, lows, closes, period=CCI_PERIOD):
    tp = [(h+l+c)/3 for h,l,c in zip(highs, lows, closes)]
    result = []
    for i in range(len(tp)):
        if i < period - 1:
            result.append(None)
        else:
            window  = tp[i-period+1:i+1]
            sma_tp  = sum(window) / period
            mean_dev = sum(abs(x-sma_tp) for x in window) / period
            cci_val  = (tp[i] - sma_tp) / (0.015 * mean_dev) if mean_dev else 0.0
            result.append(round(cci_val, 2))
    return result


# ── Pattern detection ─────────────────────────────────────────────────────────

def is_bullish(candle):
    return candle["close"] > candle["open"]

def is_bearish(candle):
    return candle["close"] < candle["open"]

def body_size(candle):
    return abs(candle["close"] - candle["open"])

def candle_range(candle):
    return candle["high"] - candle["low"]

def body_ratio(candle):
    rng = candle_range(candle)
    return body_size(candle) / rng if rng > 0 else 0

def upper_wick_ratio(candle):
    rng = candle_range(candle)
    upper = candle["high"] - max(candle["open"], candle["close"])
    return upper / rng if rng > 0 else 0

def lower_wick_ratio(candle):
    rng = candle_range(candle)
    lower = min(candle["open"], candle["close"]) - candle["low"]
    return lower / rng if rng > 0 else 0


def detect_three_white_soldiers(c1, c2, c3):
    """
    Three White Soldiers:
    c3 = oldest, c2 = middle, c1 = newest (most recent)

    Rules:
    1. All 3 candles are bullish (green)
    2. Each opens within body of previous
    3. Each closes near its high (small upper wick)
    4. Bodies progressively same size or growing
    5. No very small candles (no dojis)
    """
    # 1. All bullish
    if not (is_bullish(c1) and is_bullish(c2) and is_bullish(c3)):
        return False, "Not all 3 bullish"

    # 2. No dojis
    if any(body_size(c) < MIN_BODY_SIZE for c in [c1, c2, c3]):
        return False, "Doji candle detected"

    # 3. Body ratios (strong candles)
    if any(body_ratio(c) < MIN_BODY_RATIO for c in [c1, c2, c3]):
        return False, "Weak candle body"

    # 4. Each opens within body of previous
    # c2 opens within c3's body
    if not (c3["open"] <= c2["open"] <= c3["close"]):
        return False, "c2 not opening in c3 body"

    # c1 opens within c2's body
    if not (c2["open"] <= c1["open"] <= c2["close"]):
        return False, "c1 not opening in c2 body"

    # 5. Each closes higher
    if not (c2["close"] > c3["close"] and c1["close"] > c2["close"]):
        return False, "Not closing progressively higher"

    # 6. Small upper wicks (closes near high)
    if any(upper_wick_ratio(c) > MAX_WICK_RATIO for c in [c1, c2, c3]):
        return False, "Upper wick too large"

    return True, "Three White Soldiers ✅"


def detect_three_black_crows(c1, c2, c3):
    """
    Three Black Crows:
    c3 = oldest, c2 = middle, c1 = newest

    Rules:
    1. All 3 candles are bearish (red)
    2. Each opens within body of previous
    3. Each closes near its low (small lower wick)
    4. Each closes lower than previous
    5. No dojis
    """
    # 1. All bearish
    if not (is_bearish(c1) and is_bearish(c2) and is_bearish(c3)):
        return False, "Not all 3 bearish"

    # 2. No dojis
    if any(body_size(c) < MIN_BODY_SIZE for c in [c1, c2, c3]):
        return False, "Doji candle detected"

    # 3. Body ratios (strong candles)
    if any(body_ratio(c) < MIN_BODY_RATIO for c in [c1, c2, c3]):
        return False, "Weak candle body"

    # 4. Each opens within body of previous
    # c2 opens within c3's body (between open and close of bearish c3)
    if not (c3["close"] <= c2["open"] <= c3["open"]):
        return False, "c2 not opening in c3 body"

    # c1 opens within c2's body
    if not (c2["close"] <= c1["open"] <= c2["open"]):
        return False, "c1 not opening in c2 body"

    # 5. Each closes lower
    if not (c2["close"] < c3["close"] and c1["close"] < c2["close"]):
        return False, "Not closing progressively lower"

    # 6. Small lower wicks (closes near low)
    if any(lower_wick_ratio(c) > MAX_WICK_RATIO for c in [c1, c2, c3]):
        return False, "Lower wick too large"

    return True, "Three Black Crows ✅"


# ── Score calculation ─────────────────────────────────────────────────────────

def calc_score(c1, c2, c3, cci_val, direction):
    """Score 0-10 based on pattern quality."""
    score = 5.0

    # CCI extremity
    cci_abs = abs(cci_val)
    if cci_abs > 150: score += 2.0
    elif cci_abs > 100: score += 1.5
    elif cci_abs > 50:  score += 1.0
    else:               score += 0.5

    # Consecutive body sizes (growing momentum = better)
    b3, b2, b1 = body_size(c3), body_size(c2), body_size(c1)
    if b1 >= b2 >= b3: score += 1.5  # perfect momentum
    elif b1 >= b2:      score += 1.0

    # Average body ratio (stronger candles = better)
    avg_br = (body_ratio(c1) + body_ratio(c2) + body_ratio(c3)) / 3
    if avg_br > 0.75: score += 1.0
    elif avg_br > 0.60: score += 0.5

    # Wick quality
    if direction == "BUY":
        avg_wick = (upper_wick_ratio(c1) + upper_wick_ratio(c2) + upper_wick_ratio(c3)) / 3
        if avg_wick < 0.10: score += 0.5  # tiny upper wicks = very strong
    else:
        avg_wick = (lower_wick_ratio(c1) + lower_wick_ratio(c2) + lower_wick_ratio(c3)) / 3
        if avg_wick < 0.10: score += 0.5

    return min(10.0, round(score, 1))


# ── Main signal function ──────────────────────────────────────────────────────

def get_crows_soldiers_signal(connector, symbol, cfg):
    """
    Main function — detect Three Black Crows / Three White Soldiers.
    Returns signal dict compatible with V5 format.
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

    s_cfg    = cfg.get("strategy", {})
    sl_mult  = float(s_cfg.get("sl_atr_multiplier", 1.5))
    tp_mult  = float(s_cfg.get("tp_atr_multiplier", 4.5))
    entry_tf = _get_primary_tf(cfg)

    try:
        needed  = max(CCI_PERIOD, MA_PERIOD) + 10
        candles = connector.get_candles(symbol, entry_tf, needed)
        if not candles or len(candles) < needed // 2:
            result["veto_reason"] = "Not enough data"
            return result

        n      = len(candles)
        opens  = [c["open"]  for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        closes = [c["close"] for c in candles]

        # Indicators
        cci_vals = calc_cci(highs, lows, closes, CCI_PERIOD)
        sma_vals = calc_sma(closes, MA_PERIOD)

        # Last 3 completed bars (MQL5: bar 1=prev, 2=prev-prev, 3=oldest)
        c1 = candles[n-2]  # most recent completed bar
        c2 = candles[n-3]
        c3 = candles[n-4]

        cci1 = cci_vals[n-2]
        cci2 = cci_vals[n-3]
        sma1 = sma_vals[n-2]

        if cci1 is None or cci2 is None:
            result["veto_reason"] = "Insufficient CCI data"
            return result

        result["cci_value"] = round(cci1, 1)

        # Current price
        bid, ask = connector.get_symbol_price(symbol)

        # ATR for SL/TP
        atr = sum(c["high"] - c["low"] for c in candles[-14:]) / 14

        # ── Check Three White Soldiers (BUY) ─────────────────────────────────
        tws, tws_msg = detect_three_white_soldiers(c1, c2, c3)
        if tws and cci1 > CCI_CONFIRM_BUY:
            score = calc_score(c1, c2, c3, cci1, "BUY")
            conf  = min(99, int(65 + abs(cci1) / 3))
            sl    = round(ask - sl_mult * atr, 5)
            tp    = round(ask + tp_mult * atr, 5)
            result.update({
                "direction":  "BUY",
                "score":      score,
                "confidence": conf,
                "regime":     "BULL" if sma1 and closes[-2] > sma1 else "NEUTRAL",
                "entry":      round(ask, 5),
                "sl": sl, "tp": tp, "atr": round(atr, 5),
                "pattern":    f"3 White Soldiers (CCI={cci1:.0f})",
                "m15": "BUY", "h1": "BUY",
            })
            log.info("[3CROW] 3 White Soldiers BUY %s sc=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            return result

        # ── Check Three Black Crows (SELL) ────────────────────────────────────
        tbc, tbc_msg = detect_three_black_crows(c1, c2, c3)
        if tbc and cci1 < -CCI_CONFIRM_SELL:
            score = calc_score(c1, c2, c3, cci1, "SELL")
            conf  = min(99, int(65 + abs(cci1) / 3))
            sl    = round(bid + sl_mult * atr, 5)
            tp    = round(bid - tp_mult * atr, 5)
            result.update({
                "direction":  "SELL",
                "score":      score,
                "confidence": conf,
                "regime":     "BEAR" if sma1 and closes[-2] < sma1 else "NEUTRAL",
                "entry":      round(bid, 5),
                "sl": sl, "tp": tp, "atr": round(atr, 5),
                "pattern":    f"3 Black Crows (CCI={cci1:.0f})",
                "m15": "SELL", "h1": "SELL",
            })
            log.info("[3CROW] 3 Black Crows SELL %s sc=%.1f CCI=%.1f TF=%s", symbol, score, cci1, entry_tf)
            return result

        # No pattern
        if tws:
            result["veto_reason"] = f"3 White Soldiers but CCI={cci1:.0f} (need >0)"
        elif tbc:
            result["veto_reason"] = f"3 Black Crows but CCI={cci1:.0f} (need <0)"
        else:
            # Show nearest pattern attempt
            result["veto_reason"] = tws_msg if not is_bearish(c1) else tbc_msg

    except Exception as e:
        log.error("3Crows strategy %s: %s", symbol, e)
        result["veto_reason"] = f"Error: {str(e)[:40]}"

    return result


def scan_all_crows(connector, symbols, cfg):
    """Scan all symbols with 3 Crows/Soldiers strategy."""
    results = []
    for sym in symbols:
        try:
            sig = get_crows_soldiers_signal(connector, sym, cfg)
            results.append(sig)
        except Exception as e:
            log.error("3Crows scan %s: %s", sym, e)
    return results


# ── CCI-based Close Signal ────────────────────────────────────────────────────

def get_cci_close_signal(connector, symbol, cfg, position_type):
    """
    Check if open position should be closed based on CCI.
    
    Close BUY  when: CCI crosses below +80 OR CCI crosses below -80
    Close SELL when: CCI crosses above -80 OR CCI crosses above +80
    
    Returns: (should_close: bool, reason: str)
    """
    close_level = float(cfg.get("strategy",{}).get("cci_close_level", 80))
    entry_tf    = _get_primary_tf(cfg)
    
    try:
        candles = connector.get_candles(symbol, entry_tf, CCI_PERIOD + 5)
        if not candles or len(candles) < CCI_PERIOD + 2:
            return False, "Not enough data"
        
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        closes = [c["close"] for c in candles]
        cci    = calc_cci(highs, lows, closes, CCI_PERIOD)
        
        n    = len(cci)
        cci1 = cci[n-2]   # latest completed bar
        cci2 = cci[n-3]   # previous bar
        
        if cci1 is None or cci2 is None:
            return False, "CCI not ready"
        
        if position_type == "BUY":
            # Close BUY if CCI crosses below +80 (momentum lost)
            if cci2 > close_level and cci1 < close_level:
                return True, f"CCI crossed below +{close_level:.0f} ({cci1:.0f}) — BUY momentum ended"
            # Close BUY if CCI crosses below -80 (reversal)
            if cci2 > -close_level and cci1 < -close_level:
                return True, f"CCI crossed below -{close_level:.0f} ({cci1:.0f}) — trend reversed"
                
        elif position_type == "SELL":
            # Close SELL if CCI crosses above -80 (momentum lost)
            if cci2 < -close_level and cci1 > -close_level:
                return True, f"CCI crossed above -{close_level:.0f} ({cci1:.0f}) — SELL momentum ended"
            # Close SELL if CCI crosses above +80 (reversal)
            if cci2 < close_level and cci1 > close_level:
                return True, f"CCI crossed above +{close_level:.0f} ({cci1:.0f}) — trend reversed"
        
        return False, f"CCI={cci1:.0f} — hold position"
        
    except Exception as e:
        log.error("CCI close check %s: %s", symbol, e)
        return False, str(e)
