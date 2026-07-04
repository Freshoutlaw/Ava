"""
Ava — tools/vision.py  (Tier 18: Multi-Modal Vision)
------------------------------------------------------
Ava can see and understand images:
  - Analyse any image file or URL
  - Read your screen and describe what's visible
  - OCR: extract text from images/PDFs
  - Watch the screen for a visual trigger
  - Read documents (PDF, image-based)
  - See you via webcam — instantly, no cold-start (Tier 18b: live watch mode)
  - Operate the desktop autonomously (see → decide → click/type → repeat)

Uses Groq's vision model (llama-4-scout).
OCR uses pytesseract (requires tesseract installed).
Screen capture uses Pillow ImageGrab.
Webcam uses opencv-python.

REAL-TIME NOTE: a vision-language model only ever analyses a single still
frame per call — there's no "video understanding" API here. What this file
does instead to feel real-time:
  1. A persistent capture thread keeps the webcam open and a fresh frame
     buffered at all times, so see_me answers instantly (no camera cold-open
     delay, which is usually the 1-3s lag people notice).
  2. Optional "watch mode" pushes a live low-res JPEG frame to the UI several
     times a second (so you see a live preview), and periodically asks the
     vision model to comment ONLY when the scene has meaningfully changed —
     avoiding both spam and wasted API calls.
"""

import os, io, base64, time, json, threading
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

try:
    from PIL import ImageGrab, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

import requests as _requests

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _encode_image_path(path: str) -> tuple[str, str]:
    p = Path(path)
    ext_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",
               ".gif":"image/gif",".webp":"image/webp",".bmp":"image/bmp"}
    media = ext_map.get(p.suffix.lower(), "image/png")
    data  = base64.standard_b64encode(p.read_bytes()).decode("utf-8")
    return data, media


def _encode_image_url(url: str) -> tuple[str, str]:
    resp = _requests.get(url, timeout=15)
    ct   = resp.headers.get("Content-Type","image/jpeg").split(";")[0]
    data = base64.standard_b64encode(resp.content).decode("utf-8")
    return data, ct


