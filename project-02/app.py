#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forex Bot V5 Elite — Flask API (clean, no duplicates)"""
try:
    from news_filter import get_upcoming_events, check_news
    from ai_advisor  import test_api_key as _test_key
    AI_NEWS_OK = True
except ImportError:
    AI_NEWS_OK = False

import json, time, logging, threading
from flask      import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from bot        import ForexBotV5
from mt5_connector import MT5Connector

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot_log.txt",encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)
connector  = MT5Connector()
bot        = ForexBotV5(connector)
activity   = []
bot_running = False
bot_thread  = None

def ts():
    import datetime; return datetime.datetime.utcnow().strftime("%H:%M:%S")

def add_log(msg, lv="INFO"):
    activity.append({"t":ts(),"msg":msg,"lv":lv})
    if len(activity)>60: activity.pop(0)

def load_cfg():
    try:    return json.load(open("config.json",encoding="utf-8"))
    except: return {}

def save_cfg(c): json.dump(c,open("config.json","w",encoding="utf-8"),indent=2)
def ok(**kw):    return jsonify({"ok":True,**kw})
def fail(m=""):  return jsonify({"ok":False,"msg":m}),400

def _mt5_call(fn, timeout=12, fallback=None):
    import threading as _th
    result=[fallback]; done=_th.Event()
    def _r():
        try: result[0]=fn()
        except: pass
        finally: done.set()
    _th.Thread(target=_r,daemon=True).start()
    if not done.wait(timeout): return fallback
    return result[0]


def _bot_loop():
    global bot_running
    cycle=0; error_streak=0

    while bot_running:
        try:
            is_conn = _mt5_call(connector.is_connected, timeout=5, fallback=False)
            if not is_conn:
                add_log("MT5 disconnected — reconnecting...", "WARN")
                try:
                    cfg_a=bot.cfg.get("account",{})
                    r=_mt5_call(lambda: connector.connect(
                        cfg_a.get("login",0), cfg_a.get("password",""), cfg_a.get("server","")),
                        timeout=10, fallback=(False,"timeout"))
                    if r and r[0]:
                        add_log("Reconnected OK", "INFO"); error_streak=0
                    else:
                        add_log("Reconnect failed — retry in 5s", "WARN"); error_streak+=1
                except Exception as re:
                    add_log("Reconnect error: {}".format(str(re)[:40]), "ERROR"); error_streak+=1
                waited=0
                while waited<5 and bot_running: import time; time.sleep(0.5); waited+=0.5
                continue

            cycle+=1; error_streak=0
            before_placed=bot._session_stats.get("trades_placed",0)
            before_pnl   =bot._session_stats.get("total_profit", 0.0)

            import threading as _th2
            _done=_th2.Event(); _err=[None]
            def _rc():
                try: bot.run_cycle()
                except Exception as ex: _err[0]=ex
                finally: _done.set()
            _th2.Thread(target=_rc, daemon=True).start()
            if not _done.wait(timeout=15):
                add_log("#{} TIMEOUT (internet?) — skipping cycle".format(cycle), "WARN")
                error_streak+=1; continue
            if _err[0]: raise _err[0]

            after_placed=bot._session_stats.get("trades_placed",0)
            after_pnl   =bot._session_stats.get("total_profit", 0.0)
            mode  = bot.cfg.get("strategy",{}).get("strategy_mode","V5")
            mtag  = "" if mode=="V5" else "[{}] ".format(mode)

            # Show any status message from bot (max trades, errors)
            status_msg = getattr(bot, '_status_msg', '')
            if status_msg:
                add_log("#{} ⚠️ {}".format(cycle, status_msg), "WARN")
                bot._status_msg = ""

            if after_placed > before_placed:
                pnl   =round(after_pnl-before_pnl,2)
                w     =bot._session_stats.get("wins",0)
                l     =bot._session_stats.get("losses",0)
                tag   ="WIN" if pnl>=0 else "LOSS"
                last_t=bot._trade_log[-1] if bot._trade_log else {}
                add_log("#{} {}{} {} {} Sc:{:.1f} {:+.2f} | W:{} L:{} Total:{:+.2f}".format(
                    cycle, mtag, tag, last_t.get("symbol","?"), last_t.get("direction","?"),
                    last_t.get("score",0), pnl, w, l, after_pnl), "TRADE")
            else:
                sigs=bot.get_last_signals()
                if sigs:
                    active=[s for s in sigs if s.get("direction") in ("BUY","SELL")]
                    best  =sorted(sigs, key=lambda x:-x.get("score",0))[0]
                    n     =len(sigs)
                    if active:
                        a=active[0]
                        add_log("#{} {}SIGNAL {} {} {:.1f}/10".format(
                            cycle, mtag, a.get("symbol","?"), a.get("direction","?"),
                            a.get("score",0)), "INFO")
                    elif mode == "V5":
                        g =sum(1 for s in sigs if "GATE"  in (s.get("veto_reason","") or ""))
                        v =sum(1 for s in sigs if "VETO"  in (s.get("veto_reason","") or ""))
                        sc=sum(1 for s in sigs if "SCORE" in (s.get("veto_reason","") or ""))
                        add_log("#{} {} syms | GATE:{} VETO:{} SCORE:{} | best={} {:.1f}/10".format(
                            cycle, n, g, v, sc, best.get("symbol","?"),
                            best.get("score",0)), "INFO")
                    else:
                        reason=(best.get("veto_reason","") or "no pattern found")[:42]
                        add_log("#{} {}{} syms scanned | best={} {:.1f}/10 | {}".format(
                            cycle, mtag, n, best.get("symbol","?"),
                            best.get("score",0), reason), "INFO")
                else:
                    add_log("#{} {}Scanning...".format(cycle, mtag), "INFO")

        except Exception as e:
            error_streak+=1
            add_log("#{} Error({}): {}".format(cycle, error_streak, str(e)[:50]), "ERROR")
            if error_streak>=5:
                add_log("Force reconnecting...", "WARN")
                try:
                    _mt5_call(connector.disconnect, timeout=3)
                    import time; time.sleep(2)
                    cfg_a=bot.cfg.get("account",{})
                    _mt5_call(lambda: connector.connect(
                        cfg_a.get("login",0),cfg_a.get("password",""),cfg_a.get("server","")),
                        timeout=10)
                    error_streak=0
                except: pass
            import time; time.sleep(1)

        interval=max(2,int(bot.cfg.get("scan_interval_seconds",2)))
        waited=0
        while waited<interval and bot_running:
            import time; time.sleep(0.4); waited+=0.4

    add_log("Bot stopped","INFO")




