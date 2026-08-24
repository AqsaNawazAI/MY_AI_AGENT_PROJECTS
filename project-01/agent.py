import os, json, time, base64, io, urllib.request, urllib.error, re
from pathlib import Path
import pyautogui
import pyperclip

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
CONFIG = DATA / "config.json"

DEFAULT_CONFIG = {
    "provider": "groq",
    "api_base": "https://api.groq.com/openai/v1",
    "model": "qwen/qwen3.6-27b",
    "api_key": "",
    "max_steps": 20,
    "dry_run": False,
    "confirm_external": True,
    "confirm_destructive": True,
    "reasoning_effort": "none",
}

if not CONFIG.exists():
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")


def config():
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        out = DEFAULT_CONFIG.copy()
        if isinstance(data, dict):
            out.update(data)
        out["provider"] = "groq"
        out["api_base"] = "https://api.groq.com/openai/v1"
        if not out.get("model") or out.get("model") in {
            "gpt-5.6", "computer-use-preview", "computer-use-preview-2025-03-11"
        }:
            out["model"] = "qwen/qwen3.6-27b"
        def _normalize_max_steps(value, default=20):
            # Settings can arrive as a number, numeric string, or (from some
            # older frontend builds) a one-item list. Never let malformed
            # settings crash the autonomous agent.
            if isinstance(value, (list, tuple)):
                value = value[0] if value else default
            if isinstance(value, dict):
                value = value.get("value", value.get("max_steps", default))
            try:
                value = int(float(str(value).strip()))
            except (TypeError, ValueError):
                value = default
            return max(1, min(value, 40))

        out["max_steps"] = _normalize_max_steps(out.get("max_steps", 20))
        out["reasoning_effort"] = "none"
        return out
    except Exception:
        return DEFAULT_CONFIG.copy()


SYSTEM = """You are ASTRA WORLD, a Windows desktop computer-use agent.
You control the user's real Windows desktop using the supplied screenshot.
Perform the user's task, not merely explain it.

Return ONLY valid JSON:
{"actions":[{"type":"click|double_click|right_click|type|keypress|scroll|move|drag|wait", ...}],
 "done":false,
 "message":"brief status"}

Coordinates refer to the supplied screenshot pixel coordinates.
Allowed:
click/double_click/right_click/move={x,y}
type={text}
keypress={keys}
scroll={x,y,scroll_y}
wait={seconds}
drag={path:[{x,y},...]}

Use small, verifiable actions. Do not invent screen elements.
If the user's goal is complete, return actions=[] and done=true.
If another observation/action is required, return done=false.
For consequential actions such as sending messages, purchases/payments, deleting data,
account/security changes, or trading, stop before the final consequential action and request confirmation.
"""


def screenshot_b64():
    # JPEG keeps visual requests much smaller than full-resolution PNG.
    im = pyautogui.screenshot()
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=75, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post_chat(payload, key, base, attempts=3):
    url = base.rstrip("/") + "/chat/completions"
    last_error = None

    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
                "Accept": "application/json",
                "User-Agent": "ASTRA-WORLD/1.0",
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except Exception:
                body = raw
            message = body.get("error", body) if isinstance(body, dict) else body
            # Do not retry authentication/permission failures.
            if e.code in (400, 401, 403):
                raise RuntimeError(
                    f"Groq API HTTP {e.code}: "
                    + json.dumps(message, ensure_ascii=False)[:1800]
                )
            last_error = RuntimeError(
                f"Groq API HTTP {e.code}: "
                + json.dumps(message, ensure_ascii=False)[:1800]
            )
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_error = e

        if attempt < attempts:
            time.sleep(attempt * 1.5)

    raise RuntimeError(f"Groq network request failed after {attempts} attempts: {last_error}")


def _parse_plan(raw):
    text = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(text, list):
        text = "".join(
            str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in text
        )
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip(),
                  flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {"actions": [], "done": True, "message": text or "No actionable plan returned."}


def _number(value, default=None):
    """Normalize coordinates/numbers returned by vision models.
    Accepts scalars, numeric strings, one-item lists/tuples, dict wrappers,
    and coordinate pairs when a single scalar is expected.
    """
    if isinstance(value, dict):
        for key in ("value", "x", "y", "coordinate", "coord"):
            if key in value:
                return _number(value[key], default)
        return default
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        # For a scalar field, use the first scalar value.
        return _number(value[0], default)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _point(action):
    """Extract x/y from all common model coordinate shapes."""
    x = action.get("x")
    y = action.get("y")
    if isinstance(x, (list, tuple)) and len(x) >= 2 and y is None:
        x, y = x[0], x[1]
    if isinstance(action.get("coordinate"), (list, tuple)):
        pair = action["coordinate"]
        if len(pair) >= 2:
            x, y = pair[0], pair[1]
    if isinstance(action.get("coordinates"), (list, tuple)):
        pair = action["coordinates"]
        if len(pair) >= 2:
            x, y = pair[0], pair[1]
    if isinstance(action.get("position"), (list, tuple)):
        pair = action["position"]
        if len(pair) >= 2:
            x, y = pair[0], pair[1]
    x, y = _number(x), _number(y)
    if x is None or y is None:
        raise ValueError(f"Invalid coordinates in action: {action!r}")
    return x, y


