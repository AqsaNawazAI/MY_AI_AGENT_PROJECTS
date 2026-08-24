from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
try:
    from .agent import run_task, config
except ImportError:
    from agent import run_task, config
from datetime import datetime
import os, re, subprocess, webbrowser, urllib.parse, time, json, asyncio
import pyautogui, pyperclip, psutil

BASE = Path(__file__).resolve().parent.parent
FRONTEND = BASE / "frontend"
DATA = BASE / "data"
SCREENSHOTS = Path.home() / "Pictures" / "ASTRA_World_Screenshots"
SCREENSHOTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ASTRA WORLD Groq Computer Agent")
# Prevent stale frontend assets and return JSON instead of a browser-level 500 for command errors.
@app.middleware("http")
async def astra_headers(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/app.js", "/style.css"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

class Req(BaseModel):
    command: str
    confirmed: bool = False

class Res(BaseModel):
    ok: bool
    message: str
    action: str = "none"
    needs_confirmation: bool = False
    plan: list = Field(default_factory=list)
    details: dict = Field(default_factory=dict)

SITES = {
    "gmail": "https://mail.google.com/",
    "google": "https://www.google.com/",
    "chatgpt": "https://chatgpt.com/",
    "whatsapp": "https://web.whatsapp.com/",
    "youtube": "https://www.youtube.com/",
    "drive": "https://drive.google.com/",
    "calendar": "https://calendar.google.com/",
    "github": "https://github.com/",
    "exness": "https://www.exness.com/",
}

APPS = {
    "chrome": ["chrome", "chrome.exe"],
    "google chrome": ["chrome", "chrome.exe"],
    "edge": ["msedge", "msedge.exe"],
    "microsoft edge": ["msedge", "msedge.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "vscode": ["code", "Code.exe"],
    "visual studio code": ["code", "Code.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
}

def clean_name(s):
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip() or "file"

def paste(text):
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")

def open_app(name):
    try:
        subprocess.Popen(APPS[name], shell=False)
        return True
    except Exception:
        try:
            subprocess.Popen(APPS[name][0], shell=True)
            return True
        except Exception:
            return False

def open_site(name):
    webbrowser.open(SITES[name])
    return True

def create_text_file(name, body=""):
    name = clean_name(name)
    if not Path(name).suffix:
        name += ".txt"
    path = Path.home() / "Documents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body or f"Created by ASTRA WORLD on {datetime.now():%Y-%m-%d %H:%M}", encoding="utf-8")
    return path

def create_today_list(items):
    path = Path.home() / "Documents" / "ASTRA_Today_List.txt"
    lines = [
        "ASTRA WORLD — TODAY",
        f"Date: {datetime.now():%Y-%m-%d}",
        "",
    ]
    lines += [f"{i}. [ ] {x}" for i, x in enumerate(items, 1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

def take_screenshot():
    path = SCREENSHOTS / f"astra_{datetime.now():%Y%m%d_%H%M%S}.png"
    pyautogui.screenshot().save(path)
    return path

def split_items(text):
    return [x.strip() for x in re.split(r"\s*(?:,|;| and )\s*", text) if x.strip()]

def parse_command(command):
    c = command.strip()
    l = c.lower().strip(" .!?")

    if not c:
        return {"action":"none","data":None,"message":"Please tell me what you want me to do.","confirm":False}


    if "what time" in l or l in {"time","tell me the time"}:
        return {"action":"chat","data":None,"message":f"The time is {datetime.now():%I:%M %p}.","confirm":False}

    # HARD ROUTER: simple greetings must NEVER enter the Groq vision agent.
    # This is intentionally before every other route.
    if l in {"hi","hello","hey","hy","hii","helo","salam","assalam o alaikum"}:
        return {"action":"chat","data":None,"message":"Hello! I am ASTRA. How can I help you?","confirm":False}

    # Common multi-step commands handled deterministically (no vision/API call).
    m = re.match(r"^open\s+(?:google(?:\s+and)?\s+)?(?:search\s+for|and\s+search\s+for)\s+(.+)$", c, re.I)
    if m:
        q=m.group(1).strip()
        return {"action":"search","data":q,"message":f"Searching Google for {q}.","confirm":False}
    m = re.match(r"^open\s+google\s+and\s+search\s+(?:for\s+)?(.+)$", c, re.I)
    if m:
        q=m.group(1).strip()
        return {"action":"search","data":q,"message":f"Searching Google for {q}.","confirm":False}
    m = re.match(r"^open\s+(?:youtube)(?:\s+and)?\s+(?:search\s+for|search)\s+(.+)$", c, re.I)
    if m:
        q=m.group(1).strip()
        return {"action":"youtube_search","data":q,"message":f"Opening YouTube results for {q}.","confirm":False}
    m = re.match(r"^open\s+notepad\s+and\s+(?:type|write)\s*[:\-]?\s*(.+)$", c, re.I)
    if m:
        return {"action":"app_type","data":m.group(1).strip(),"message":"Opening Notepad and typing the requested text.","confirm":False}

    # Natural website commands
    for n in sorted(SITES, key=len, reverse=True):
        aliases = [
            f"open {n}", f"open the {n}", f"launch {n}", f"start {n}",
            f"go to {n}", f"open my {n}", f"take me to {n}"
        ]
        if l in aliases:
            return {"action":"site","data":n,"message":f"Opening {n}.","confirm":False}

    if l in {"open browser","open the browser","launch browser","start browser","open web browser"}:
        return {"action":"app","data":"chrome","message":"Opening your browser.","confirm":False}

    # Natural app commands
    for n in sorted(APPS, key=len, reverse=True):
        if l in {f"open {n}", f"open the {n}", f"launch {n}", f"start {n}"}:
            return {"action":"app","data":n,"message":f"Opening {n}.","confirm":False}

    # YouTube music/search
    m = re.match(r"^(?:play|find|search)\s+(.+?)\s+(?:song|on youtube|on the youtube|youtube)$", c, re.I)
    if m:
        q=m.group(1).strip()
        return {"action":"youtube_search","data":q,"message":f"Opening YouTube results for {q}.","confirm":False}
    m = re.match(r"^(?:play|find)\s+(.+?)\s+(?:on youtube|on the youtube)$", c, re.I)
    if m:
        q=m.group(1).strip()
        return {"action":"youtube_search","data":q,"message":f"Opening YouTube results for {q}.","confirm":False}

    # Generic website names: e.g. "open exness website"
    m = re.match(r"^(?:open|launch|start|go to)\s+(.+?)(?:\s+website|\s+site)?$", c, re.I)
    if m:
        name=m.group(1).strip().lower()
        if name in SITES:
            return {"action":"site","data":name,"message":f"Opening {name}.","confirm":False}

    # Search
    m = re.match(r"^(?:search|google|search google)\s+(?:for\s+)?(.+)$", c, re.I)
    if m:
        q = m.group(1).strip()
        return {"action":"search","data":q,"message":f"Searching Google for {q}.","confirm":False}

    # File creation
    m = re.match(r"^(?:create|make)\s+(?:a\s+)?(?:text\s+)?file\s+(?:called|named)\s+(.+?)(?:\s+with\s+(.+))?$", c, re.I)
    if m:
        return {"action":"file","data":(m.group(1).strip(), (m.group(2) or "").strip()),"message":"Creating your file.","confirm":False}

    # Generic "create a file" with optional content
    m = re.match(r"^(?:create|make)\s+(?:a\s+)?file(?:\s+called|\s+named)?\s*(.*)$", c, re.I)
    if m and m.group(1).strip():
        rest = m.group(1).strip()
        parts = re.split(r"\s+(?:with|containing)\s+", rest, maxsplit=1, flags=re.I)
        return {"action":"file","data":(parts[0], parts[1] if len(parts)>1 else ""),"message":"Creating your file.","confirm":False}

    # Today's list
    m = re.match(r"^(?:create|make|prepare)\s+(?:my\s+)?(?:today'?s|today)\s+(?:to[\-\s]?do\s+)?list(?:\s*[:\-]?\s*(.*))?$", c, re.I)
    if m:
        raw = (m.group(1) or "").strip()
        items = split_items(raw) if raw else ["Review today's priorities"]
        return {"action":"todo","data":items,"message":"Creating today's list.","confirm":False}

    # Notes
    m = re.match(r"^(?:write|save|make)\s+(?:a\s+)?note\s+(?:called|named)\s+(.+?)(?:\s*[:\-]\s*(.+))?$", c, re.I)
    if m:
        return {"action":"file","data":(m.group(1).strip(), (m.group(2) or "").strip()),"message":"Creating the note.","confirm":False}

    # ChatGPT prompt workflow
    m = re.match(r"^(?:ask|tell|use|have)\s+chatgpt\s+(?:to\s+)?(.+)$", c, re.I)
    if m:
        return {"action":"chatgpt","data":m.group(1).strip(),"message":"I can open ChatGPT and type that prompt. Review it before sending.","confirm":True}

    m = re.match(r"^(?:open|go to)\s+chatgpt\s+(?:and\s+)?(?:write|type)\s+(.+)$", c, re.I)
    if m:
        return {"action":"chatgpt","data":m.group(1).strip(),"message":"I can open ChatGPT and type that prompt.","confirm":True}

    # WhatsApp
    m = re.match(
        r"^(?:whatsapp|message|send)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(.+?)\s+(?:saying|that says|:)\s+(.+)$",
        c, re.I
    )
    if m:
        return {
            "action":"whatsapp",
            "data":(m.group(1).strip(),m.group(2).strip()),
            "message":f"I can prepare a WhatsApp message to {m.group(1).strip()}. Review it before sending.",
            "confirm":True
        }

    # Computer controls
    if l in {"take a screenshot","screenshot","take screenshot","capture screen"}:
        return {"action":"screenshot","data":None,"message":"Taking a screenshot.","confirm":False}

    for phrase, folder in [
        ("downloads","Downloads"),("documents","Documents"),("desktop","Desktop")
    ]:
        if l in {f"open {phrase}",f"open my {phrase}"}:
            return {"action":"path","data":str(Path.home()/folder),"message":f"Opening {phrase}.","confirm":False}

    m = re.match(r"^(?:type|write)\s+(.+)$", c, re.I)
    if m:
        return {"action":"type","data":m.group(1),"message":"Typing into the active window.","confirm":False}

    if l in {"lock my pc","lock computer","lock pc"}:
        return {"action":"lock","data":None,"message":"Locking the PC requires confirmation.","confirm":True}
    if l in {"restart my pc","restart computer","restart pc"}:
        return {"action":"restart","data":None,"message":"Restarting the PC requires confirmation.","confirm":True}
    if l in {"shut down my pc","shutdown my pc","shutdown computer","shutdown pc"}:
        return {"action":"shutdown","data":None,"message":"Shutting down the PC requires confirmation.","confirm":True}

    return {
        "action":"unknown","data":None,
        "message":"I will use the autonomous computer agent for this task.",
        "confirm":False
    }

async def execute_browser_runtime(action, data):
    """Use Chrome/Chromium remote debugging when available.
    This is optional; normal webbrowser behavior remains the fallback.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            pages = []
            for context in browser.contexts:
                pages.extend(context.pages)
            page = pages[-1] if pages else await browser.contexts[0].new_page()

            if action == "site":
                await page.goto(SITES[data], wait_until="domcontentloaded", timeout=30000)
                return True
            if action == "site_url":
                await page.goto(data, wait_until="domcontentloaded", timeout=30000)
                return True
            if action == "search":
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(data)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return True
            if action == "chatgpt":
                await page.goto(SITES["chatgpt"], wait_until="domcontentloaded", timeout=30000)
                await page.keyboard.insert_text(data)
                return True
            if action == "whatsapp":
                person, msg = data
                digits = re.sub(r"\D","",person)
                if len(digits) >= 10:
                    url = "https://web.whatsapp.com/send?phone="+digits+"&text="+urllib.parse.quote(msg)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                else:
                    await page.goto(SITES["whatsapp"], wait_until="domcontentloaded", timeout=30000)
                    await page.keyboard.insert_text(person)
                return True
    except Exception:
        return False
    return False


class AgentReq(BaseModel):
    task: str
    confirmed: bool = False

class ApiTestReq(BaseModel):
    api_key: str = ""
    api_base: str = "https://api.groq.com/openai/v1"
    model: str = "qwen/qwen3.6-27b"

class SettingsReq(BaseModel):
    provider: str = "groq"
    api_base: str = "https://api.groq.com/openai/v1"
    model: str = "qwen/qwen3.6-27b"
    api_key: str = ""
    max_steps: int = 20

@app.post("/api/groq-test")
def groq_test(req: ApiTestReq):
    """Validate the saved/entered Groq key, model permission, and actual chat path.
    Returns Groq's response body on errors instead of hiding it behind urllib's generic 403.
    """
    key=(req.api_key or config().get('api_key') or os.getenv("GROQ_API_KEY") or "").strip()
    if not key: return {"ok":False,"stage":"authentication","message":"Groq API key is missing. Enter it in Settings and Save Settings first."}
    import urllib.request, urllib.error
    base=(req.api_base or config().get('api_base') or 'https://api.groq.com/openai/v1').rstrip('/')
    model=(req.model or config().get('model') or 'qwen/qwen3.6-27b').strip()
    headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":"ASTRA-WORLD/1.0"}
    def call(method,url,payload=None,timeout=30):
        data=json.dumps(payload).encode() if payload is not None else None
        rq=urllib.request.Request(url,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(rq,timeout=timeout) as resp:
                raw=resp.read().decode(errors='replace')
                try: body=json.loads(raw)
                except Exception: body=raw
                return resp.status,body,dict(resp.headers)
        except urllib.error.HTTPError as e:
            raw=e.read().decode(errors='replace')
            try: body=json.loads(raw)
            except Exception: body=raw
            return e.code,body,dict(e.headers or {})
    # 1) Authentication + model availability
    status,models,resp_headers=call('GET',base+'/models')
    if status != 200:
        err=models.get('error',models) if isinstance(models,dict) else models
        return {"ok":False,"stage":"models","status":status,"message":f"Groq /models returned HTTP {status}: {json.dumps(err,ensure_ascii=False)[:1800]}","headers":{k:v for k,v in resp_headers.items() if k.lower().startswith('x-ratelimit') or k.lower()=='retry-after'}}
    ids={str(x.get('id')) for x in models.get('data',[]) if isinstance(x,dict)} if isinstance(models,dict) else set()
    if model not in ids:
        return {"ok":False,"stage":"model","status":200,"message":f"API key is valid, but model '{model}' was not returned by /models for this key/project.","available_sample":sorted(ids)[:30]}
    # 2) Actual chat-completions path
    payload={"model":model,"messages":[{"role":"user","content":"Reply with exactly: ASTRA GROQ OK"}],"temperature":0,"max_completion_tokens":16,"reasoning_effort":"none"}
    status,body,resp_headers=call('POST',base+'/chat/completions',payload)
    if status != 200:
        err=body.get('error',body) if isinstance(body,dict) else body
        return {"ok":False,"stage":"chat_completions","status":status,"message":f"Groq chat/completions returned HTTP {status}: {json.dumps(err,ensure_ascii=False)[:1800]}","headers":{k:v for k,v in resp_headers.items() if k.lower().startswith('x-ratelimit') or k.lower()=='retry-after'}}
    try:
        content=body.get('choices',[{}])[0].get('message',{}).get('content','')
    except Exception: content=''
    return {"ok":True,"stage":"chat_completions","status":200,"message":"Groq API connection successful.","model":body.get('model',model),"reply":str(content)[:200]}

@app.get("/api/settings")
def get_settings():
    x=config().copy(); x['api_key']='' if x.get('api_key') else ''
    return x

@app.post("/api/settings")
def save_settings(s: SettingsReq):
    p=DATA/"config.json"
    x=config()
    incoming=s.model_dump()
    if not (incoming.get('api_key') or '').strip():
        incoming['api_key']=x.get('api_key','')
    x.update(incoming)
    x['provider']='groq'
    x['api_base']='https://api.groq.com/openai/v1'
    x['model']='qwen/qwen3.6-27b'
    p.write_text(json.dumps(x,indent=2),encoding="utf-8")
    return {"ok":True,"message":"ASTRA settings saved locally."}

@app.post("/api/agent")
def agent(req: AgentReq):
    try:
        return run_task(req.task, req.confirmed)
    except Exception as e:
        return {"ok":False,"needs_confirmation":False,"message":f"Agent error: {type(e).__name__}: {e}","steps":0}

@app.get("/health")
def health(): return {"ok":True,"service":"ASTRA WORLD","backend":"connected"}

@app.get("/")
def home():
    index = FRONTEND / "index.html"
    if not index.exists():
        return {"ok":False,"error":"Dashboard file missing","frontend":str(index)}
    return FileResponse(index)

@app.get("/style.css")
def css(): return FileResponse(FRONTEND/"style.css", media_type="text/css")

@app.get("/app.js")
def js(): return FileResponse(FRONTEND/"app.js", media_type="application/javascript")

@app.get("/api/version")
async def api_version():
    return {"ok": True, "version": "ASTRA WORLD v29 SMART ROUTER", "provider": "groq"}

@app.get("/api/status")
def status():
    return {
        "system":"ONLINE","astra":"ACTIVE","backend":"CONNECTED",
        "cpu":round(psutil.cpu_percent(.05)),
        "memory":round(psutil.virtual_memory().percent),
        "browser_runtime": False
    }

@app.get("/api/browser-runtime")
async def browser_runtime():
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            pages = sum(len(c.pages) for c in browser.contexts)
            return {"connected":True,"pages":pages}
    except Exception as e:
        return {"connected":False,"pages":0,"error":str(e)}

@app.post("/api/command", response_model=Res)
async def command(req: Req):
    parsed = parse_command(req.command)
    action, data = parsed["action"], parsed["data"]
    msg, needs = parsed["message"], parsed["confirm"]

    # Unknown natural-language commands go to the real OpenAI computer-use loop.
    if action == "unknown":
        try:
            result = run_task(req.command, req.confirmed)
            return Res(
                ok=bool(result.get("ok")),
                message=result.get("message") or "ASTRA finished the task.",
                action="computer_use",
                needs_confirmation=bool(result.get("needs_confirmation")),
                plan=result.get("plan") or [],
                details={"steps": result.get("steps", 0)}
            )
        except Exception as e:
            return Res(ok=False, message=f"Computer agent error: {type(e).__name__}: {e}", action="computer_use")

    if needs and not req.confirmed:
        return Res(ok=False, message=msg, action=action, needs_confirmation=True, plan=[action], details={"data":data})

    try:
        if action in {"chat","none"}:
            return Res(ok=(action=="chat"), message=msg, action=action)

        if action == "site":
            used_runtime = await execute_browser_runtime("site",data)
            if not used_runtime: open_site(data)
            return Res(ok=True, message=msg, action=action, needs_confirmation=False, plan=["Open website"])

        if action == "app":
            ok = open_app(data)
            return Res(ok=ok, message=msg if ok else f"I couldn't open {data}.", action=action)

        if action == "app_type":
            ok = open_app("notepad")
            if not ok:
                return Res(ok=False, message="I couldn't open Notepad.", action=action)
            time.sleep(0.8)
            paste(data)
            return Res(ok=True, message="Notepad opened and the text was typed.", action=action)

        if action == "youtube_search":
            url="https://www.youtube.com/results?search_query="+urllib.parse.quote_plus(data)
            used_runtime = await execute_browser_runtime("site_url",url)
            if not used_runtime: webbrowser.open(url)
            return Res(ok=True, message=msg, action=action)

        if action == "search":
            used_runtime = await execute_browser_runtime("search",data)
            if not used_runtime:
                webbrowser.open("https://www.google.com/search?q="+urllib.parse.quote_plus(data))
            return Res(ok=True, message=msg, action=action)

        if action == "path":
            os.startfile(data)
            return Res(ok=True, message=msg, action=action)

        if action == "file":
            name, body = data
            path = create_text_file(name,body)
            os.startfile(path)
            return Res(ok=True, message=f"Created {path} and opened it.", action=action)

        if action == "todo":
            path = create_today_list(data)
            os.startfile(path)
            return Res(ok=True, message=f"Today's list was created at {path}.", action=action)

        if action == "screenshot":
            path = take_screenshot()
            return Res(ok=True, message=f"Screenshot saved to {path}.", action=action)

        if action == "type":
            paste(data)
            return Res(ok=True, message="Done. I typed it into the active window.", action=action)

        if action == "chatgpt":
            used_runtime = await execute_browser_runtime("chatgpt",data)
            if not used_runtime:
                open_site("chatgpt")
                time.sleep(3)
                paste(data)
            return Res(ok=True, message="ChatGPT is open and the prompt is typed. Review it and press Send.", action=action)

        if action == "whatsapp":
            person,msg_text = data
            used_runtime = await execute_browser_runtime("whatsapp",(person,msg_text))
            if not used_runtime:
                digits = re.sub(r"\D","",person)
                if len(digits) >= 10:
                    webbrowser.open("https://web.whatsapp.com/send?phone="+digits+"&text="+urllib.parse.quote(msg_text))
                else:
                    open_site("whatsapp")
                    time.sleep(3)
                    paste(person)
            return Res(ok=True, message=f"WhatsApp is prepared for {person}. Review the correct contact and message, then send.", action=action)

        if action == "lock":
            subprocess.run(["rundll32.exe","user32.dll,LockWorkStation"])
            return Res(ok=True, message="PC locked.", action=action)

        if action == "restart":
            subprocess.run(["shutdown","/r","/t","5"])
            return Res(ok=True, message="PC will restart in 5 seconds.", action=action)

        if action == "shutdown":
            subprocess.run(["shutdown","/s","/t","5"])
            return Res(ok=True, message="PC will shut down in 5 seconds.", action=action)

        return Res(ok=False, message=msg, action=action)

    except Exception as e:
        return Res(ok=False, message=f"Action failed: {e}", action=action if "action" in locals() else "none")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=8765)