def _vision_call(image_b64: str, media_type: str, prompt: str) -> str:
    """Call Groq vision model with an image + prompt."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip() or os.environ.get("GROQ_API_KEY_1", "").strip()
    if not api_key:
        return "Error: no Groq API key set (GROQ_API_KEY_1)."
    import groq as _groq
    client   = _groq.Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=VISION_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type":"image_url","image_url":{"url":f"data:{media_type};base64,{image_b64}"}},
                {"type":"text","text": prompt},
            ],
        }],
    )
    return response.choices[0].message.content or ""


# ── Handlers: static images / screen / OCR / documents ────────────────────────

def handle_analyse_image(inputs: dict) -> str:
    path   = inputs.get("path","").strip()
    url    = inputs.get("url","").strip()
    prompt = inputs.get("prompt","Describe this image in detail.").strip()
    if not path and not url:
        return "Error: provide 'path' (file) or 'url'."
    try:
        b64, mt = _encode_image_path(path) if path else _encode_image_url(url)
        return _vision_call(b64, mt, prompt)
    except Exception as e:
        return f"Vision error: {e}"


def handle_read_screen(inputs: dict) -> str:
    if not PIL_AVAILABLE:
        return "Error: Pillow not installed. Run: pip install Pillow"
    prompt = inputs.get("prompt","What is currently visible on this screen? Describe everything in detail.").strip()
    try:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        result = _vision_call(b64, "image/png", prompt)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DATA_DIR / f"screen_read_{ts}.png"
        img.save(str(path))
        return f"Screen analysis (saved: {path}):\n\n{result}"
    except Exception as e:
        return f"Screen read error: {e}"


def handle_ocr_image(inputs: dict) -> str:
    if not OCR_AVAILABLE:
        return ("pytesseract not installed.\n"
                "Install: pip install pytesseract\n"
                "Also install Tesseract OCR engine:\n"
                "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "  Linux: sudo apt install tesseract-ocr")
    if not PIL_AVAILABLE:
        return "Error: Pillow not installed. Run: pip install Pillow"
    path = inputs.get("path","").strip()
    url  = inputs.get("url","").strip()
    lang = inputs.get("language","eng")
    try:
        if path:
            img = Image.open(path)
        elif url:
            resp = _requests.get(url, timeout=15)
            img  = Image.open(io.BytesIO(resp.content))
        else:
            img = ImageGrab.grab()
        text = pytesseract.image_to_string(img, lang=lang)
        return f"OCR result ({len(text)} chars):\n{text}"
    except Exception as e:
        return f"OCR error: {e}"


def handle_watch_screen(inputs: dict) -> str:
    if not PIL_AVAILABLE:
        return "Error: Pillow not installed."
    if not OCR_AVAILABLE:
        return "Error: pytesseract not installed (needed for text detection)."
    watch_for = inputs.get("watch_for","").strip()
    prompt    = inputs.get("vision_prompt","").strip()
    try:
        img = ImageGrab.grab()
        if watch_for:
            text  = pytesseract.image_to_string(img)
            found = watch_for.lower() in text.lower()
            return f"Screen check: '{watch_for}' → {'FOUND ✓' if found else 'NOT FOUND'}\nOCR text preview: {text[:400]}"
        elif prompt:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
            return _vision_call(b64, "image/png", prompt)
        else:
            return "Error: provide 'watch_for' (text) or 'vision_prompt'."
    except Exception as e:
        return f"Watch screen error: {e}"


def handle_read_document(inputs: dict) -> str:
    path = inputs.get("path","").strip()
    if not path: return "Error: 'path' is required."
    p = Path(path)
    if not p.exists(): return f"Error: file not found — {path}"
    if p.suffix.lower() == ".pdf":
        try:
            import fitz
            doc, pages = fitz.open(path), []
            for page in doc:
                text = page.get_text()
                if len(text.strip()) > 50:
                    pages.append(text)
                elif PIL_AVAILABLE and OCR_AVAILABLE:
                    pix  = page.get_pixmap(dpi=150)
                    img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    pages.append(pytesseract.image_to_string(img))
            full = "\n\n--- Page Break ---\n\n".join(pages)
            return f"Document ({len(doc)} pages):\n{full[:5000]}"
        except ImportError:
            return "PyMuPDF not installed. Run: pip install PyMuPDF"
        except Exception as e:
            return f"PDF read error: {e}"
    else:
        return handle_ocr_image({"path": path})


VISION_TOOLS = [
    {
        "name": "analyse_image",
        "description": (
            "Analyse an image file or URL using vision AI. Answer questions about it, "
            "describe contents, read text in it, or identify objects. "
            "Provide 'path' for local files or 'url' for web images."
        ),
        "input_schema": {
            "type":"object",
            "properties": {
                "path":   {"type":"string","description":"Local file path to image"},
                "url":    {"type":"string","description":"URL of image to analyse"},
                "prompt": {"type":"string","description":"Question or instruction (default: describe the image)"},
            },
            "required": [],
        },
        "handler": handle_analyse_image, "requires_confirmation": False,
    },
    {
        "name": "read_screen",
        "description": "Take a screenshot and describe what is currently visible on the screen.",
        "input_schema": {
            "type":"object",
            "properties": {"prompt": {"type":"string","description":"What to focus on or ask about the screen"}},
            "required": [],
        },
        "handler": handle_read_screen, "requires_confirmation": False,
    },
    {
        "name": "ocr_image",
        "description": "Extract text from an image using OCR. If no path/url given, OCRs the current screen.",
        "input_schema": {
            "type":"object",
            "properties": {
                "path":     {"type":"string","description":"Image file path"},
                "url":      {"type":"string","description":"Image URL"},
                "language": {"type":"string","description":"OCR language code (default: eng)"},
            },
            "required": [],
        },
        "handler": handle_ocr_image, "requires_confirmation": False,
    },
    {
        "name": "watch_screen",
        "description": "Check the current screen for specific text or visually analyse it.",
        "input_schema": {
            "type":"object",
            "properties": {
                "watch_for":     {"type":"string","description":"Text to look for on screen"},
                "vision_prompt": {"type":"string","description":"Visual question to ask about the screen"},
            },
            "required": [],
        },
        "handler": handle_watch_screen, "requires_confirmation": False,
    },
    {
        "name": "read_document",
        "description": "Extract text from a PDF or image-based document using OCR.",
        "input_schema": {
            "type":"object",
            "properties": {"path": {"type":"string","description":"Path to PDF or image document"}},
            "required": ["path"],
        },
        "handler": handle_read_document, "requires_confirmation": False,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Live webcam — persistent capture + optional "watch mode"
# ═══════════════════════════════════════════════════════════════════════════════
#
# _WebcamStream keeps the camera open in a background thread once started,
# continuously refreshing a buffered latest frame. This removes the cold-open
# lag (~1-3s) that made one-shot see_me feel laggy. When "watching" is on, it
# also (a) streams a low-res live JPEG to the UI several times a second via a
# registered callback, and (b) periodically asks the vision model to comment,
# but ONLY when the scene has meaningfully changed (mean pixel diff above a
# threshold) — so it narrates naturally instead of spamming every few seconds.

_frame_callback = None   # set by ava.py: fn(base64_jpeg_str) -> None, pushed to UI
_comment_callback = None # set by ava.py: fn(text) -> None, e.g. pushed as a notice/spoken


def set_frame_callback(fn):
    """Register a callback that receives each live preview frame (base64 JPEG)."""
    global _frame_callback
    _frame_callback = fn


def set_comment_callback(fn):
    """Register a callback that receives Ava's proactive commentary text."""
    global _comment_callback
    _comment_callback = fn


