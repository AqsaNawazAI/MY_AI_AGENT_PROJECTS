#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Advisor — Claude API se trade confirmation
Har passing signal ke liye Claude se poochha jata hai
"""

import requests, logging, json
from datetime import datetime, timezone

log = logging.getLogger(__name__)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"   # Fast + cheap


def ask_claude(signal: dict, balance: float, api_key: str) -> tuple:
    """
    Claude se poochho: kya yeh trade leni chahiye?
    Returns: (should_trade: bool, reason: str, confidence: int)
    """
    if not api_key or api_key.strip() == "":
        return True, "No API key — AI check skipped", 70

    sym   = signal.get("symbol","?")
    dir_  = signal.get("direction","?")
    score = signal.get("score",0)
    conf  = signal.get("confidence",0)
    rsi   = signal.get("rsi",50)
    adx   = signal.get("adx",0)
    reg   = signal.get("regime","NEUTRAL")
    m15   = signal.get("m15","?")
    h1    = signal.get("h1","?")
    h4    = signal.get("h4","?")
    entry = signal.get("entry",0)
    sl    = signal.get("sl",0)
    tp    = signal.get("tp",0)
    sl_pips = abs(entry - sl) * (100 if "JPY" in sym else 10000)
    tp_pips = abs(tp - entry) * (100 if "JPY" in sym else 10000)
    rr    = tp_pips / sl_pips if sl_pips > 0 else 0

    prompt = f"""You are an expert forex trading advisor. Analyze this trade signal quickly.

SIGNAL:
Symbol: {sym}
Direction: {dir_}
V5 Score: {score}/10
Confidence: {conf}%
Market Regime: {reg}

INDICATORS:
RSI: {rsi:.1f} (30-70 healthy, >70 overbought, <30 oversold)
ADX: {adx:.1f} (>25 trending, <15 weak)
M15: {m15} | H1: {h1} | H4: {h4}

TRADE LEVELS:
Entry: {entry:.5f}
Stop Loss: {sl:.5f} ({sl_pips:.1f} pips)
Take Profit: {tp:.5f} ({tp_pips:.1f} pips)
Risk/Reward: {rr:.1f}:1

Account Balance: ${balance:.2f}

DECISION: Should this trade be taken?
Reply in EXACTLY this format:
DECISION: YES or NO
REASON: (one short sentence, max 15 words)
CONFIDENCE: (number 1-100)"""

    try:
        r = requests.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key":          api_key,
                "anthropic-version":  "2023-06-01",
                "content-type":       "application/json",
            },
            json={
                "model":      CLAUDE_MODEL,
                "max_tokens": 100,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=10
        )

        if r.status_code == 200:
            text = r.json()["content"][0]["text"].strip()
            log.info("AI response: %s", text.replace("\n"," "))

            # Parse response
            lines = text.split("\n")
            decision  = "YES"
            reason    = "AI confirmed"
            ai_conf   = 70

            for line in lines:
                if line.startswith("DECISION:"):
                    decision = "NO" if "NO" in line.upper() else "YES"
                elif line.startswith("REASON:"):
                    reason = line.replace("REASON:","").strip()
                elif line.startswith("CONFIDENCE:"):
                    try:
                        ai_conf = int(''.join(filter(str.isdigit, line)))
                    except:
                        pass

            should_trade = decision == "YES"
            return should_trade, reason, ai_conf

        elif r.status_code == 401:
            log.error("AI: Invalid API key!")
            return True, "Invalid API key — skipping AI", 50
        elif r.status_code == 429:
            log.warning("AI: Rate limit — allowing trade")
            return True, "AI rate limit — trade allowed", 60
        else:
            log.warning("AI HTTP %s", r.status_code)
            return True, f"AI error {r.status_code} — trade allowed", 50

    except requests.Timeout:
        log.warning("AI timeout — allowing trade")
        return True, "AI timeout — trade allowed", 60
    except Exception as e:
        log.error("AI error: %s", e)
        return True, f"AI unavailable — trade allowed", 50


def test_api_key(api_key: str) -> tuple:
    """API key test karo."""
    if not api_key:
        return False, "No API key provided"
    try:
        r = requests.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":    CLAUDE_MODEL,
                "max_tokens": 10,
                "messages": [{"role":"user","content":"Say OK"}]
            },
            timeout=8
        )
        if r.status_code == 200:
            return True, "✅ Claude API connected!"
        elif r.status_code == 401:
            return False, "❌ Invalid API key"
        else:
            return False, f"❌ Error {r.status_code}"
    except Exception as e:
        return False, f"❌ {str(e)[:50]}"
