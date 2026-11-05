#!/usr/bin/env python3
"""
server.py — Tiny stdlib web server for the Knowledge Galaxy viewer + chat brain.
Serves ONLY the viewer/ folder on port 4700. config.json stays in project root.
"""

import http.server
import os
import sys
import json
import re
import uuid
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http import HTTPStatus

import actions
import stt
import telephony


PORT = 4703
PROJECT_ROOT = Path(__file__).parent
VIEWER_DIR = PROJECT_ROOT / "viewer"
NOTES_DIR = PROJECT_ROOT / "notes"
CONFIG_FILE = PROJECT_ROOT / "config.json"


# ─── Load config ──────────────────────────────────────────────────────────
def load_config():
    if not CONFIG_FILE.exists():
        print(f"Config not found: {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


CONFIG = load_config()
PROVIDER = CONFIG.get("provider", "ollama")  # "ollama" | "openrouter" | "anthropic"

# ─── Provider settings ───────────────────────────────────────────────────
# config.json may nest per-provider settings. The legacy flat keys
# (api_key / model) are still honoured as a fallback.
OLLAMA_CFG = CONFIG.get("ollama", {})
OLLAMA_HOST = OLLAMA_CFG.get("host", "http://localhost:11434").rstrip("/")
OLLAMA_TIMEOUT = int(OLLAMA_CFG.get("timeout", 300))


def _parse_ollama_models(raw):
    """Accept ['name', ...] or [{'name':..., 'think':...}, ...]."""
    models = []
    for item in raw or []:
        if isinstance(item, str):
            models.append({"name": item, "think": None})
        elif isinstance(item, dict) and item.get("name"):
            models.append({"name": item["name"], "think": item.get("think")})
    return models


OLLAMA_MODELS = _parse_ollama_models(OLLAMA_CFG.get("models"))
if not OLLAMA_MODELS:
    OLLAMA_MODELS = [{"name": OLLAMA_CFG.get("model", "gemma4:31b-cloud"), "think": None}]

OPENROUTER_CFG = CONFIG.get("openrouter", {})
API_KEY = OPENROUTER_CFG.get("api_key") or CONFIG.get("api_key", "")
MODEL = OPENROUTER_CFG.get("model") or CONFIG.get("model", "nvidia/nemotron-3-ultra-550b-a55b:free")

STT_CFG = CONFIG.get("stt", {})
ACTIONS_CFG = CONFIG.get("actions", {})
ACTIONS_ENABLED = bool(ACTIONS_CFG.get("enabled", True))


# ─── Load notes for scoring ───────────────────────────────────────────────
NOTE_DATA = []  # list of {id, title, content, excerpt, words, title_words}

def load_notes():
    global NOTE_DATA
    md_files = sorted(NOTES_DIR.rglob("*.md"))
    for idx, filepath in enumerate(md_files):
        content = filepath.read_text(encoding="utf-8")
        # Extract title
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else filepath.stem.replace("-", " ").title()
        # Clean content for word extraction
        clean = re.sub(r'^---[\s\S]*?---', '', content)
        clean = re.sub(r'^#+\s.*$', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'\[\[([^\]]+)\]\]', r'\1', clean)
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
        clean = re.sub(r'```[\s\S]*?```', '', clean)
        clean = re.sub(r'`([^`]+)`', r'\1', clean)
        clean = re.sub(r'\|.*\|', '', clean)
        words = set(re.findall(r'\b\w{3,}\b', clean.lower()))
        title_words = set(re.findall(r'\b\w{3,}\b', title.lower()))
        NOTE_DATA.append({
            "id": idx,
            "title": title,
            "content": content,
            "words": words,
            "title_words": title_words,
        })
    print(f"Loaded {len(NOTE_DATA)} notes for chat scoring")


load_notes()


# ─── Session storage ──────────────────────────────────────────────────────
SESSIONS = {}  # session_id -> {"history": [{"role": "...", "content": "..."}], "last_access": time}
SESSION_LOCK = threading.Lock()
SESSION_TTL = 3600  # 1 hour


import time

def get_session(session_id):
    with SESSION_LOCK:
        now = time.time()
        if session_id in SESSIONS:
            if now - SESSIONS[session_id]["last_access"] < SESSION_TTL:
                SESSIONS[session_id]["last_access"] = now
                return SESSIONS[session_id]
            else:
                del SESSIONS[session_id]
        # Create new
        session = {"history": [], "last_access": now}
        SESSIONS[session_id] = session
        return session


# ─── Keyword scoring ──────────────────────────────────────────────────────
def score_notes(question: str, top_n: int = 6) -> list:
    """Score notes by keyword overlap with question. Title matches weigh 3x."""
    q_words = set(re.findall(r'\b\w{3,}\b', question.lower()))
    if not q_words:
        return []

    scored = []
    for note in NOTE_DATA:
        # Body overlap
        body_overlap = len(q_words & note["words"])
        # Title overlap (weighted 3x)
        title_overlap = len(q_words & note["title_words"]) * 3
        score = body_overlap + title_overlap
        if score > 0:
            scored.append((score, note["id"]))

    scored.sort(reverse=True, key=lambda x: x[0])
    return [note_id for _, note_id in scored[:top_n]]


# ─── Action protocol ─────────────────────────────────────────────────────
# Appended to the brain's prompt so it knows how to ask for a machine action.
ACTION_PROMPT = (
    "\n\nYou can also drive this computer. When the user asks you to DO something "
    "on the machine, reply with ONLY a JSON object and nothing else "
    "(no code fences, no explanation, no other text):\n"
    '{"say": "<one short witty line>", "action": {"type": "<type>", ...}}\n'
    "Use exactly one of these action types:\n"
    '- {"type": "system_status"}\n'
    '- {"type": "list_dir", "path": "<folder>"}\n'
    '- {"type": "read_file", "path": "<file>"}\n'
    '- {"type": "search_files", "pattern": "*.pdf", "root": "<folder>"}\n'
    '- {"type": "open_app", "app": "notepad"}\n'
    '- {"type": "open_path", "path": "<file or folder>"}\n'
    '- {"type": "open_url", "url": "https://..."}\n'
    '- {"type": "run_command", "command": "git status"}\n'
    "Prefer a supported app or command; if the user asks for something outside "
    "this list, say so in plain text instead. For every other message reply "
    "with plain text and no JSON at all."
)


# ─── LLM API call ───────────────────────────────────────────────────────────
def call_llm(question: str, context_notes: list, history: list, is_boot: bool = False) -> str:
    """Call LLM API (Anthropic or OpenRouter) with context notes and history."""
    import urllib.request

    # Build context from notes
    context_parts = []
    for note in context_notes:
        context_parts.append(f"--- NOTE {note['id']}: {note['title']} ---\n{note['content'][:3000]}")
    context = "\n\n".join(context_parts)

    if is_boot:
        system_prompt = (
            "You are Jarvis, a dry, impeccably polite British butler with razor wit. "
            "Address the user as 'sir' occasionally — not every sentence. "
            "One genuinely funny line beats three bland ones. "
            "Deliver a boot greeting: 'Good evening, sir. [N] notes indexed, all present and accounted for' "
            "where [N] is the actual note count provided. Keep it to one sentence."
        )
        # For boot, pass note count in context
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": f"Note count: {len(context_notes)}. Deliver the boot greeting."})
    else:
        system_prompt = (
            "You are Jarvis, a dry, impeccably polite British butler with razor wit. "
            "Address the user as 'sir' occasionally — not every sentence. "
            "One genuinely funny line beats three bland ones. "
            "Answer questions about the provided notes in ONE witty sentence plus the facts — "
            "never recite the note back (it's on screen). "
            "If the notes don't contain the answer, admit it with a sigh. "
            "Do not use outside knowledge. "
            "Handle small talk and jokes in character WITHOUT mentioning notes or citations. "
            "Only discuss the provided notes when the user actually asks about them."
        )
        if ACTIONS_ENABLED:
            system_prompt += ACTION_PROMPT
        # Build messages with history
        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-6:]:  # Keep last 6 exchanges
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": f"Context notes:\n{context}\n\nQuestion: {question}"})

    if PROVIDER == "ollama":
        return call_ollama(messages)
    elif PROVIDER == "openrouter":
        return call_openrouter(messages)
    else:
        return call_anthropic(messages)