class _WebcamStream:
    def __init__(self):
        self._cap          = None
        self._lock         = threading.Lock()
        self._latest_jpeg  = None      # bytes, always the freshest captured frame
        self._running      = threading.Event()
        self._thread        = None
        self._commentary_on = False
        self._camera_index  = 0
        self._last_comment_frame = None
        self._comment_interval   = 12.0   # seconds between commentary checks
        self._diff_threshold      = 18.0  # mean abs pixel diff to count as "changed"

    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self, camera_index: int = 0, commentary: bool = False) -> str:
        if self._running.is_set():
            self._commentary_on = commentary or self._commentary_on
            return "Already watching — commentary " + ("enabled" if self._commentary_on else "unchanged") + "."
        if not CV2_AVAILABLE:
            return "Error: opencv-python not installed. Run: pip install opencv-python"

        self._camera_index  = camera_index
        self._commentary_on = commentary
        self._cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW if os.name == "nt" else 0)
        if not self._cap.isOpened():
            self._cap = None
            return f"Error: couldn't open webcam (index {camera_index})."

        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="ava-webcam", daemon=True)
        self._thread.start()
        return f"Watching started (camera {camera_index}). Commentary: {'on' if commentary else 'off'}."

    def stop(self) -> str:
        if not self._running.is_set():
            return "Not currently watching."
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock:
            if self._cap:
                self._cap.release()
            self._cap = None
            self._latest_jpeg = None
        return "Stopped watching."

    def get_latest_frame_b64(self) -> str | None:
        with self._lock:
            if self._latest_jpeg is None:
                return None
            return base64.standard_b64encode(self._latest_jpeg).decode("utf-8")

    def _loop(self):
        last_ui_push = 0.0
        last_comment_check = 0.0
        prev_gray = None

        while self._running.is_set():
            with self._lock:
                if self._cap is None:
                    break
                ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(0.1)
                continue

            success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if success:
                with self._lock:
                    self._latest_jpeg = buf.tobytes()

            now = time.time()

            # Push a live preview frame to the UI at ~4fps (throttled, not every loop iter)
            if _frame_callback and (now - last_ui_push) > 0.25:
                try:
                    small = cv2.resize(frame, (320, 240))
                    ok2, sbuf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 55])
                    if ok2:
                        _frame_callback(base64.standard_b64encode(sbuf.tobytes()).decode("utf-8"))
                except Exception:
                    pass
                last_ui_push = now

            # Periodic change-triggered commentary
            if self._commentary_on and (now - last_comment_check) > self._comment_interval:
                last_comment_check = now
                try:
                    gray = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
                    if prev_gray is not None:
                        diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
                        if diff > self._diff_threshold and _comment_callback:
                            b64 = base64.standard_b64encode(buf.tobytes()).decode("utf-8") if success else None
                            if b64:
                                comment = _vision_call(
                                    b64, "image/jpeg",
                                    "In one short sentence, note anything notable that changed "
                                    "about the person or scene compared to a normal baseline. "
                                    "If nothing meaningful changed, reply with exactly: NOTHING."
                                )
                                if comment.strip().upper() != "NOTHING":
                                    _comment_callback(comment.strip())
                    prev_gray = gray
                except Exception:
                    pass

            time.sleep(0.08)   # ~12fps internal capture rate


