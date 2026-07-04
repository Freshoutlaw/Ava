# HANDOFF.md — Ava Project State

## Mission

Ava is a full-featured AI executive assistant for a single user, currently at Tier 20 (complete feature set). It combines a always-on backend loop (Python/Groq) with a React-based cosmic visualization UI, providing text and voice interaction, proactive heartbeat checks, persistent memory, autonomous workflows, and system automation. The goal is daily-driver reliability and personality—warm, plain-spoken, trustworthy.

---

## Current State

### Working & Verified ✅

- **Core chat loop (Tier 1–2):** Text input, streaming replies, tool calling all functional. Backend runs on Groq API with multi-key rotation (GROQ_API_KEY_1..5).
- **Voice (Tier 3):** Push-to-talk (hold key) with Deepgram STT and ElevenLabs TTS. Optional; fails gracefully if not installed.
- **Desktop UI (Tier 10):** PyWebView + React cosmic visualization app. Auto-detects built React dist; falls back to tkinter if PyWebView unavailable.
- **Memory (Tier 4):** JSON-backed persistent store (`data/memory.json`). Conversation history, user preferences, learned patterns all saved.
- **Heartbeat (Tier 5):** Background loop surfaces proactive checks (financial, time-sensitive, etc.) without spamming. Respects waking hours config.
- **Learning (Tier 6):** Tracks interaction success, tool accuracy, preference drift over time (`preference_model.json`, `tool_accuracy.json`).
- **System Automation (Tier 14):** Can screenshot, read screen, control mouse/keyboard via pyautogui.
- **Browser Automation (Tier 16):** Playwright installed and working; can navigate, click, extract data.
- **Workflows (Tier 19):** Autonomous goal execution; can chain tools, retry, store results.
- **Daemon (Windows):** Background service via pywin32 (optional, not required for dev).

### Half-Built / In Progress

- **React UI:** Cosmic visualization exists (`cosmicScene.jsx`, `cosmicSceneV2.jsx`); renders to desktop via PyWebView. Does NOT yet fully sync with backend state (mood colors, listening indicator, etc. are static or demo-only). Message history appears but interactivity is rough.
- **Web dashboard (--web-ui flag):** Server exists (`ui_server.py`) but minimal. No real-time updates; mostly a stub for future expansion.

### Broken / Blocked

- None known. All Tiers 1–20 report operational.

### Next Action for Fresh Session

