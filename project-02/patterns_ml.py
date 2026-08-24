"""
patterns_ml.py — Book-based candlestick pattern detection + ML prediction
==========================================================================
- 31+ patterns encoded from trading books (vectorized pandas)
- ML target: NEXT CANDLE COLOR only (lookahead-safe — mid-price target
  was proven to inflate accuracy artificially, see forex_pattern_ml README)
- Chronological 80/20 split (no shuffle = no future leakage)
- Model cached per (symbol, timeframe), retrains every RETRAIN_MIN minutes
"""
import time, logging
import numpy as np
import pandas as pd

log = logging.getLogger("patterns_ml")

try:
    from xgboost import XGBClassifier
    _HAS_XGB = True
except Exception:
    _HAS_XGB = False
try:
    from sklearn.ensemble import GradientBoostingClassifier
    _HAS_SK = True
except Exception:
    _HAS_SK = False

RETRAIN_MIN = 30          # retrain model every 30 min per symbol/tf
_model_cache = {}         # (symbol, tf) -> dict(model, trained_at, acc, n, feats)


# ----------------------------------------------------------------------
# 1. PATTERN DETECTORS (vectorized, from the books)
# ----------------------------------------------------------------------
def _base(df):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body   = (c - o).abs()
    rng    = (h - l).replace(0, np.nan)
    upper  = h - np.maximum(o, c)
    lower  = np.minimum(o, c) - l
    bull   = c > o
    bear   = c < o
    avg_body = body.rolling(14, min_periods=5).mean()
    return o, h, l, c, body, rng, upper, lower, bull, bear, avg_body


def detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame of boolean pattern columns, same index as df."""
    o, h, l, c, body, rng, up, lo, bull, bear, ab = _base(df)
    o1, c1, h1, l1 = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    o2, c2 = o.shift(2), c.shift(2)
    body1, body2 = body.shift(1), body.shift(2)
    bull1, bear1 = bull.shift(1).fillna(False), bear.shift(1).fillna(False)
    bull2, bear2 = bull.shift(2).fillna(False), bear.shift(2).fillna(False)
    small = body < 0.3 * ab
    long_ = body > 1.2 * ab

    P = pd.DataFrame(index=df.index)

    # --- single candle -------------------------------------------------
    P["doji"]            = body <= 0.1 * rng
    P["dragonfly_doji"]  = P["doji"] & (lo > 2 * body.clip(lower=1e-12)) & (up < 0.1 * rng)
    P["gravestone_doji"] = P["doji"] & (up > 2 * body.clip(lower=1e-12)) & (lo < 0.1 * rng)
    P["hammer"]          = (lo >= 2 * body) & (up <= 0.3 * body.clip(lower=1e-12)) & (body > 0)
    P["inverted_hammer"] = (up >= 2 * body) & (lo <= 0.3 * body.clip(lower=1e-12)) & (body > 0)
    P["hanging_man"]     = P["hammer"] & (c.rolling(5).mean() > c.rolling(20).mean())
    P["shooting_star"]   = P["inverted_hammer"] & (c.rolling(5).mean() > c.rolling(20).mean())
    P["bull_marubozu"]   = bull & long_ & (up < 0.05 * rng) & (lo < 0.05 * rng)
    P["bear_marubozu"]   = bear & long_ & (up < 0.05 * rng) & (lo < 0.05 * rng)
    P["spinning_top"]    = small & (up > body) & (lo > body) & ~P["doji"]

    # --- two candle ----------------------------------------------------
    P["bull_engulfing"]  = bull & bear1 & (c > o1) & (o < c1) & (body > body1)
    P["bear_engulfing"]  = bear & bull1 & (c < o1) & (o > c1) & (body > body1)
    P["bull_harami"]     = bull & bear1 & (o > c1) & (c < o1) & (body < body1)
    P["bear_harami"]     = bear & bull1 & (o < c1) & (c > o1) & (body < body1)
    P["piercing"]        = bull & bear1 & (o < l1) & (c > (o1 + c1) / 2) & (c < o1)
    P["dark_cloud"]      = bear & bull1 & (o > h1) & (c < (o1 + c1) / 2) & (c > o1)
    P["tweezer_bottom"]  = ((l - l1).abs() <= 0.1 * rng) & bear1 & bull
    P["tweezer_top"]     = ((h - h1).abs() <= 0.1 * rng) & bull1 & bear
    P["bull_kicker"]     = bull & bear1 & (o > o1)
    P["bear_kicker"]     = bear & bull1 & (o < o1)

    # --- three candle --------------------------------------------------
    mid_small1 = body1 < 0.5 * body2
    P["morning_star"]    = bear2 & mid_small1 & bull & (c > (o2 + c2) / 2)
    P["evening_star"]    = bull2 & mid_small1 & bear & (c < (o2 + c2) / 2)
    P["three_white_soldiers"] = bull & bull1 & bull2 & (c > c1) & (c1 > c2) & (body > 0.5 * ab) & (body1 > 0.5 * ab)
    P["three_black_crows"]    = bear & bear1 & bear2 & (c < c1) & (c1 < c2) & (body > 0.5 * ab) & (body1 > 0.5 * ab)
    P["three_inside_up"]   = P["bull_harami"].shift(1).fillna(False) & bull & (c > h1)
    P["three_inside_down"] = P["bear_harami"].shift(1).fillna(False) & bear & (c < l1)
    P["three_outside_up"]  = P["bull_engulfing"].shift(1).fillna(False) & bull & (c > c1)
    P["three_outside_down"]= P["bear_engulfing"].shift(1).fillna(False) & bear & (c < c1)
    P["bull_abandoned_baby"] = P["doji"].shift(1).fillna(False) & bear2 & bull & (h1 < np.minimum(l, l.shift(2)))
    P["bear_abandoned_baby"] = P["doji"].shift(1).fillna(False) & bull2 & bear & (l1 > np.maximum(h, h.shift(2)))
    P["rising_three"]  = bull & bull.shift(4).fillna(False) & (c > h.shift(4)) & small.shift(1).fillna(False) & small.shift(2).fillna(False)
    P["falling_three"] = bear & bear.shift(4).fillna(False) & (c < l.shift(4)) & small.shift(1).fillna(False) & small.shift(2).fillna(False)

    return P.fillna(False)


# direction map for chart markers: +1 bullish, -1 bearish, 0 neutral
PATTERN_DIR = {
    "hammer": 1, "inverted_hammer": 1, "dragonfly_doji": 1, "bull_marubozu": 1,
    "bull_engulfing": 1, "bull_harami": 1, "piercing": 1, "tweezer_bottom": 1,
    "bull_kicker": 1, "morning_star": 1, "three_white_soldiers": 1,
    "three_inside_up": 1, "three_outside_up": 1, "bull_abandoned_baby": 1,
    "rising_three": 1,
    "hanging_man": -1, "shooting_star": -1, "gravestone_doji": -1, "bear_marubozu": -1,
    "bear_engulfing": -1, "bear_harami": -1, "dark_cloud": -1, "tweezer_top": -1,
    "bear_kicker": -1, "evening_star": -1, "three_black_crows": -1,
    "three_inside_down": -1, "three_outside_down": -1, "bear_abandoned_baby": -1,
    "falling_three": -1,
    "doji": 0, "spinning_top": 0,
}

PRETTY = {k: k.replace("_", " ").title().replace("Bull ", "Bull ").replace("Bear ", "Bear ")
          for k in PATTERN_DIR}


# ----------------------------------------------------------------------
# 2. INDICATORS / FEATURES
# ----------------------------------------------------------------------
def _rsi(c, n=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, min_periods=n).mean()
    ls = (-d.clip(upper=0)).ewm(alpha=1/n, min_periods=n).mean()
    return 100 - 100 / (1 + g / ls.replace(0, np.nan))

def _atr(df, n=14):
    tr = pd.concat([df.high - df.low,
                    (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, min_periods=n).mean()

def build_features(df: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    F = P.astype(int).copy()
    body = (df.close - df.open)
    rng = (df.high - df.low).replace(0, np.nan)
    F["body_ratio"] = (body / rng).fillna(0)
    F["rsi"]        = _rsi(df.close).fillna(50) / 100.0
    atr = _atr(df)
    F["atr_norm"]   = (atr / df.close).fillna(0)
    F["ret1"]       = df.close.pct_change().fillna(0)
    F["ret3"]       = df.close.pct_change(3).fillna(0)
    F["dist_sma20"] = (df.close / df.close.rolling(20).mean() - 1).fillna(0)
    return F


# ----------------------------------------------------------------------
# 3. ML TRAIN + PREDICT (lookahead-safe)
# ----------------------------------------------------------------------
def _make_model():
    if _HAS_XGB:
        return XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.08,
                             subsample=0.9, colsample_bytree=0.9,
                             eval_metric="logloss", verbosity=0)
    if _HAS_SK:
        return GradientBoostingClassifier(n_estimators=120, max_depth=3,
                                          learning_rate=0.08, subsample=0.9)
    return None


def train_model(df: pd.DataFrame, key: str):
    """Chronological split, target = next candle color. Returns cache entry."""
    P = detect_patterns(df)
    F = build_features(df, P)
    # TARGET: next candle bullish? (shift -1 → then DROP last row = no lookahead)
    y = (df.close.shift(-1) > df.open.shift(-1)).astype(int)
    F, y = F.iloc[:-1], y.iloc[:-1]
    valid = F.notna().all(axis=1)
    F, y = F[valid], y[valid]
    if len(F) < 120:
        return None
    split = int(len(F) * 0.8)
    Xtr, ytr, Xte, yte = F.iloc[:split], y.iloc[:split], F.iloc[split:], y.iloc[split:]
    model = _make_model()
    if model is None:
        return None
    try:
        model.fit(Xtr.values, ytr.values)
        acc = float((model.predict(Xte.values) == yte.values).mean()) if len(Xte) else 0.5
    except Exception as e:
        log.error("train fail %s: %s", key, e)
        return None
    entry = {"model": model, "trained_at": time.time(), "acc": round(acc * 100, 1),
             "n_train": len(Xtr), "n_test": len(Xte), "feats": list(F.columns),
             "engine": "XGBoost" if _HAS_XGB else "GradBoost"}
    _model_cache[key] = entry
    return entry


def get_model(df, symbol, tf):
    key = f"{symbol}_{tf}"
    e = _model_cache.get(key)
    if e and time.time() - e["trained_at"] < RETRAIN_MIN * 60:
        return e
    return train_model(df, key) or e


# ----------------------------------------------------------------------
# 3b. LIVE FILTER — single prediction for the trading decision path
# ----------------------------------------------------------------------
def predict_latest(candles: list, symbol: str, tf: str):
    """
    Returns (prob_bullish, info) using ONLY the most recently completed
    candle's features (index -2, since -1 may still be forming/incomplete
    depending on how the caller fetched candles — callers should pass the
    same candle list they used for the rest of the strategy so indices
    line up with what strategy_combo.py already treats as "latest").

    prob_bullish: float 0..1, P(next candle closes green), or None if the
    model isn't ready yet (not enough history / still training).
    info: dict with model accuracy/engine for logging, or None.

    This does NOT shift anything — it is intentionally the mirror image of
    train_model()'s lookahead-safe labeling: training drops the last row
    (because its label would need the future), while prediction uses the
    LAST available row on purpose, because that's the one whose "next
    candle" hasn't happened yet — which is exactly what we want to predict
    live.
    """
    if not candles or len(candles) < 60:
        return None, None
    try:
        df = pd.DataFrame(candles)
        entry = get_model(df, symbol, tf)
        if not entry:
            return None, None
        P = detect_patterns(df)
        F = build_features(df, P)
        row = F[entry["feats"]].iloc[[-2]].fillna(0).values  # last COMPLETED bar
        prob = float(entry["model"].predict_proba(row)[0, 1])
        info = {"engine": entry["engine"], "accuracy": entry["acc"],
                "n_train": entry["n_train"], "n_test": entry["n_test"]}
        return prob, info
    except Exception as e:
        log.error("predict_latest %s/%s: %s", symbol, tf, e)
        return None, None


# ----------------------------------------------------------------------
# 4. MAIN ENTRY — analyze candles for the API
# ----------------------------------------------------------------------
def analyze(candles: list, symbol: str = "?", tf: str = "?", marker_lookback: int = 120):
    """
    Input : list of OHLCV dicts (from mt5_connector.get_candles)
    Output: dict with pattern markers (name + ML prob written per candle)
            and model info block for the chart overlay.
    """
    if not candles or len(candles) < 60:
        return {"markers": [], "model": None, "latest": None,
                "error": "not enough candles"}

    df = pd.DataFrame(candles)
    entry = get_model(df, symbol, tf)
    P = detect_patterns(df)
    F = build_features(df, P)

    probs = None
    if entry:
        try:
            probs = entry["model"].predict_proba(F[entry["feats"]].fillna(0).values)[:, 1]
        except Exception as e:
            log.error("predict fail: %s", e)

    markers, latest = [], None
    start = max(0, len(df) - marker_lookback)
    for i in range(start, len(df)):
        hits = [pat for pat in P.columns if P[pat].iloc[i]]
        if not hits:
            continue
        # strongest = multi-candle patterns first (they appear later in dict)
        hits.sort(key=lambda x: abs(PATTERN_DIR.get(x, 0)), reverse=True)
        pat = hits[0]
        d = PATTERN_DIR.get(pat, 0)
        prob = float(probs[i]) if probs is not None and i < len(probs) else None
        # ML prob = P(next candle bullish). For bearish patterns show P(bear).
        show = prob if d >= 0 else (1 - prob) if prob is not None else None
        txt = PRETTY.get(pat, pat)
        if show is not None:
            txt += f" {show*100:.0f}%"
        if len(hits) > 1:
            txt += f" +{len(hits)-1}"
        m = {"time": int(df.time.iloc[i]), "pattern": pat, "name": PRETTY.get(pat, pat),
             "dir": d, "text": txt, "prob": round(show * 100, 1) if show is not None else None,
             "all": hits}
        markers.append(m)
        latest = m

    model_info = None
    if entry:
        model_info = {"engine": entry["engine"], "accuracy": entry["acc"],
                      "train_candles": entry["n_train"], "test_candles": entry["n_test"],
                      "target": "next candle color (lookahead-safe)",
                      "patterns_encoded": len(PATTERN_DIR),
                      "trained_ago_min": round((time.time() - entry["trained_at"]) / 60, 1)}
    return {"markers": markers, "model": model_info, "latest": latest, "error": None}