_stream = _WebcamStream()


# ── Tool handlers: webcam ─────────────────────────────────────────────────────

def handle_see_me(inputs: dict) -> str:
    """
    Look at the webcam right now and describe what's visible.
    Uses the live buffered frame if watch mode is active (instant, no lag);
    otherwise opens the camera briefly for a one-shot capture.
    """
    prompt = inputs.get("prompt", "Describe what you see — the person, their expression, and surroundings.").strip()

    if _stream.is_running():
        b64 = _stream.get_latest_frame_b64()
        if b64:
            result = _vision_call(b64, "image/jpeg", prompt)
            return result

    # Fallback: one-shot open (has the cold-start delay)
    if not CV2_AVAILABLE:
        return "Error: opencv-python not installed. Run: pip install opencv-python"
    camera_index = int(inputs.get("camera_index", 0))
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW if os.name == "nt" else 0)
    if not cap.isOpened():
        cap.release()
        return f"Error: couldn't open webcam (index {camera_index}). Is another app using it?"
    try:
        for _ in range(5):
            cap.read(); time.sleep(0.05)
        ok, frame = cap.read()
        if not ok or frame is None:
            return "Error: failed to capture a frame from the webcam."
        success, buf = cv2.imencode(".jpg", frame)
        if not success:
            return "Error: failed to encode webcam frame."
        b64 = base64.standard_b64encode(buf.tobytes()).decode("utf-8")
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DATA_DIR / f"webcam_{ts}.jpg"
        path.write_bytes(buf.tobytes())
        result = _vision_call(b64, "image/jpeg", prompt)
        return f"(Tip: say 'watch me' first for instant, lag-free responses next time.)\n\n{result}"
    finally:
        cap.release()


def handle_start_watching(inputs: dict) -> str:
    """
    Start real-time webcam watching: keeps the camera open continuously so
    see_me answers instantly, streams a live preview to the UI, and — if
    commentary is enabled — proactively narrates meaningful changes.
    """
    camera_index = int(inputs.get("camera_index", 0))
    commentary   = bool(inputs.get("commentary", False))
    return _stream.start(camera_index=camera_index, commentary=commentary)


def handle_stop_watching(inputs: dict) -> str:
    """Stop real-time webcam watching and release the camera."""
    return _stream.stop()