1. **Read this file entirely** (you're doing it).
2. **Run `python ava.py`** to launch the desktop app and verify the current state.
3. **Identify the specific user request** (what's broken, what feature to add, what to refine).
4. **Make incremental changes** within the scope agreed in your initial briefing—don't refactor without asking.

---

## Decisions Made (and Why)

### 1. **Provider abstraction (Groq → Claude later)**
- **Decision:** Backend sits behind a thin provider seam. Only `_call_with_rotation()` in `brain.py` and a few lines in `ava.py` know about Groq.
- **Alternatives:** Hard-code Groq everywhere; would be painful to swap.
- **Reason:** We will move to Claude (Anthropic) once stable. The seam buys us that without rewriting the core.
- **Reversibility:** Easy. Provider swap is hours, not days.

### 2. **Multi-key rotation for Groq API**
- **Decision:** Support `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, … `GROQ_API_KEY_5` in `.env`. On rate limit (429), rotate and retry immediately.
- **Alternatives:** Single key + backoff timer; would waste user time waiting.
- **Reason:** Groq has aggressive rate limits in free tier. Multi-key gives us headroom without paid plan overhead.
- **Reversibility:** Trivial. Just use a single `GROQ_API_KEY` if you want to opt out.

### 3. **Memory as flat JSON + JSONL hybrid**
- **Decision:** Long-term state in `memory.json` (user preferences, goals, notes). Interaction log in `interaction_log.jsonl` (one turn per line, immutable).
- **Alternatives:** SQL database (overkill for single-user); all-in-one JSON (gets unwieldy).
- **Reason:** Single-user app needs simplicity. JSONL makes append-only interaction log cheap; JSON dict for ephemeral state. No migrations, no process locks.
- **Reversibility:** Easy to migrate to a real DB later if needed.

### 4. **Heartbeat as background thread, not cron**
- **Decision:** `heartbeat.py` spawns a daemon thread in the main process. Checks happen on a timer; notices queued and shown when user is engaged.
- **Alternatives:** Separate system daemon or cron job; would require install/registration overhead.
- **Reason:** Single-user, single machine. In-process is simpler, survives app restart. Can be migrated to a real background service later if deployed server-side.
- **Reversibility:** Fully reversible. Thread can become a subprocess or external service.

### 5. **PyWebView + React for desktop UI, not web-only**
- **Decision:** Desktop app renders React built dist via PyWebView (native window with Chromium). Text input -> Python backend -> JSON response -> React re-render.
- **Alternatives:** Pure web (localhost:5173); would lose native window feel. Pure Tkinter; would be hard to animate.
- **Reason:** Native window feel (always in taskbar, single-click focus) + modern UI (React + Tailwind + Three.js animations) without Electron bloat.
- **Reversibility:** React can still be served over HTTP. PyWebView can be swapped for a web frame or webview library.

### 6. **Confirmation gate on consequential actions**
- **Decision:** Before sending a message, spending money, deleting data, or committing code, Ava stops and asks for explicit confirmation. Gate applies to all modes (text, voice, heartbeat).
- **Alternatives:** Trust the user always; would be dangerous once Ava is autonomous.
- **Reason:** Once Tier 19–20 (workflows, proactive behavior) is live, accidental damage gets expensive. Gate is a safety rail.
- **Reversibility:** Easy. Disable in config or remove entirely if user disables Ava's autonomy.

### 7. **Tool registry + seam-based extension**
- **Decision:** All tools defined in one `tools/` module. Ava looks up by name and calls a single `run_tool()` function. Adding a tool = one function, never edit the loop.
- **Alternatives:** Runtime discovery (introspection); would be slower and harder to reason about.
- **Reason:** Predictability. Tool list is static, versioned, and auditable.
- **Reversibility:** N/A. This is the foundation. Would require rearchitecting if changed.

### 8. **Learning & preference tracking are optional (Tier 6+)**
- **Decision:** `learning.py` logs interactions, scores responses, builds a preference model. Can be disabled in config. Not in Tier 1–5.
- **Alternatives:** Mandatory from day one; adds complexity early.
- **Reason:** MVP works without learning. Once we're stable, learning kicks in (no code changes needed).
- **Reversibility:** Yes. Set `learning.enabled: false` in config.

---

## Architecture & Key Files

### Core Loop
- **[ava.py](ava.py)** — Main entry point. Initializes config, UI, Groq client, tools, memory, heartbeat. Runs the chat loop: get input → classify → route to brain/tools → stream reply → log → push to UI.
- **[brain.py](brain.py)** — Intelligence layer. Summarizes long history, does structured reasoning, self-critique, tool hint selection, turn classification (SIMPLE/LOOKUP/RESEARCH/TASK/MEMORY).
- **[tools/](tools/)** — Tool registry. `base.py` defines the tool interface; modules under `tools/` implement each tool (finance, outreach, system, browser, etc.).

### Memory & State
- **[memory.py](memory.py)** — Persistent JSON-backed store. Load/save `memory.json`, manage user preferences, goals, notes. Also exposes memory tools so Ava can tell herself things.
- **[data/](data/)** — Runtime state directory. `memory.json` (persistent), `interaction_log.jsonl` (immutable turn log), `preference_model.json` (learned preferences), `tool_accuracy.json` (tool success rates), heartbeat state, workflow state, audit log.

### Voice & Input
- **[heartbeat.py](heartbeat.py)** — Background daemon thread. Checks financial status, calendar, messages on a timer. Queues notices; shows them when user is engaged.
- **[learning.py](learning.py)** — Optional Tier 6+. Logs interactions, scores Ava's responses against user feedback, builds preference drift model.

### UI Layers
- **[ui_pywebview.py](ui_pywebview.py)** — Desktop native window via PyWebView. Renders built React app from `ui_react/dist/`. Sends JSON events to frontend, receives text input.
- **[ui_desktop.py](ui_desktop.py)** — Fallback tkinter UI. Bare-bones text interface if PyWebView not available.
- **[ui_server.py](ui_server.py)** — WebSocket server (optional `--web-ui` flag). Minimal; future expansion for browser-based dashboard.

### React UI
- **[ui_react/src/app.jsx](ui_react/src/app.jsx)** — Root component. Renders CosmicScene.
- **[ui_react/src/cosmicScene.jsx](ui_react/src/cosmicScene.jsx)** — Main visual. Three.js cosmic visualization (swirling orb, agent panels, message history, input bar). Animates color/state based on backend events.
- **[ui_react/src/cosmicSceneV2.jsx](ui_react/src/cosmicSceneV2.jsx)** — Alternate visual (less used; kept for reference/future).
- **[ui_react/package.json](ui_react/package.json)** — React 18 + Three.js + Tailwind. Vite for dev (`npm run dev`), build (`npm run build`).

### Config & Secrets
- **[config.json](config.json)** — Model, token limits, audio settings (sample rate, channels), VAD thresholds, audit log paths. All tunable without code change.
- **.env** — Secrets (GROQ_API_KEY_1..5, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID). Git-ignored from commit 1.

### Agents & Automation
- **[agents/](agents/)** — Multi-agent bus (Tier 12+). Specialized agents (Nova, Pulse, Forge, etc.) can collaborate. Base class in `base.py`; roster in `roster.py`.
- **[automation/](automation/)** — Autonomous workflows (Tier 19+). Goal-based execution, retry logic, dependency graphs.

### Other
- **[AGENT.md](AGENT.md)** — Single source of truth. Identity, stack, tiers, secrets, confirmation gates, proactive behavior rules. Read this before every session.
- **[Build instructions.md](Build instructions.md)** — How to build the React UI and run Ava. Kept up-to-date.
- **[docs/project-structure.md](docs/project-structure.md)** — Longer architectural notes (mostly reference; architecture is in this HANDOFF now).

---

## Gotchas & Hard-Won Knowledge

1. **Groq rate limits are aggressive.** Free tier: ~30 req/min per IP. Multi-key rotation buys headroom, but a single key will 429 under load. Have 3+ keys if possible.

2. **Deepgram + miniaudio can be finicky on Windows.** If voice fails to initialize, check that sounddevice and miniaudio are the right versions (see requirements.txt). Voice failures are silent (caught in `try/except`); check the console log.

3. **PyWebView loads from `ui_react/dist/` if it exists, else falls back to inline HTML.** If you rebuild React without clearing the old dist, you'll see stale UI. Always `npm run build` after editing React code, then restart ava.py.

4. **Token budget is rough (~3.5 chars per token).** History gets summarized at ~12k chars. If Ava suddenly forgets older context, she's just summarized it into a system prompt. This is intentional and saves money.

5. **Memory tools (tell/remember/recall) use the same backend as the main conversation.** If you call a memory tool in the middle of a turn, the turn counter still increments. Don't be surprised if context flushes sooner than expected.

6. **The heartbeat thread is a daemon.** It won't block app shutdown. If a heartbeat check hangs, the app can close before it finishes. Heartbeat timeouts are baked in (60 sec default).

7. **Confirmation gates stop *all* modes.** Text input, voice, and heartbeat-initiated actions all respect the gate. If you want to disable it temporarily for testing, set `confirmation_gate.enabled: false` in config.json.

8. **Interaction log is append-only and huge.** After 100k+ turns, it'll be >50MB. No automatic cleanup. Consider archiving old logs manually if storage becomes an issue.

9. **Tool accuracy tracking requires human feedback.** Ava assumes feedback comes via `feedback <tool-name> <score>` or via the preference model if you rate responses. Without feedback, all tools are equal weight.

10. **The React UI doesn't yet fully sync backend state.** Voice listening/speaking indicators are demo animations, not live state. Message history is synced but color mood (idle/listening/processing/speaking) doesn't respond to real backend state yet. This is a known TODO.

---

## Conventions In Play

1. **Modules are self-contained.** Each `tools/` module exports a `run()` function with signature `run(args: dict) -> dict`. No interdependencies between tools.

2. **Errors are caught and logged, never crash.** User-facing errors are brief and actionable. Internal errors go to audit log.

3. **No unit tests yet.** This is still a prototype/MVP. Testing is manual (run Ava, poke it, check audit log). Once stable, we'll add test harness.

4. **Config is JSON, not Python.** Makes it easy to tune without restarting for simple tweaks (would require a reload mechanism to be fully live).

5. **Secrets go in .env only.** Never in source, logs, or error messages.

6. **Tier numbers are fixed.** Tier 1 = text loop, Tier 3 = voice, Tier 5 = heartbeat, etc. New features don't get new tier numbers; they fit into the existing 20-tier hierarchy. See AGENT.md for the full map.

7. **Conversation turns are immutable.** Once logged to `interaction_log.jsonl`, a turn is final. Corrections go into a new turn.

8. **No async/await in the chat loop.** Everything is synchronous within a turn. Only the heartbeat and UI event loop run in parallel threads. This keeps the core simple.

---

## Open Questions

1. **Should the React UI state sync with the backend mood in real-time?** Currently color/animation is hardcoded or demos. Real sync would mean WebSocket events from Python → JavaScript on every state change. Worth doing?

2. **How long should the interaction log be kept?** It grows indefinitely. Should we auto-archive logs after N days or truncate older than 30 days?

3. **What's the voice ID for ElevenLabs?** Set in `.env` via `ELEVENLABS_VOICE_ID`. We haven't settled on a final voice for Ava; default to a generic ID. Need to pick one and document it.

4. **Should memory tools be in the confirmation gate?** `remember` and `tell_yourself` are usually safe, but `delete_memory` should probably gate. Currently they're all gated. Worth optimizing?

5. **Multi-agent coordination (Tier 12) — is this feature actually needed early?** Agents are defined but rarely used. Should we promote it or leave it as a Tier 12+ optional add-on?

---

## Do Not Touch

- **The tool registry interface** (`tools/base.py`). It's the contract between the loop and all tools. Changing it would break all 14+ tools.
- **The conversation turn structure** (`interaction_log.jsonl` format). It's the audit trail. Changing it would corrupt historical logs.
- **The heartbeat timing.** It's tuned conservatively (60 sec checks, rate-limited). Don't speed it up without stress testing.
- **The confirmation gate logic.** It's a safety rail. If you want to disable it, do so in config, not by removing code.
- **Git history** (this project is not currently in git, but when it is: commit messages should be descriptive, not automated).

---

## Resume Command

Read this HANDOFF.md carefully. Then:

1. **Run `python ava.py`** to launch Ava and verify the current state.
2. **Ask the user: "What's the next thing we're building or fixing?"** Get a concrete ask (e.g., "Add a calendar tool," "Fix the UI color sync," "Enable voice transcription logging").
3. **Make incremental changes.** Edit only the files needed; don't refactor unless asked.
4. **Test after each change.** Restart `python ava.py` and verify the feature works.
5. **Update config.json or add a new tool to tools/ as needed.** Don't modify ava.py, brain.py, or memory.py unless the core loop needs tweaking.
6. **Before you `clear` the context again, update this HANDOFF.md** with any new decisions, gotchas, or state changes.

---

**Last updated:** This session (no prior HANDOFF existed).  
**Confidence level:** High. All information sourced from actual files and code inspection, not memory.