def _execute_one(action):
    if not isinstance(action, dict):
        return False
    action_type = str(action.get("type", action.get("action", ""))).lower().strip().replace("-", "_").replace(" ", "_")

    if action_type in ("click", "double_click", "right_click", "move"):
        x, y = _point(action)
        if action_type == "click":
            pyautogui.click(x, y)
        elif action_type == "double_click":
            pyautogui.doubleClick(x, y)
        elif action_type == "right_click":
            pyautogui.rightClick(x, y)
        else:
            pyautogui.moveTo(x, y, duration=0.15)
    elif action_type == "type":
        pyperclip.copy(str(action.get("text", "")))
        pyautogui.hotkey("ctrl", "v")
    elif action_type == "keypress":
        keys = action.get("keys") or action.get("key") or []
        keys = [keys] if isinstance(keys, str) else list(keys)
        mapped = {
            "ENTER": "enter", "RETURN": "enter", "ESC": "esc",
            "ESCAPE": "esc", "SPACE": "space", "TAB": "tab",
            "BACKSPACE": "backspace", "CTRL": "ctrl", "ALT": "alt",
            "SHIFT": "shift", "WIN": "win", "META": "win",
            "ARROWUP": "up", "ARROWDOWN": "down",
            "ARROWLEFT": "left", "ARROWRIGHT": "right",
            "HOME": "home", "END": "end", "DELETE": "delete",
        }
        keys = [mapped.get(str(k).upper(), str(k).lower()) for k in keys]
        if len(keys) > 1:
            pyautogui.hotkey(*keys)
        elif keys:
            pyautogui.press(keys[0])
    elif action_type == "scroll":
        x = _number(action.get("x"), pyautogui.position().x)
        y = _number(action.get("y"), pyautogui.position().y)
        pyautogui.moveTo(x, y)
        amount = _number(action.get("scroll_y", action.get("amount", 0)), 0)
        pyautogui.scroll(amount)
    elif action_type == "wait":
        time.sleep(max(0.1, min(float(action.get("seconds", 1)), 5)))
    elif action_type == "drag":
        path = action.get("path") or []
        if not path:
            return False
        x0, y0 = _point(path[0])
        pyautogui.moveTo(x0, y0)
        pyautogui.mouseDown()
        try:
            for point in path[1:]:
                px, py = _point(point)
                pyautogui.moveTo(px, py, duration=0.12)
        finally:
            pyautogui.mouseUp()
    else:
        return False

    return True


def run_task(task, confirmed=False):
    # IMPORTANT: use the key saved by ASTRA Settings first.
    # Environment variable is only a fallback for first-time/manual setups.
    settings = config()
    key = (settings.get("api_key") or os.getenv("GROQ_API_KEY") or "").strip()

    if not key:
        return {
            "ok": False,
            "needs_confirmation": False,
            "message": "Groq API key is not configured. Open SETTINGS and add your key.",
            "steps": 0,
        }

    model = settings.get("model") or "qwen/qwen3.6-27b"
    base = settings.get("api_base") or "https://api.groq.com/openai/v1"
    raw_max_steps = settings.get("max_steps", 20)
    if isinstance(raw_max_steps, (list, tuple)):
        raw_max_steps = raw_max_steps[0] if raw_max_steps else 20
    if isinstance(raw_max_steps, dict):
        raw_max_steps = raw_max_steps.get("value", raw_max_steps.get("max_steps", 20))
    try:
        max_steps = max(1, min(int(float(str(raw_max_steps).strip())), 40))
    except (TypeError, ValueError):
        max_steps = 20

    for step in range(1, max_steps + 1):
        try:
            shot = screenshot_b64()
            prompt = (
                SYSTEM
                + "\nUSER TASK:\n" + str(task)
                + "\nCURRENT STEP: " + str(step)
                + "\nUse the current screenshot to choose the next concrete desktop actions."
                + "\nDo not declare success until the visible screen supports completion."
            )

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a precise Windows GUI agent. Follow the JSON-only protocol.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64," + shot
                                },
                            },
                        ],
                    },
                ],
                "temperature": 0.1,
                "max_completion_tokens": 1200,
                "response_format": {"type": "json_object"},
            }

            plan = _parse_plan(_post_chat(payload, key, base))
            message = str(plan.get("message", "")).strip()
            actions = plan.get("actions") or []

            if plan.get("needs_confirmation") or (
                "confirm" in message.lower() and not confirmed
            ):
                return {
                    "ok": False,
                    "needs_confirmation": True,
                    "message": message or "Confirmation is required before this action.",
                    "steps": step,
                    "plan": actions,
                }

            if not actions:
                return {
                    "ok": bool(plan.get("done", False)),
                    "needs_confirmation": False,
                    "message": message or (
                        "Task completed." if plan.get("done", False)
                        else "ASTRA needs another action."
                    ),
                    "steps": step,
                    "plan": [],
                }

            for action in actions:
                if not _execute_one(action):
                    return {
                        "ok": False,
                        "needs_confirmation": False,
                        "message": "ASTRA received an unsupported local action: "
                        + str(action),
                        "steps": step,
                    }
                time.sleep(0.25)

            # Next loop iteration captures a fresh screenshot and verifies state.

        except Exception as exc:
            return {
                "ok": False,
                "needs_confirmation": False,
                "message": f"Groq agent failed: {type(exc).__name__}: {exc}",
                "steps": step,
            }

    return {
        "ok": False,
        "needs_confirmation": False,
        "message": f"ASTRA reached the {max_steps}-step visual planning limit.",
        "steps": max_steps,
    }