def call_ollama(messages: list) -> str:
    """Call a local Ollama model, falling back to other local models on failure."""
    errors = []
    for entry in OLLAMA_MODELS:
        model = entry["name"]
        try:
            text = _call_ollama_model(model, messages, entry.get("think"))
            if text:
                return text
            errors.append(f"{model}: empty response")
        except Exception as e:
            errors.append(f"{model}: {type(e).__name__} {e}")
    return "[No local model answered. Tried " + "; ".join(errors) + "]"


def _call_ollama_model(model: str, messages: list, think=None) -> str:
    """Single Ollama chat call. Returns the assistant text, or '' if the model
    produced nothing (reasoning models can return only a `thinking` field)."""
    import urllib.request

    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {"temperature": 0.7, "num_predict": 400},
    }
    # Reasoning models (qwen3) emit a separate `thinking` field and can leave
    # `content` empty; turning thinking off keeps replies short and fast.
    if think is not None:
        payload["think"] = think

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        result = json.loads(resp.read().decode())

    msg = result.get("message", {})
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("thinking") or "").strip()
    return content


def call_anthropic(messages: list) -> str:
    """Call Anthropic Messages API."""
    import urllib.request

    payload = {
        "model": MODEL,
        "max_tokens": 500,
        "system": messages[0]["content"],
        "messages": messages[1:],
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        return f"[API Error {e.code}: {err_body}]"
    except Exception as e:
        return f"[Error: {e}]"


def call_openrouter(messages: list) -> str:
    """Call OpenRouter API (OpenAI-compatible)."""
    import urllib.request

    payload = {
        "model": MODEL,
        "max_tokens": 500,
        "messages": messages,
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "HTTP-Referer": "http://localhost:4703",
            "X-Title": "Knowledge Galaxy",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            msg = result["choices"][0]["message"]
            # Nemotron models may return content in reasoning field
            content = msg.get("content") or msg.get("reasoning") or ""
            return content.strip()
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read(600).decode("utf-8", "replace")
        except Exception:
            pass
        if e.code == 429:
            return ("[OpenRouter's free daily quota is used up"
                    f"{_reset_hint(err_body)}. Top up credits, or switch the "
                    "brain to Ollama in config.json.]")
        return f"[API Error {e.code}: {err_body}]"
    except Exception as e:
        return f"[Error: {type(e).__name__}: {e}]"


def _reset_hint(err_body: str) -> str:
    """Human-readable reset time from an OpenRouter 429 body, if present."""
    try:
        headers = json.loads(err_body).get("error", {}).get("metadata", {}).get("headers", {})
        ms = headers.get("X-RateLimit-Reset")
        if ms:
            import datetime
            when = datetime.datetime.fromtimestamp(int(ms) / 1000).astimezone()
            return f" — resets at {when:%-I:%M %p} on {when:%Y-%m-%d}"
    except Exception:
        pass
    return ""


# ─── Deterministic action intent ─────────────────────────────────────────
# The model writes fine prose but does not reliably emit action JSON, so the
# intents that actually change the machine are detected from the wording
# itself. The model is then only asked for the witty line.

ACTION_LINE_PROMPT = (
    "You are Jarvis, a dry, impeccably polite British butler with razor wit. "
    "The user asked you to do something on their computer and you are about to. "
    "Reply with ONE short witty sentence (at most 20 words) saying what you are "
    "about to do. No JSON, no explanation, just the line."
)


def detect_action_intent(question: str):
    """Guess the action from the wording alone. Returns an action dict or None."""
    q = (question or "").lower().strip()
    if not q:
        return None

    # "run whoami" / "execute git status"
    if re.search(r"\b(run|execute)\b", q):
        for cmd in actions.ALLOWED_COMMANDS:
            if cmd in q:
                return {"type": "run_command", "command": cmd}

    # "open notepad" / "launch chrome" / "start the terminal"
    if re.search(r"\b(open|launch|start)\b", q):
        for alias in sorted(actions.APP_ALIASES, key=len, reverse=True):
            if re.search(r"\b" + re.escape(alias) + r"\b", q):
                return {"type": "open_app", "app": alias}

    # "check system status" / "how much memory is free"
    if (re.search(r"\b(system status|machine status|computer status|system vitals|"
                  r"cpu load|cpu usage|ram usage|memory usage|memory free|"
                  r"disk space|disk usage|uptime)\b", q)
            or (re.search(r"\b(status|cpu|ram|memory|disk|uptime|vitals)\b", q)
                and re.search(r"\b(check|show|tell|report|how much|what)\b", q))):
        return {"type": "system_status"}

    return None


def call_llm_action_line(question: str, action: dict) -> str:
    """One witty line announcing the action, with a plain fallback."""
    fallback = f"Certainly, sir - {actions.describe(action)}."
    try:
        messages = [
            {"role": "system", "content": ACTION_LINE_PROMPT},
            {"role": "user", "content":
                f"The user said: {question}\nYou will: {actions.describe(action)}"},
        ]
        if PROVIDER == "ollama":
            line = call_ollama(messages)
        elif PROVIDER == "openrouter":
            line = call_openrouter(messages)
        else:
            line = call_anthropic(messages)
        line = (line or "").strip()
        # The provider helpers return bracketed strings on error - not a line.
        if not line or (line.startswith("[") and line.endswith("]")):
            return fallback
        return line
    except Exception:
        return fallback


def _strip_code_fence(text: str) -> str:
    """Remove a markdown code-fence wrapper, e.g. ```json { ... } ```."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    return s


def _parse_action(text: str):
    """If the brain replied with an action envelope, return it.

    Expected shape: {"say": "...", "action": {"type": ..., ...}}
    Returns None for ordinary prose replies.
    """
    if not text:
        return None
    stripped = _strip_code_fence(text)
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # Tolerate trailing chatter around the JSON.
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            obj = json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(obj, dict) and isinstance(obj.get("action"), dict):
        return {"say": str(obj.get("say") or "").strip(), "action": obj["action"]}
    return None


# ─── Request handler ──────────────────────────────────────────────────────
class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    # HTTP/1.1 so responses can be keep-alive; every response must therefore
    # carry a Content-Length (see send_json and the file handler).
    protocol_version = "HTTP/1.1"
    timeout = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.address_string()}] {format % args}\n")

    def end_headers(self):
        if self.path.endswith(('.js', '.css', '.html', '.json', '.png', '.jpg', '.svg', '.ico')):
            self.send_header('Cache-Control', 'public, max-age=3600')
        else:
            self.send_header('Cache-Control', 'no-cache')
        # No wildcard CORS: the app is same-origin only, and it can drive this
        # machine, so no other site may talk to it.
        super().end_headers()

    def _is_same_origin(self) -> bool:
        """True only for requests that came from this app's own origin.

        Browsers set Origin on cross-origin POSTs and Sec-Fetch-Site on every
        fetch, so both are checked. This is what stops a random web page from
        POSTing to localhost and making Jarvis open apps or run commands.
        """
        origin = self.headers.get('Origin')
        if origin:
            allowed = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
            if origin.rstrip('/') not in allowed:
                return False
        site = self.headers.get('Sec-Fetch-Site')
        if site and site not in ('same-origin', 'none'):
            return False
        return True

    def do_GET(self):
        # The one line left on the desk by the last phone call.
        if self.path == '/desk':
            self.send_json(HTTPStatus.OK, desk_line())
            return
        # Block access to config.json and any file outside viewer/
        if self.path.startswith('/config.json') or '..' in Path(self.path.lstrip('/')).parts:
            self.send_error(403, "Forbidden")
            return
        super().do_GET()

    def do_POST(self):
        # Jarvis can act on this machine, so only same-origin POSTs are served.
        if not self._is_same_origin():
            self.send_json(HTTPStatus.FORBIDDEN, {
                "error": "Cross-origin requests are not allowed."
            })
            return
        if self.path == '/chat':
            self.handle_chat()
        elif self.path == '/remember':
            self.handle_remember()
        elif self.path == '/act':
            self.handle_act()
        elif self.path == '/transcribe':
            self.handle_transcribe()
        else:
            self.send_error(404, "Not Found")

    def handle_act(self):
        """Run an allowlisted local action (see actions.py)."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Empty request"})
            return

        try:
            body = json.loads(self.rfile.read(content_length).decode())
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        if not ACTIONS_ENABLED:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Actions are disabled."})
            return

        clean, error = actions.validate(body.get("action") or {})
        if error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": error})
            return

        # Anything that changes the machine needs the user's explicit OK.
        if actions.needs_confirmation(clean) and not body.get("confirm"):
            self.send_json(HTTPStatus.OK, {
                "status": "confirm_required",
                "action": clean,
                "description": actions.describe(clean),
                "message": f"May I {actions.describe(clean)}?",
            })
            return

        try:
            result = actions.execute(clean)
        except actions.ActionError as e:
            self.send_json(HTTPStatus.OK, {
                "status": "error", "error": str(e), "action": clean,
            })
            return
        except Exception as e:
            self.send_json(HTTPStatus.OK, {
                "status": "error", "error": f"{type(e).__name__}: {e}", "action": clean,
            })
            return

        self.send_json(HTTPStatus.OK, {
            "status": "ok",
            "action": clean,
            "result": result,
            "message": result.get("message") or "Done, sir.",
        })

    def handle_transcribe(self):
        """Transcribe recorded audio locally with Whisper."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No audio received"})
            return
        if content_length > 25 * 1024 * 1024:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Audio too large (max 25 MB)"})
            return

        audio = self.rfile.read(content_length)
        suffix = self.headers.get('X-Audio-Suffix', '.webm')
        if not suffix.startswith('.'):
            suffix = '.webm'

        try:
            text = stt.transcribe(audio, suffix)
        except stt.STTUnavailable as e:
            self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(e)})
            return
        except Exception as e:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": f"{type(e).__name__}: {e}"
            })
            return

        self.send_json(HTTPStatus.OK, {"text": text})

    def handle_chat(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Empty request"})
            return

        try:
            body = json.loads(self.rfile.read(content_length).decode())
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        question = body.get("question", "").strip()
        session_id = body.get("session_id", "")

        if not question:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No question provided"})
            return

        # Get or create session
        if not session_id:
            session_id = str(uuid.uuid4())
        session = get_session(session_id)

        # Check if this is a boot request
        if question == "__BOOT__":
            print(f"DEBUG: Boot request received! question={repr(question)}", file=sys.stderr)
            self.handle_boot()
            return

        # "call me" is not a question about the notes. It is a request for
        # the telephone, and it rings with the standing brief: the date,
        # what is open on the desk, and the latest activity.
        if is_call_request(question):
            headline, notes = telephony.standing_brief()
            try:
                record = call_me(headline, notes)
            except telephony.TelephonyError as exc:
                answer = "I could not ring you, sir: %s" % exc
                record = {}
            else:
                answer = "I am ringing you now, sir."
            session["history"].append({"role": "user", "content": question})
            session["history"].append({"role": "assistant", "content": answer})
            self.send_json(HTTPStatus.OK, {
                "answer": answer,
                "nodes": [],
                "session_id": session_id,
                "is_note_question": False,
                "action": None,
                "call_id": record.get("call_id"),
            })
            return

        # Score notes
        top_ids = score_notes(question)
        context_notes = [n for n in NOTE_DATA if n["id"] in top_ids]

        # Determine if this is a note question or small talk
        is_note_question = len(top_ids) > 0 and not self._is_small_talk(question)

        # An action request is detected from the wording, not from the model.
        detected = detect_action_intent(question) if ACTIONS_ENABLED else None

        if detected is not None:
            # No note context needed - the model only supplies the line.
            answer = call_llm_action_line(question, detected)
            is_note_question = False
            top_ids = []
        elif is_note_question:
            # Call LLM with context
            answer = call_llm(question, context_notes, session["history"], is_boot=False)
        else:
            # Small talk - no context notes needed, just personality
            answer = call_llm(question, [], session["history"], is_boot=False)

        # Update history
        session["history"].append({"role": "user", "content": question})
        session["history"].append({"role": "assistant", "content": answer})

        # The brain may have asked for a machine action instead of prose.
        action_info = None
        if ACTIONS_ENABLED:
            if detected is not None:
                # Deterministic intent - the action is known, so no parsing.
                clean, error = actions.validate(detected)
                if error:
                    answer = f"[I would have done that, but it was refused: {error}]"
                else:
                    action_info = {
                        "action": clean,
                        "description": actions.describe(clean),
                        "status": ("confirm_required" if actions.needs_confirmation(clean)
                                   else "ready"),
                    }
            else:
                envelope = _parse_action(answer)
                if envelope:
                    clean, error = actions.validate(envelope["action"])
                    if error:
                        answer = f"[I would have done that, but it was refused: {error}]"
                    else:
                        action_info = {
                            "action": clean,
                            "description": actions.describe(clean),
                            "status": ("confirm_required" if actions.needs_confirmation(clean)
                                       else "ready"),
                        }
                        answer = envelope["say"] or f"Certainly, sir - {action_info['description']}."
                        # An action request is not a note question, even when the
                        # wording happens to overlap with note content.
                        is_note_question = False
                        top_ids = []

        # Respond
        self.send_json(HTTPStatus.OK, {
            "answer": answer,
            "nodes": top_ids if is_note_question else [],
            "session_id": session_id,
            "is_note_question": is_note_question,
            "action": action_info,
        })

    def _is_small_talk(self, question: str) -> bool:
        """Heuristic to detect small talk / jokes vs actual note questions."""
        q = question.lower().strip()
        # Common small talk patterns
        small_talk_patterns = [
            'hello', 'hi ', 'hey', 'good morning', 'good evening', 'good afternoon',
            'how are you', 'what\'s up', 'whats up', 'nice to meet',
            'thank you', 'thanks', 'bye', 'goodbye', 'see you',
            'joke', 'funny', 'laugh', 'riddle', 'who are you', 'what are you',
            'your name', 'jarvis', 'are you real', 'do you like', 'favorite',
            'weather', 'time', 'date', 'today', 'tomorrow',
        ]
        # Check if question is very short and matches small talk
        if len(q) < 50 and any(p in q for p in small_talk_patterns):
            return True
        # Questions that are clearly about the notes (contain business terms)
        note_indicators = [
            'roast', 'coffee', 'bean', 'subscription', 'signature', 'farm', 'premium',
            'marcus', 'lena', 'ethiopia', 'colombia', 'guatemala', 'peru', 'costa rica',
            'yirgacheffe', 'huila', 'antigua', 'cupping', 'quality', 'inventory',
            'equipment', 'packaging', 'barista', 'event', 'brand', 'email', 'instagram',
            'financial', 'revenue', 'profit', 'team', 'staff', 'manager', 'director',
        ]
        if any(ind in q for ind in note_indicators):
            return False
        # Default: if we scored notes, it's probably a note question
        return False

    def handle_boot(self):
        """Return boot greeting with note count."""
        self.send_json(HTTPStatus.OK, {
            "answer": f"Good evening, sir. {len(NOTE_DATA)} notes indexed, all present and accounted for.",
            "nodes": [],
            "session_id": str(uuid.uuid4()),
            "is_note_question": False,
        })

    def handle_remember(self):
        """Handle 'remember that...' requests - create a new capture note."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Empty request"})
            return

        try:
            body = json.loads(self.rfile.read(content_length).decode())
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        statement = body.get("statement", "").strip()
        if not statement:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No statement provided"})
            return

        # Generate title from first few words
        words = statement.split()
        title_words = words[:6]  # First 6 words
        title = " ".join(title_words).rstrip(".,;:").title()
        if len(title) > 60:
            title = title[:57] + "..."

        # Create filename
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-')
        filename = f"{timestamp}-{safe_title}.md"

        # Create note content
        note_content = f"# {title}\n\nCaptured: {time.strftime('%Y-%m-%d %H:%M')}\n\n{statement}\n"

        # Write to captures folder
        captures_dir = NOTES_DIR / "captures"
        captures_dir.mkdir(exist_ok=True)
        filepath = captures_dir / filename
        filepath.write_text(note_content, encoding="utf-8")

        # Add to NOTE_DATA
        new_id = len(NOTE_DATA)
        clean = re.sub(r'^---[\s\S]*?---', '', note_content)
        clean = re.sub(r'^#+\s.*$', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'\[\[([^\]]+)\]\]', r'\1', clean)
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
        clean = re.sub(r'```[\s\S]*?```', '', clean)
        clean = re.sub(r'`([^`]+)`', r'\1', clean)
        clean = re.sub(r'\|.*\|', '', clean)
        note_words = set(re.findall(r'\b\w{3,}\b', clean.lower()))
        title_words_set = set(re.findall(r'\b\w{3,}\b', title.lower()))

        NOTE_DATA.append({
            "id": new_id,
            "title": title,
            "content": note_content,
            "words": note_words,
            "title_words": title_words_set,
        })

        # Find most related existing node for spawn position
        spawn_node_id = 0
        if len(NOTE_DATA) > 1:
            best_score = -1
            for note in NOTE_DATA[:-1]:  # Don't compare to self
                score = len(note_words & note["words"]) + len(title_words_set & note["title_words"]) * 3
                if score > best_score:
                    best_score = score
                    spawn_node_id = note["id"]

        # Return new node info for live addition
        self.send_json(HTTPStatus.OK, {
            "id": new_id,
            "title": title,
            "excerpt": statement[:700],
            "group": "captures",
            "spawn_node_id": spawn_node_id,
            "answer": f"Logged, sir. \"{title}\" filed under captures.",
            "is_note_question": False,
        })

    def send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ─── The telephone ───────────────────────────────────────────────────────────
