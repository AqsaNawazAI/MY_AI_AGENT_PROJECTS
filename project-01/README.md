# ASTRA WORLD — COMPLETE LOCAL COMPUTER AGENT

## What this build contains

ASTRA is now structured as a real local computer-agent foundation rather than only a dashboard demo.

### Voice / natural commands
Examples:
- "Open my Gmail"
- "Open WhatsApp"
- "Open ChatGPT"
- "Open the browser"
- "Search Google for free AI agent projects"
- "Create a file named project notes"
- "Create a file named meeting notes with today's tasks"
- "Make today's list: finish assignment, email mam, review project"
- "Ask ChatGPT to write a professional project introduction"
- "WhatsApp message to Ali saying hello"
- "Take a screenshot"
- "Open Downloads"
- "Type hello everyone"

### Real local actions
- Windows applications
- Websites
- Google search
- Documents/files
- Today's task list
- Screenshots
- Keyboard typing
- Browser runtime via Chrome DevTools Protocol
- ChatGPT prompt preparation
- WhatsApp message preparation
- Lock/restart/shutdown with confirmation

## Browser Runtime

Run `start_browser_runtime.bat`.

This launches a dedicated Chrome profile with remote debugging on:
http://127.0.0.1:9222

Log in to Gmail, WhatsApp Web and ChatGPT in that browser once. ASTRA can then use the browser runtime for navigation and typing.

## Why this is safer and more reliable

ASTRA does not blindly execute arbitrary shell commands from speech. Actions are routed through explicit capabilities. External messages and destructive system actions require confirmation.

## Installation

1. Windows 10/11.
2. Python 3.10+ installed and available as `python`.
3. Extract this ZIP.
4. Run `start_astra.bat`.
5. Allow microphone permission in the browser.
6. For browser automation, also run `start_browser_runtime.bat`.
7. Log into the required websites in the ASTRA browser profile.

## Important limitation

No desktop agent can honestly guarantee "every possible laptop task" from only a fixed command parser. For arbitrary GUI tasks, the next layer is a visual computer-use model that can inspect screenshots, identify UI controls, click/type/scroll, and verify the result. This package provides the local execution, browser runtime, voice interface, task-oriented commands, confirmations, and extensible agent architecture needed for that layer.

Do not expose port 8765 or 9222 to the public internet.


## Groq Vision / Computer Agent

This build uses the Groq **Responses API** for autonomous screen reasoning. Groq's current API accepts image inputs and supports computer-use tooling in its Responses platform. citeturn0search0turn0search2

Setup:
1. Install Python 3.10+.
2. Run `start_astra_openai.bat`.
3. Open **SETTINGS** in ASTRA.
4. Enter your Groq API key.
5. Keep the API base as `https://api.api.groq.com/openai/v1`.
6. Choose a current vision-capable model available to your API account (the default is `qwen/qwen3.6-27b`).
7. Enable **AUTONOMOUS SCREEN AGENT**.

ASTRA captures the current screen, sends the screenshot plus the task to Groq, receives a structured next-action plan, executes safe local mouse/keyboard/browser actions, then repeats for verification.

### API key security
The key is saved locally in `data/config.json`. Do not upload that file or expose ASTRA's local ports publicly. API usage is billed according to your Groq account and model usage.

### Safety boundary
ASTRA does not silently send messages, delete data, purchase/pay, alter account/security settings, or perform destructive actions. Those actions require confirmation.


### Groq API test
Use **SETTINGS → TEST GROQ** before running autonomous mode. The API key may be stored locally or supplied through the `GROQ_API_KEY` environment variable.

## Dependency installation

The main ASTRA launcher installs only the core packages it needs. **Playwright is no longer downloaded during normal startup**, so a slow Playwright download cannot prevent `psutil` and the backend from being installed.

- `start_astra_openai.bat` = core ASTRA + Groq agent
- `install_browser_runtime.bat` = optional Playwright + Chromium browser automation
- `start_browser_runtime.bat` = launches the CDP browser after the optional runtime is installed

If a package download times out, simply rerun the relevant installer; pip is configured with longer timeouts and retries.


### Troubleshooting v10
Keep the black `ASTRA BACKEND` console window open. If it closes, the backend stopped. Visit `http://127.0.0.1:8765/health`; it should show `ok: true`.
The command parser includes YouTube song search and generic sites such as Exness. Browser Runtime is optional; normal web opening uses the Windows default browser.

### v12 startup fix
Use `start_astra_openai.bat` from this v12 folder. Do not run the older v8/v9 folders. The dashboard and backend are now cache-safe and `/api/command` returns structured JSON errors instead of an unhandled HTTP 500.


## v18 Computer Use
This build uses the current GA Responses API computer tool (`{"type":"computer"}`) with GPT-5.6. The deprecated `computer-use-preview` model/tool is not forced. The agent sends a desktop screenshot, executes returned computer actions locally with PyAutoGUI, captures a new screenshot, and continues until completion or the configured step limit.
