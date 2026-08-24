#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forex Bot V5 Elite - Risk Manager
ATR-based position sizing with daily drawdown protection.
"""

import logging

log = logging.getLogger(__name__)

# Pip sizes per symbol
PIP_SIZES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
    "NZDUSD": 0.0001, "USDCHF": 0.0001, "USDCAD": 0.0001,
    "USDJPY": 0.01,   "EURJPY": 0.01,   "GBPJPY": 0.01,
    "XAUUSD": 0.01,   "XAGUSD": 0.001,
}

# Approximate pip values per 0.01 lot (micro lot) in USD
PIP_VALUES_PER_MICRO = {
    "EURUSD": 0.10, "GBPUSD": 0.10, "AUDUSD": 0.10,
    "NZDUSD": 0.10, "USDCHF": 0.10, "USDCAD": 0.10,
    "USDJPY": 0.10, "EURJPY": 0.10, "GBPJPY": 0.10,
    "XAUUSD": 1.00, "XAGUSD": 0.50,
}


def calculate_lot_size(balance: float, risk_pct: float,
                       entry: float, sl: float, symbol: str,
                       min_lot=0.01, max_lot=1.0) -> float:
    """
    Calculate lot size based on % risk of balance.
    risk_pct: e.g. 1.0 means 1%
    """
    try:
        risk_amount = balance * risk_pct / 100.0
        pip_size = PIP_SIZES.get(symbol, 0.0001)
        pip_value = PIP_VALUES_PER_MICRO.get(symbol, 0.10)

        if pip_size <= 0 or pip_value <= 0:
            return min_lot

        sl_distance = abs(entry - sl)
        if sl_distance < pip_size:
            return min_lot

        sl_pips = sl_distance / pip_size
        # risk_amount = lots/0.01 * pip_value * sl_pips
        lots = risk_amount / (pip_value / 0.01 * sl_pips)

        lots = round(lots, 2)
        lots = max(min_lot, min(lots, max_lot))
        log.debug("lot_size: balance=%.2f risk=%.1f%% sl_pips=%.1f -> lots=%.2f",
                  balance, risk_pct, sl_pips, lots)
        return lots
    except Exception as exc:
        log.error("calculate_lot_size: %s", exc)
        return min_lot


def check_max_drawdown(deals: list, balance: float,
                       max_dd_pct: float = 3.0) -> tuple:
    """
    Check if daily loss exceeds max_dd_pct of balance.
    Returns (ok: bool, current_dd_pct: float)
    """
    try:
        from datetime import datetime, timezone
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        daily_pnl = 0.0
        for d in deals:
            deal_time = getattr(d, "time", 0)
            if hasattr(deal_time, "timestamp"):
                ts = deal_time.timestamp()
            else:
                ts = float(deal_time)
            if ts >= today_start.timestamp():
                daily_pnl += getattr(d, "profit", 0.0)

        if balance <= 0:
            return True, 0.0

        dd_pct = abs(min(0.0, daily_pnl)) / balance * 100.0
        ok = dd_pct < max_dd_pct
        return ok, round(dd_pct, 2)
    except Exception as exc:
        log.error("check_max_drawdown: %s", exc)
        return True, 0.0


def symbol_already_open(positions, symbol: str) -> bool:
    """Check if a position is already open for this symbol."""
    for p in positions:
        sym = getattr(p, "symbol", p.get("symbol", "")) if isinstance(p, dict) else p.symbol
        if sym == symbol:
            return True
    return False