VISION_TOOLS += [
    {
        "name": "see_me",
        "description": (
            "Look at the webcam right now and describe what's visible — the person, "
            "expression, surroundings. Use when asked 'can you see me', 'how do I look', etc. "
            "Instant if 'watch me' / start_watching is already active; otherwise opens the camera briefly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt":       {"type": "string",  "description": "What to focus on (default: describe person + surroundings)."},
                "camera_index": {"type": "integer", "description": "Webcam index if multiple cameras (default 0)."},
            },
            "required": [],
        },
        "handler": handle_see_me, "requires_confirmation": False,
    },
    {
        "name": "start_watching",
        "description": (
            "Start real-time webcam watching — keeps the camera continuously open so future "
            "see_me calls are instant with no lag, streams a live preview to the UI, and can "
            "optionally narrate notable changes on its own without being asked (set commentary=true). "
            "Use when the user says 'watch me', 'keep an eye on me', 'see me in real time', or similar. "
            "Requires confirmation since it keeps the camera on continuously (privacy)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "camera_index": {"type": "integer", "description": "Webcam index (default 0)."},
                "commentary":   {"type": "boolean", "description": "If true, Ava proactively comments on notable changes (default false)."},
            },
            "required": [],
        },
        "handler": handle_start_watching, "requires_confirmation": True,
    },
    {
        "name": "stop_watching",
        "description": "Stop real-time webcam watching and release the camera. Use when asked to stop watching / turn off the camera.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": handle_stop_watching, "requires_confirmation": False,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Computer-use loop — "operate my desktop"
# ═══════════════════════════════════════════════════════════════════════════════

def _operate_vision_call(image_b64: str, goal: str, history: str) -> dict:
    prompt = f"""You are operating a Windows desktop on the user's behalf.

Goal: {goal}

Steps taken so far:
{history or '(none yet)'}

Look at the current screenshot. Decide the SINGLE next action to move toward the goal.
Reply with ONLY a JSON object, no other text:
{{
  "reasoning": "brief note on what you see and why this action",
  "action": "click" | "type" | "hotkey" | "done" | "stuck",
  "x": 000,
  "y": 000,
  "text": "...",
  "keys": "ctrl+c",
  "done_summary": ""
}}

Use "done" when the goal is clearly achieved. Use "stuck" if nothing productive can be done."""
    result_text = _vision_call(image_b64, "image/png", prompt)
    cleaned = result_text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return {"action": "stuck", "reasoning": f"Could not parse model response: {result_text[:200]}"}


def handle_operate_computer(inputs: dict) -> str:
    if not PIL_AVAILABLE:
        return "Error: Pillow not installed. Run: pip install Pillow"
    goal      = inputs.get("goal", "").strip()
    max_steps = min(int(inputs.get("max_steps", 8)), 20)
    if not goal:
        return "Error: 'goal' is required, e.g. 'open Notepad and type Hello'."
    try:
        from tools.system import handle_mouse_click, handle_type_text, handle_hotkey
    except Exception as e:
        return f"Error: system automation tools unavailable ({e})."

    history_lines: list[str] = []
    log_lines:     list[str] = [f"Operating computer toward goal: {goal}"]

    for step in range(1, max_steps + 1):
        try:
            img = ImageGrab.grab()
        except Exception as e:
            return f"Screenshot failed at step {step}: {e}"

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

        decision = _operate_vision_call(b64, goal, "\n".join(history_lines))
        action   = decision.get("action", "stuck")
        reason   = decision.get("reasoning", "")
        log_lines.append(f"Step {step}: {action} — {reason[:100]}")

        if action == "done":
            log_lines.append(f"✓ Goal achieved: {decision.get('done_summary', '')}")
            break
        if action == "stuck":
            log_lines.append("✗ Stopped — Ava couldn't find a productive next step.")
            break
        if action == "click":
            x, y = decision.get("x"), decision.get("y")
            if x is None or y is None:
                log_lines.append("  (click requested but no coordinates given — skipping)")
                history_lines.append(f"Step {step}: attempted click but coordinates were missing.")
                continue
            result = handle_mouse_click({"x": x, "y": y})
            history_lines.append(f"Step {step}: clicked ({x},{y}) — {reason[:80]}")
            log_lines.append(f"  → {result}")
        elif action == "type":
            text = decision.get("text", "")
            result = handle_type_text({"text": text})
            history_lines.append(f"Step {step}: typed '{text[:40]}' — {reason[:80]}")
            log_lines.append(f"  → {result}")
        elif action == "hotkey":
            keys = decision.get("keys", "")
            result = handle_hotkey({"keys": keys})
            history_lines.append(f"Step {step}: pressed '{keys}' — {reason[:80]}")
            log_lines.append(f"  → {result}")
        else:
            log_lines.append(f"  (unknown action '{action}' — stopping)")
            break

        time.sleep(0.6)
    else:
        log_lines.append(f"⚠ Reached max_steps ({max_steps}) without completing the goal.")

    return "\n".join(log_lines)


VISION_TOOLS += [
    {
        "name": "operate_computer",
        "description": (
            "Autonomously operate the desktop toward a goal: Ava repeatedly looks at "
            "the screen, decides the next click/type/keypress, and executes it, until "
            "the goal is done or max_steps is reached. ALWAYS requires confirmation — "
            "this controls the real mouse and keyboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal":      {"type": "string",  "description": "What Ava should accomplish on screen, described plainly."},
                "max_steps": {"type": "integer", "description": "Max actions before stopping (default 8, max 20)."},
            },
            "required": ["goal"],
        },
        "handler": handle_operate_computer, "requires_confirmation": True,
    },
]
