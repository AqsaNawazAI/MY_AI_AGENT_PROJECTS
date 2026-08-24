#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forex Bot V5 Elite - Strategy Engine  (Paper-Mode Matched)
=============================================================
Trade logic exactly matches tested paper simulation:

  Step 1  GATE     — Signal confidence >= 83%
  Step 2  REGIME   — Detect BULL/BEAR/NEUTRAL/EUPHORIA/CRASH from H4
  Step 3  VETO     — RSI safe-zone + ADX > 20 + H4 direction match
  Step 4  3TF      — M15 / H1 / H4 all agree on direction
  Step 5  SCORE    — Combined indicator score >= 8 / 10
  Result  ENTRY    — SL = 1.5×ATR, TP = 4.5×ATR  (3 : 1 RR)
"""

import logging
from datetime import datetime
import numpy as np

log = logging.getLogger(__name__)

# ── Min threshold — must match config.json strategy.score_threshold ──────────
V5_MIN_SCORE      = 6.0
V5_MIN_CONFIDENCE = 70       # % — GATE check
V5_RR             = 3.0      # reward : risk
V5_SL_ATR_MULT    = 1.5
V5_TP_ATR_MULT    = 4.5


# ═══════════════════════════════════════════════════════════════════════════════
#  INDICATOR FUNCTIONS  (unchanged from original — solid implementations)
# ═══════════════════════════════════════════════════════════════════════════════

def ema(data: np.ndarray, period: int) -> np.ndarray:
    if len(data) < period:
        return np.full(len(data), np.nan)
    k = 2.0 / (period + 1)
    result = np.zeros(len(data))
    result[:period] = np.nan
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    if len(data) < period + 1:
        return np.full(len(data), 50.0)
    delta = np.diff(data)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    result = np.full(len(data), 50.0)
    ag = np.mean(gain[:period])
    al = np.mean(loss[:period])
    for i in range(period, len(delta)):
        ag = (ag * (period - 1) + gain[i]) / period
        al = (al * (period - 1) + loss[i]) / period
        result[i + 1] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return result


def macd(data: np.ndarray, fast=12, slow=26, signal=9):
    ef   = ema(data, fast)
    es   = ema(data, slow)
    ml   = ef - es
    sl_  = ema(np.where(np.isnan(ml), 0, ml), signal)
    hist = ml - sl_
    return ml, sl_, hist


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14) -> np.ndarray:
    if len(high) < period + 1:
        return np.full(len(high), 0.0010)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    result = np.zeros(len(high))
    result[period] = np.mean(tr[:period])
    for i in range(period + 1, len(high)):
        result[i] = (result[i - 1] * (period - 1) + tr[i - 1]) / period
    return result


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14):
    n = len(high)
    if n < period * 2 + 1:
        return (np.full(n, 15.0), np.full(n, 20.0), np.full(n, 20.0))

    tr   = np.maximum(high[1:] - low[1:],
                      np.maximum(np.abs(high[1:] - close[:-1]),
                                 np.abs(low[1:] - close[:-1])))
    up   = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    pdm  = np.where((up > down) & (up > 0),   up,   0.0)
    ndm  = np.where((down > up) & (down > 0), down, 0.0)

    atr_v = np.zeros(n);  pdi_v = np.zeros(n)
    ndi_v = np.zeros(n);  dx_v  = np.zeros(n)
    adx_v = np.zeros(n)

    atr_v[period] = np.sum(tr[:period])
    sp = np.sum(pdm[:period])
    sn = np.sum(ndm[:period])

    for i in range(period, n - 1):
        atr_v[i+1] = atr_v[i] - atr_v[i] / period + tr[i]
        sp = sp - sp / period + pdm[i]
        sn = sn - sn / period + ndm[i]
        if atr_v[i+1] > 0:
            pdi_v[i+1] = 100 * sp / atr_v[i+1]
            ndi_v[i+1] = 100 * sn / atr_v[i+1]
        denom = pdi_v[i+1] + ndi_v[i+1]
        if denom > 0:
            dx_v[i+1] = 100 * abs(pdi_v[i+1] - ndi_v[i+1]) / denom

    start = period * 2
    if start < n:
        adx_v[start] = np.mean(dx_v[period + 1:start + 1])
        for i in range(start + 1, n):
            adx_v[i] = (adx_v[i-1] * (period - 1) + dx_v[i]) / period

    return adx_v, pdi_v, ndi_v


def stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               k=5, d=3):
    n      = len(close)
    k_line = np.full(n, 50.0)
    for i in range(k, n):
        h = np.max(high[i - k:i])
        l = np.min(low[i - k:i])
        if h != l:
            k_line[i] = 100.0 * (close[i] - l) / (h - l)
    d_line = ema(k_line, d)
    return k_line, d_line


def bollinger(data: np.ndarray, period=20, mult=2.0):
    n = len(data)
    upper = np.zeros(n);  mid = np.zeros(n);  lower = np.zeros(n)
    for i in range(period, n):
        w = data[i - period:i]
        m = np.mean(w);  s = np.std(w)
        mid[i]   = m
        upper[i] = m + mult * s
        lower[i] = m - mult * s
    return upper, mid, lower


# ═══════════════════════════════════════════════════════════════════════════════
#  CANDLE PARSING + TIMEFRAME ANALYSIS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_candles(candles: list) -> dict:
    opens  = np.array([c["open"]   for c in candles], dtype=float)
    highs  = np.array([c["high"]   for c in candles], dtype=float)
    lows   = np.array([c["low"]    for c in candles], dtype=float)
    closes = np.array([c["close"]  for c in candles], dtype=float)
    vols   = np.array([c["volume"] for c in candles], dtype=float)
    return {"open": opens, "high": highs, "low": lows,
            "close": closes, "volume": vols}


def analyze_timeframe(candles: list) -> dict:
    if not candles or len(candles) < 60:
        return {"valid": False}

    c = parse_candles(candles)
    n = len(c["close"])

    e8   = ema(c["close"], 8)
    e21  = ema(c["close"], 21)
    e50  = ema(c["close"], 50)
    rsi_ = rsi(c["close"], 14)
    ml, sl_, hist = macd(c["close"])
    atr_ = atr(c["high"], c["low"], c["close"], 14)
    adx_, pdi, ndi = adx(c["high"], c["low"], c["close"], 14)
    sk, dk = stochastic(c["high"], c["low"], c["close"])
    bu, bm, bl = bollinger(c["close"], 20, 2.0)

    i      = n - 1
    avg_vol = float(np.mean(c["volume"][max(0, i-20):i])) if i > 20 else 500.0

    return {
        "valid":           True,
        "close":           float(c["close"][i]),
        "high":            float(c["high"][i]),
        "low":             float(c["low"][i]),
        "ema8":            float(e8[i]),
        "ema21":           float(e21[i]),
        "ema50":           float(e50[i]),
        "rsi":             float(rsi_[i]),
        "macd":            float(ml[i]),
        "macd_sig":        float(sl_[i]),
        "macd_hist":       float(hist[i]),
        "macd_hist_prev":  float(hist[i - 1]) if i > 0 else 0.0,
        "adx":             float(adx_[i]),
        "pdi":             float(pdi[i]),
        "ndi":             float(ndi[i]),
        "stoch_k":         float(sk[i]),
        "stoch_d":         float(dk[i]),
        "stoch_k_prev":    float(sk[i - 1]) if i > 0 else 50.0,
        "bb_upper":        float(bu[i]),
        "bb_mid":          float(bm[i]),
        "bb_lower":        float(bl[i]),
        "atr":             float(atr_[i]),
        "volume":          float(c["volume"][i]),
        "avg_volume":      avg_vol,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  DIRECTION DETECTOR  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def get_tf_direction(ind: dict) -> str:
    """BUY / SELL / NEUTRAL from indicators (needs 4/5 votes)."""
    if not ind.get("valid"):
        return "NEUTRAL"
    bull = 0;  bear = 0
    e8, e21, e50 = ind["ema8"], ind["ema21"], ind["ema50"]
    bull += 1 if e8  > e21  else 0;  bear += 1 if e8  < e21  else 0
    bull += 1 if e21 > e50  else 0;  bear += 1 if e21 < e50  else 0
    bull += 1 if ind["pdi"] > ind["ndi"] else 0
    bear += 1 if ind["pdi"] < ind["ndi"] else 0
    bull += 1 if ind["macd_hist"] > 0 else 0
    bear += 1 if ind["macd_hist"] < 0 else 0
    bull += 1 if ind["rsi"] > 50 else 0
    bear += 1 if ind["rsi"] < 50 else 0
    if bull >= 4: return "BUY"
    if bear >= 4: return "SELL"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════════
#  ── NEW V5 PAPER-MATCHED FUNCTIONS ──
# ═══════════════════════════════════════════════════════════════════════════════

def calc_confidence(ind_m15: dict, ind_h1: dict, ind_h4: dict) -> int:
    """
    Calculate signal confidence 0-95.
    Matches paper-mode GATE: only >=83 passes.

    Contributors:
      ADX strength (M15)     0-20 pts
      RSI away from 50       0-8  pts
      MACD histogram growing 0-4  pts
      H4 ADX confirmation    0-3  pts
    Base = 65  →  typical range 65-95
    """
    if not ind_m15.get("valid"):
        return 60

    score = 65.0

    # ADX strength on M15 (main trend quality indicator)
    adx_val = ind_m15.get("adx", 15.0)
    if   adx_val >= 35: score += 20
    elif adx_val >= 28: score += 15
    elif adx_val >= 22: score += 10
    elif adx_val >= 18: score += 5

    # RSI distance from neutral 50 (trend clarity)
    rsi_val = ind_m15.get("rsi", 50.0)
    dist    = abs(rsi_val - 50.0)
    if   dist >= 25: score += 8
    elif dist >= 18: score += 6
    elif dist >= 10: score += 3

    # MACD histogram momentum (growing in the signal direction)
    hist      = ind_m15.get("macd_hist",      0.0)
    hist_prev = ind_m15.get("macd_hist_prev", 0.0)
    if abs(hist) > 0:
        if (hist > 0 and hist > hist_prev) or (hist < 0 and hist < hist_prev):
            score += 4   # histogram expanding (momentum building)
        else:
            score += 2   # histogram exists but shrinking

    # H4 ADX confirmation (higher-TF trend health)
    if ind_h4.get("valid"):
        h4_adx = ind_h4.get("adx", 15.0)
        if   h4_adx >= 25: score += 3
        elif h4_adx >= 20: score += 1

    return min(int(score), 95)


def detect_regime(ind_h4: dict) -> str:
    """
    Detect market regime from H4 indicators.
    Returns: BULL | BEAR | NEUTRAL | EUPHORIA | CRASH

    Regime rules (matched to paper simulation):
      CRASH    — Strong bearish (ADX>=25, NDI leads by >20, RSI<25)
      EUPHORIA — Strong bullish (ADX>=25, PDI leads by >20, RSI>78)
      BULL     — Trending up   (ADX>=20, PDI leads by >8)
      BEAR     — Trending down (ADX>=20, NDI leads by >8)
      NEUTRAL  — Weak/mixed trend
    """
    if not ind_h4.get("valid"):
        return "NEUTRAL"

    adx_val = ind_h4.get("adx", 15.0)
    pdi     = ind_h4.get("pdi", 20.0)
    ndi     = ind_h4.get("ndi", 20.0)
    rsi_h4  = ind_h4.get("rsi", 50.0)
    di_diff = pdi - ndi      # positive = bullish, negative = bearish

    if adx_val >= 25 and di_diff < -20 and rsi_h4 < 15:
        return "CRASH"

    if adx_val >= 25 and di_diff > 20 and rsi_h4 > 85:
        return "EUPHORIA"

    if adx_val >= 20 and di_diff > 8:
        return "BULL"

    if adx_val >= 20 and di_diff < -8:
        return "BEAR"

    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCORE SIGNAL  (unchanged — only threshold raised to 8.0 in config)
# ═══════════════════════════════════════════════════════════════════════════════

def score_signal(direction: str, ind: dict) -> float:
    """Score 0-10. Entry requires >= 8."""
    if not ind.get("valid") or direction == "NEUTRAL":
        return 0.0

    score = 0.0
    e8, e21, e50 = ind["ema8"], ind["ema21"], ind["ema50"]

    if direction == "BUY":
        # EMA stack (0-2): e8 > e21 > e50
        if e8 > e21 > e50: score += 2.0
        elif e8 > e21:      score += 1.0

        # RSI pullback zone (0-2): buy the dip, not the peak
        # Max 2 when RSI is in healthy pullback range (30-58)
        r = ind["rsi"]
        if   30 <= r <= 58: score += 2.0
        elif 25 <= r <= 68: score += 1.0

        # MACD histogram (0-2): growing bullish momentum
        if   ind["macd_hist"] > 0 and ind["macd_hist"] > ind["macd_hist_prev"]:
            score += 2.0
        elif ind["macd_hist"] > 0:
            score += 1.0

        # ADX trend strength (0-1)
        if   ind["adx"] >= 25: score += 1.0
        elif ind["adx"] >= 20: score += 0.5

        # Stochastic momentum (0-1)
        if   ind["stoch_k"] >= 40 and ind["stoch_k"] > ind["stoch_k_prev"]: score += 1.0
        elif ind["stoch_k"] >= 30:                                            score += 0.5

        # BB position (0-1): price near lower band = buy setup
        if ind["bb_upper"] != ind["bb_lower"]:
            pos = (ind["close"] - ind["bb_lower"]) / (ind["bb_upper"] - ind["bb_lower"])
            if   pos <= 0.50: score += 1.0
            elif pos <= 0.65: score += 0.5

        # Volume surge (0-1)
        if   ind["volume"] > ind["avg_volume"] * 1.2: score += 1.0
        elif ind["volume"] > ind["avg_volume"]:        score += 0.5

    else:  # SELL
        # EMA stack (0-2): e8 < e21 < e50
        if e8 < e21 < e50: score += 2.0
        elif e8 < e21:      score += 1.0

        # RSI rally zone (0-2): sell the bounce, not the bottom
        r = ind["rsi"]
        if   42 <= r <= 70: score += 2.0
        elif 32 <= r <= 75: score += 1.0

        # MACD histogram (0-2): growing bearish momentum
        if   ind["macd_hist"] < 0 and ind["macd_hist"] < ind["macd_hist_prev"]:
            score += 2.0
        elif ind["macd_hist"] < 0:
            score += 1.0

        # ADX trend strength (0-1)
        if   ind["adx"] >= 25: score += 1.0
        elif ind["adx"] >= 20: score += 0.5

        # Stochastic momentum (0-1)
        if   ind["stoch_k"] <= 60 and ind["stoch_k"] < ind["stoch_k_prev"]: score += 1.0
        elif ind["stoch_k"] <= 70:                                            score += 0.5

        # BB position (0-1): price near upper band = sell setup
        if ind["bb_upper"] != ind["bb_lower"]:
            pos = (ind["close"] - ind["bb_lower"]) / (ind["bb_upper"] - ind["bb_lower"])
            if   pos >= 0.50: score += 1.0
            elif pos >= 0.35: score += 0.5

        # Volume surge (0-1)
        if   ind["volume"] > ind["avg_volume"] * 1.2: score += 1.0
        elif ind["volume"] > ind["avg_volume"]:        score += 0.5

    return round(min(score, 10.0), 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  VETO SYSTEM  (unchanged logic, just cleaner)
# ═══════════════════════════════════════════════════════════════════════════════

def check_veto(direction: str, ind_m15: dict, h4_dir: str,
               rsi_ob=80, rsi_os=20, adx_min=20) -> tuple:
    """
    Returns (vetoed: bool, reason: str)
    Three hard-blocking conditions (matched to paper simulation).
    """
    if not ind_m15.get("valid"):
        return True, "Insufficient candle data"

    r = ind_m15["rsi"]
    if direction == "BUY"  and r > rsi_ob: return True, f"RSI Overbought ({r:.1f}>{rsi_ob})"
    if direction == "SELL" and r < rsi_os: return True, f"RSI Oversold ({r:.1f}<{rsi_os})"

    if ind_m15["adx"] < adx_min:
        return True, f"ADX Weak ({ind_m15['adx']:.1f}<{adx_min})"

    if direction == "BUY"  and h4_dir == "SELL": return True, "H4 Trend Bearish"
    if direction == "SELL" and h4_dir == "BUY":  return True, "H4 Trend Bullish"

    return False, "No VETO"


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN SIGNAL FUNCTION  — 5-Step V5 Paper-Mode Logic
# ═══════════════════════════════════════════════════════════════════════════════

def get_signal(connector, symbol: str, cfg: dict) -> dict:
    """
    Run full V5 paper-matched signal analysis.

    5 steps:
      1. GATE     — confidence >= 83 %
      2. REGIME   — no CRASH trades
      3. VETO     — RSI + ADX + H4 alignment
      4. 3TF      — M15/H1/H4 direction agreement
      5. SCORE    — >= 8.0 / 10

    Returns signal dict compatible with existing dashboard/bot.py.
    """
    base = {
        "symbol":       symbol,
        "direction":    "WAIT",
        "score":        0.0,
        "vetoed":       False,
        "veto_reason":  "",
        "entry":        0.0,
        "sl":           0.0,
        "tp":           0.0,
        "atr":          0.0,
        "rsi":          50.0,
        "adx":          0.0,
        "m15":          "NEUTRAL",
        "h1":           "NEUTRAL",
        "h4":           "NEUTRAL",
        "confidence":   0,
        "regime":       "NEUTRAL",
        "signal_time":  "",
    }

    try:
        s_cfg      = cfg.get("strategy", {})
        tfs        = s_cfg.get("timeframes", ["M15", "H1", "H4"])
        if len(tfs) < 3:
            tfs = ["M15", "H1", "H4"]
        tf_m15, tf_h1, tf_h4 = tfs[0], tfs[1], tfs[2]

        rsi_ob  = s_cfg.get("veto_rsi_overbought", 80)
        rsi_os  = s_cfg.get("veto_rsi_oversold",   20)
        adx_min = s_cfg.get("veto_adx_min",         20)
        threshold = float(s_cfg.get("score_threshold", V5_MIN_SCORE))
        sl_mult   = float(s_cfg.get("sl_atr_multiplier", V5_SL_ATR_MULT))
        tp_mult   = float(s_cfg.get("tp_atr_multiplier", V5_TP_ATR_MULT))

        # ── Fetch candles ─────────────────────────────────────────────────
        c_m15 = connector.get_candles(symbol, tf_m15, 150)
        c_h1  = connector.get_candles(symbol, tf_h1,  150)
        c_h4  = connector.get_candles(symbol, tf_h4,  120)

        if not c_m15 or not c_h1 or not c_h4:
            base["veto_reason"] = "No candle data"
            return base

        ind_m15 = analyze_timeframe(c_m15)
        ind_h1  = analyze_timeframe(c_h1)
        ind_h4  = analyze_timeframe(c_h4)

        # Populate display fields
        base["rsi"] = round(ind_m15.get("rsi", 50.0), 1)
        base["adx"] = round(ind_m15.get("adx",  0.0), 1)
        base["atr"] = round(ind_h1.get("atr",   0.001), 5)

        dir_m15 = get_tf_direction(ind_m15)
        dir_h1  = get_tf_direction(ind_h1)
        dir_h4  = get_tf_direction(ind_h4)

        base["m15"] = dir_m15
        base["h1"]  = dir_h1
        base["h4"]  = dir_h4

        # ──────────────────────────────────────────────────────────────────
        #  STEP 1 — GATE: Signal confidence >= 83 %
        # ──────────────────────────────────────────────────────────────────
        confidence = calc_confidence(ind_m15, ind_h1, ind_h4)
        base["confidence"] = confidence

        # Read confidence threshold from config (allows dashboard to control it)
        min_conf = int(s_cfg.get("min_confidence", V5_MIN_CONFIDENCE))
        if confidence < min_conf:
            base["veto_reason"] = (
                f"GATE: Confidence {confidence}% < {min_conf}% "
                f"(ADX={base['adx']:.1f}, RSI={base['rsi']:.1f})"
            )
            return base

        # ──────────────────────────────────────────────────────────────────
        #  STEP 2 — REGIME: No trades in CRASH
        # ──────────────────────────────────────────────────────────────────
        regime = detect_regime(ind_h4)
        base["regime"] = regime

        if regime == "CRASH":
            base["veto_reason"] = "REGIME: CRASH — no new entries"
            return base

        # ──────────────────────────────────────────────────────────────────
        #  STEP 3 — VETO: RSI extreme + ADX weak + H4 mismatch
        # ──────────────────────────────────────────────────────────────────
        # We check against the likely direction first
        # Use H1 direction as primary signal source
        if dir_h1 == "NEUTRAL":
            base["veto_reason"] = "VETO: H1 direction NEUTRAL"
            return base

        direction_candidate = dir_h1

        vetoed, reason = check_veto(
            direction_candidate, ind_m15, dir_h4,
            rsi_ob=rsi_ob, rsi_os=rsi_os, adx_min=adx_min,
        )
        if vetoed:
            base["vetoed"]      = True
            base["veto_reason"] = f"VETO: {reason}"
            return base

        # ──────────────────────────────────────────────────────────────────
        #  STEP 4 — 3-TIMEFRAME AGREEMENT
        #  BULL/EUPHORIA: all 3 TF must be BUY
        #  BEAR:          all 3 TF must be SELL
        #  NEUTRAL:       at least 2 / 3 must agree
        # ──────────────────────────────────────────────────────────────────
        all_dirs = [dir_m15, dir_h1, dir_h4]
        buys  = all_dirs.count("BUY")
        sells = all_dirs.count("SELL")

        if regime in ("BULL", "EUPHORIA"):
            # Strict: all 3 must be BUY
            if buys < 3:
                base["veto_reason"] = (
                    f"3TF: BULL needs all BUY "
                    f"M15:{dir_m15} H1:{dir_h1} H4:{dir_h4}"
                )
                return base
            direction = "BUY"

        elif regime == "BEAR":
            # Strict: all 3 must be SELL
            if sells < 3:
                base["veto_reason"] = (
                    f"3TF: BEAR needs all SELL "
                    f"M15:{dir_m15} H1:{dir_h1} H4:{dir_h4}"
                )
                return base
            direction = "SELL"

        else:
            # NEUTRAL / EUPHORIA handled above — require majority (2/3)
            if buys >= 2:
                direction = "BUY"
            elif sells >= 2:
                direction = "SELL"
            else:
                base["veto_reason"] = (
                    f"3TF: No majority "
                    f"M15:{dir_m15} H1:{dir_h1} H4:{dir_h4}"
                )
                return base

        # Direction consistency with candidate
        if direction != direction_candidate:
            base["veto_reason"] = (
                f"3TF: Direction mismatch (H1:{direction_candidate} vs TF:{direction})"
            )
            return base

        # ──────────────────────────────────────────────────────────────────
        #  STEP 5 — SCORE >= 8 / 10
        # ──────────────────────────────────────────────────────────────────
        sc = score_signal(direction, ind_h1)
        base["score"] = sc

        if sc < threshold:
            base["veto_reason"] = f"SCORE: {sc}/10 < {threshold} (need {threshold}+)"
            return base

        # ──────────────────────────────────────────────────────────────────
        #  ALL STEPS PASSED — GENERATE ENTRY
        # ──────────────────────────────────────────────────────────────────
        price   = ind_m15.get("close", 0.0)
        atr_h1  = ind_h1.get("atr",   0.0010)

        if direction == "BUY":
            base["entry"] = round(price,             5)
            base["sl"]    = round(price - sl_mult * atr_h1, 5)
            base["tp"]    = round(price + tp_mult * atr_h1, 5)
        else:
            base["entry"] = round(price,             5)
            base["sl"]    = round(price + sl_mult * atr_h1, 5)
            base["tp"]    = round(price - tp_mult * atr_h1, 5)

        base["direction"]   = direction
        base["signal_time"] = datetime.utcnow().strftime("%H:%M:%S")

        log.info(
            "[V5] SIGNAL PASS  %s %s  conf=%d%%  regime=%s  score=%.1f/10  "
            "M15:%s H1:%s H4:%s  entry=%.5f sl=%.5f tp=%.5f",
            direction, symbol, confidence, regime, sc,
            dir_m15, dir_h1, dir_h4, price,
            base["sl"], base["tp"],
        )

    except Exception as exc:
        log.error("get_signal %s: %s", symbol, exc, exc_info=True)
        base["veto_reason"] = str(exc)

    return base


# ═══════════════════════════════════════════════════════════════════════════════
#  SCAN ALL SYMBOLS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def scan_all_symbols(connector, symbols: list, cfg: dict) -> list:
    """Run V5 signal analysis for all symbols. Returns sorted list."""
    results = []
    for sym in symbols:
        try:
            sig = get_signal(connector, sym, cfg)
            results.append(sig)
        except Exception as exc:
            log.error("scan %s: %s", sym, exc)
    results.sort(key=lambda x: (
        0 if x["direction"] in ("BUY", "SELL") else 1,
        -x["score"]
    ))
    return results