# Jarvis can ring you. Retell is the provider; telephony.py holds the plumbing
# and the rules for what the phone is allowed to say.
#
# The agent is handed the headline and the notes IN THE PROMPT, so it can only
# ever answer from them. The call is then watched by polling Retell, and when
# it ends the transcript becomes one spoken line for the desk.

DESK_LINE = {"line": None, "call_id": None, "at": None}
DESK_LOCK = threading.Lock()

# "call me", "ring me", "phone me" - a request for the telephone, not a
# question about the notes.
CALL_REQUEST = re.compile(
    r"\b(call me|ring me|phone me|call my phone|give me a call)\b",
    re.IGNORECASE)


def is_call_request(question):
    """True when the question is actually a request to be rung."""
    text = str(question or "").strip()
    if not text:
        return False
    return bool(CALL_REQUEST.search(text))


def set_desk_line(line, call_id=None):
    """Put one line on the desk."""
    with DESK_LOCK:
        DESK_LINE["line"] = line
        DESK_LINE["call_id"] = call_id
        DESK_LINE["at"] = time.time()


def desk_line():
    """What is on the desk now."""
    with DESK_LOCK:
        return dict(DESK_LINE)


def call_me(headline, notes):
    """Render this call's script, push it to the agent, and ring the cell.

    The headline and the notes are written into the prompt itself, so the
    agent has nothing else to go on. Returns the call record; raises
    telephony.TelephonyError if the phone is not set up, or if Retell
    refuses.
    """
    missing = telephony.missing_pieces()
    if missing:
        raise telephony.TelephonyError(
            "the phone is not set up yet (%s); run setup_phone.py, sir"
            % ", ".join(missing))
    script = telephony.render_prompt(headline, notes)
    telephony.update_llm(telephony.llm_id(), script)
    record = telephony.create_call(telephony.agent_id())
    call_id = record.get("call_id")
    watcher = threading.Thread(target=watch_call, args=(call_id,), daemon=True)
    watcher.start()
    return record