# ═══════════════════════════════════════════════════════════════════════════════
#  API ROUTES  (each defined EXACTLY ONCE)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(".","dashboard.html")

@app.route("/api/status")
def status():
    acct=connector.get_account_info() if connector.is_connected() else {}
    st=bot._session_stats; w=st.get("wins",0); l=st.get("losses",0); p=st.get("trades_placed",0)
    rb=acct.get("balance",0); spnl=round(st.get("total_profit",0),2)
    bal=round(rb+spnl,2) if bot._is_paper_mode() else rb
    return jsonify({"connected":connector.is_connected(),"running":bot_running,"time":ts(),
        "balance":bal,"real_balance":rb,"currency":acct.get("currency","USD"),
        "mode":acct.get("mode","PAPER"),"server":acct.get("server",""),
        "wins":w,"losses":l,"wr":round(w/p*100,1) if p else 0,
        "total_pnl":spnl,"trades":p,
        "ai_decision":getattr(bot,"_last_ai_dec",{"decision":"—","reason":"—","time":"—"}),
        "news_status":getattr(bot,"_last_news_blk",{"blocked":False,"msg":"—","time":"—"}),
        "strategy_mode": load_cfg().get("strategy",{}).get("strategy_mode","V5"),
        "paper_mode":    load_cfg().get("strategy",{}).get("paper_mode", True),
        "score_threshold": load_cfg().get("strategy",{}).get("score_threshold", 8.0),
        "risk_percent":  load_cfg().get("trading",{}).get("risk_percent", 1.0),
        "auto_close_min":load_cfg().get("strategy",{}).get("auto_close_minutes", 2),
        "news_filter":   load_cfg().get("strategy",{}).get("news_filter", True),
        "scan_interval": load_cfg().get("scan_interval_seconds", 2),
    })

