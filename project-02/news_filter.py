#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
News Filter — ForexFactory Economic Calendar
Checks for high-impact news before taking trades
"""

import requests, logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# Currency pairs ke liye relevant currencies
PAIR_CURRENCIES = {
    "EURUSD": ["EUR","USD"], "GBPUSD": ["GBP","USD"],
    "USDJPY": ["USD","JPY"], "USDCHF": ["USD","CHF"],
    "AUDUSD": ["AUD","USD"], "NZDUSD": ["NZD","USD"],
    "USDCAD": ["USD","CAD"], "EURJPY": ["EUR","JPY"],
    "GBPJPY": ["GBP","JPY"], "EURGBP": ["EUR","GBP"],
    "XAUUSD": ["USD","XAU"], "XAGUSD": ["USD","XAG"],
}

# Cache — har 10 min mein ek baar fetch karo
_cache = {"data": None, "fetched_at": None}
CACHE_MINUTES = 10

def _fetch_calendar():
    """ForexFactory se weekly calendar fetch karo."""
    global _cache
    now = datetime.now(timezone.utc)

    # Cache check
    if _cache["data"] and _cache["fetched_at"]:
        age = (now - _cache["fetched_at"]).total_seconds() / 60
        if age < CACHE_MINUTES:
            return _cache["data"]

    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        if r.status_code == 200:
            _cache["data"]       = r.json()
            _cache["fetched_at"] = now
            log.info("News calendar fetched: %d events", len(_cache["data"]))
            return _cache["data"]
        else:
            log.warning("News calendar HTTP %s", r.status_code)
            return _cache["data"] or []
    except Exception as e:
        log.warning("News fetch failed: %s", e)
        return _cache["data"] or []


def _parse_time(time_str):
    """Time string parse karo UTC mein."""
    try:
        # Format: "2026-06-16T08:30:00-04:00"
        from datetime import datetime
        # Simple parse
        if "T" in time_str:
            # Remove timezone offset
            if "+" in time_str[10:]:
                base = time_str[:time_str.rfind("+")]
                offset_str = time_str[time_str.rfind("+"):]
                offset_h = int(offset_str[1:3])
                offset_m = int(offset_str[4:6]) if len(offset_str) > 4 else 0
                dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
                dt -= timedelta(hours=offset_h, minutes=offset_m)
                return dt
            elif time_str.endswith("Z"):
                dt = datetime.strptime(time_str[:-1], "%Y-%m-%dT%H:%M:%S")
                return dt.replace(tzinfo=timezone.utc)
            else:
                # Try with offset like "-04:00"
                for i in range(len(time_str)-5, 0, -1):
                    if time_str[i] in "+-":
                        base = time_str[:i]
                        offset = time_str[i:]
                        sign = 1 if offset[0] == "+" else -1
                        parts = offset[1:].split(":")
                        h = int(parts[0])
                        m = int(parts[1]) if len(parts) > 1 else 0
                        dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
                        dt = dt.replace(tzinfo=timezone.utc)
                        dt -= timedelta(hours=sign*h, minutes=sign*m)
                        return dt
    except Exception as e:
        log.debug("Time parse error: %s %s", time_str, e)
    return None


def check_news(symbol: str, minutes_ahead: int = 30) -> tuple:
    """
    Agle N minutes mein koi HIGH impact news hai?
    Returns: (has_news: bool, message: str)
    """
    currencies = PAIR_CURRENCIES.get(symbol, ["USD"])
    now        = datetime.now(timezone.utc)
    cutoff     = now + timedelta(minutes=minutes_ahead)

    events = _fetch_calendar()
    if not events:
        return False, "Calendar unavailable — allowing trade"

    for event in events:
        impact  = event.get("impact", "").lower()
        if impact != "high":
            continue

        country = event.get("country", "").upper()
        # Check if this news affects our pair
        relevant = any(
            c.upper() in country or country in c.upper()
            for c in currencies
        )
        if not relevant:
            continue

        time_str = event.get("date", "")
        event_dt = _parse_time(time_str)
        if not event_dt:
            continue

        # Is news within our window?
        if now <= event_dt <= cutoff:
            mins_away = int((event_dt - now).total_seconds() / 60)
            title = event.get("title", "Unknown Event")
            msg = f"⛔ HIGH NEWS in {mins_away}min: {title} ({country})"
            log.warning("News block: %s", msg)
            return True, msg

    return False, "✅ No high-impact news — clear to trade"


def get_upcoming_events(minutes_ahead: int = 120) -> list:
    """Dashboard ke liye agle 2 ghante ki news list."""
    now     = datetime.now(timezone.utc)
    cutoff  = now + timedelta(minutes=minutes_ahead)
    events  = _fetch_calendar()
    result  = []

    for event in events:
        impact = event.get("impact", "").lower()
        if impact not in ("high", "medium"):
            continue
        time_str = event.get("date", "")
        event_dt = _parse_time(time_str)
        if not event_dt:
            continue
        if now <= event_dt <= cutoff:
            mins_away = int((event_dt - now).total_seconds() / 60)
            # Pakistan time = UTC + 5
            pkt = event_dt + timedelta(hours=5)
            result.append({
                "title":     event.get("title", "?"),
                "country":   event.get("country", "?"),
                "impact":    impact,
                "pkt_time":  pkt.strftime("%I:%M %p"),
                "utc_time":  event_dt.strftime("%H:%M"),
                "mins_away": mins_away,
                "forecast":  event.get("forecast", ""),
                "previous":  event.get("previous", ""),
            })

    return sorted(result, key=lambda x: x["mins_away"])