def watch_call(call_id):
    """Wait for the call to end, then put one spoken line on the desk."""
    try:
        record = telephony.wait_for_call(call_id)
    except telephony.TelephonyError as exc:
        set_desk_line("The call could not be watched, sir: %s" % exc, call_id)
        return
    transcript = telephony.call_summary(record)
    if not transcript:
        set_desk_line("The call ended with nothing said, sir.", call_id)
        return
    try:
        summary = call_llm(
            "Summarise this telephone call in ONE short spoken line for the "
            "desk. No preamble, no quotation marks, no dashes. Here is the "
            "transcript:\n\n%s" % transcript,
            [], [], is_boot=False)
    except Exception as exc:
        summary = "The call is over, sir. %s" % exc
    set_desk_line(telephony.speakable(str(summary).strip()), call_id)


def write_pid_file():
    """Remember which process is serving, so that a restart can find it.

    The port table is not enough: Windows lets a second process bind the
    same port, and then the old process keeps answering while the restart
    believes it has worked. The pid file is written by the process itself,
    so it names the one that is really serving.
    """
    try:
        (PROJECT_ROOT / "server.pid").write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def main():
    write_pid_file()
    if not VIEWER_DIR.exists():
        print(f"Viewer directory not found: {VIEWER_DIR}", file=sys.stderr)
        sys.exit(1)

    required = ['index.html', 'graph-data.js']
    for f in required:
        if not (VIEWER_DIR / f).exists():
            print(f"Missing required file: {VIEWER_DIR / f}", file=sys.stderr)
            sys.exit(1)

    os.chdir(VIEWER_DIR)

    print(f"Knowledge Galaxy server running at http://localhost:{PORT}")
    print(f"Serving: {VIEWER_DIR}")
    print(f"Config: {CONFIG_FILE}")
    if PROVIDER == "ollama":
        chain = " -> ".join(f"{m['name']}" for m in OLLAMA_MODELS)
        print(f"Brain: Ollama at {OLLAMA_HOST}")
        print(f"  model chain: {chain}")
    else:
        print(f"Brain: {PROVIDER} model {MODEL}")
    print(f"Actions: {'enabled' if ACTIONS_ENABLED else 'disabled'}")
    print("Press Ctrl+C to stop")

    # ThreadingHTTPServer, not plain TCPServer: a single slow LLM call must not
    # block every other request (a hung chat used to freeze static files too).
    # Bind to loopback only: Jarvis can drive this machine, so it must not be
    # reachable from the network.
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), ViewerHandler) as httpd:
        httpd.daemon_threads = True
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            httpd.shutdown()


if __name__ == "__main__":
    main()