@app.route("/api/connect",methods=["POST"])
def connect():
    d=request.json or {}; login=int(d.get("login",0)); pwd=d.get("password",""); srv=d.get("server","")
    if not login or not pwd: return fail("Login and password required")
    ok2,msg=connector.connect(login,pwd,srv)
    if ok2:
        cfg2=load_cfg(); cfg2["account"]={"login":login,"password":pwd,"server":srv}
        save_cfg(cfg2); bot.cfg=load_cfg()
        a=connector.get_account_info()
        add_log("Connected: Demo Account — ${:.2f}".format(a.get("balance",0)),"INFO")
        return ok(msg=msg)
    return fail(msg)

@app.route("/api/disconnect",methods=["POST"])
def disconnect():
    connector.disconnect(); add_log("Disconnected","INFO"); return ok(msg="Disconnected")

@app.route("/api/start",methods=["POST"])
def start():
    global bot_thread,bot_running
    if bot_running:              return fail("Bot already running")
    if not connector.is_connected(): return fail("Connect to MT5 first")
    d=request.json or {}
    if d:
        cfg2=load_cfg()
        for k,v in d.items():
            if isinstance(v,dict) and isinstance(cfg2.get(k),dict): cfg2[k].update(v)
            else: cfg2[k]=v
        save_cfg(cfg2); bot.update_settings(cfg2)
    bot_running=True
    bot_thread=threading.Thread(target=_bot_loop,daemon=True); bot_thread.start()
    active_threshold = load_cfg().get("strategy",{}).get("score_threshold", 8.0)
    add_log("Bot STARTED [build=fillmode-v3] — scan every {}s — score_threshold={}/10".format(
        load_cfg().get("scan_interval_seconds",2), active_threshold),"INFO")
    return ok(msg="Bot started")

@app.route("/api/stop",methods=["POST"])
def stop():
    global bot_running; bot_running=False
    add_log("Bot STOPPED by user","WARN"); return ok(msg="Bot stopped")

@app.route("/api/signals")
def get_signals():
    return jsonify({"signals":bot.get_last_signals(),"scanned_at":ts()})

@app.route("/api/history")
def get_history():
    return jsonify({"trades":list(reversed(bot._trade_log[-50:]))})

@app.route("/api/log")
def get_log():
    return jsonify(list(reversed(activity[-40:])))

@app.route("/api/settings",methods=["GET"])
def get_settings(): return jsonify(load_cfg())

@app.route("/api/settings",methods=["POST"])
def post_settings():
    data=request.json or {}; cfg2=load_cfg()
    for k,v in data.items():
        if isinstance(v,dict) and isinstance(cfg2.get(k),dict): cfg2[k].update(v)
        else: cfg2[k]=v
    save_cfg(cfg2); bot.update_settings(cfg2)
    add_log("Settings updated","INFO"); return ok(msg="Settings saved")

@app.route("/api/trades/active")
def active_trades():
    try:    return jsonify({"trades":bot.get_active_trades()})
    except: return jsonify({"trades":[]})

@app.route("/api/trades/close/<int:ticket>",methods=["POST"])
def close_trade(ticket):
    ok2,msg=bot.close_trade(ticket)
    add_log("Close #{}: {}".format(ticket,msg),"INFO")
    if ok2: return ok(msg=msg)
    return fail(msg)

@app.route("/api/trades/close_all",methods=["POST"])
def close_all():
    ok2,msg=bot.close_all_trades()
    add_log("Close ALL: {}".format(msg),"WARN")
    if ok2: return ok(msg=msg)
    return fail(msg)

@app.route("/api/news")
def get_news():
    if not AI_NEWS_OK: return jsonify({"events":[]})
    try:    return jsonify({"events":get_upcoming_events(120)})
    except: return jsonify({"events":[]})

@app.route("/api/test_ai",methods=["POST"])
def test_ai():
    if not AI_NEWS_OK: return jsonify({"ok":False,"msg":"Not available"})
    try:
        d=request.json or {}; key=d.get("api_key","").strip()
        ok2,msg=_test_key(key)
        if ok2:
            cfg2=load_cfg(); cfg2["claude_api_key"]=key
            save_cfg(cfg2); bot.cfg["claude_api_key"]=key
        return jsonify({"ok":ok2,"msg":msg})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)})

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__=="__main__":
    cfg=load_cfg(); acct=cfg.get("account",{})
    print("\n"+"="*50)
    print("  FOREX BOT V5 ELITE")
    print("  Dashboard: http://localhost:5000")
    print("  Account:   {}  {}".format(acct.get("login","—"),acct.get("server","—")))
    print("="*50+"\n")
    app.run(host="0.0.0.0",port=5000,debug=False,use_reloader=False)
