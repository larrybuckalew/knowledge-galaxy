#!/usr/bin/env python3
"""
server.py — Tiny stdlib web server for the Knowledge Galaxy viewer + chat brain.
Serves ONLY the viewer/ folder on port 4700. config.json stays in project root.
"""

import http.server
import socketserver
import os
import sys
import json
import re
import uuid
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http import HTTPStatus


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
API_KEY = CONFIG.get("api_key", "")
MODEL = CONFIG.get("model", "meta-llama/llama-3.1-8b-instruct:free")
PROVIDER = CONFIG.get("provider", "anthropic")  # "anthropic" or "openrouter"


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
        # Build messages with history
        messages = [{"role": "system", "content": system_prompt}]
        for h in history[-6:]:  # Keep last 6 exchanges
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": f"Context notes:\n{context}\n\nQuestion: {question}"})

    if PROVIDER == "openrouter":
        return call_openrouter(messages)
    else:
        return call_anthropic(messages)


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
        err_body = e.read().decode()
        return f"[API Error {e.code}: {err_body}]"
    except Exception as e:
        return f"[Error: {e}]"


# ─── Request handler ──────────────────────────────────────────────────────
class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.address_string()}] {format % args}\n")

    def end_headers(self):
        if self.path.endswith(('.js', '.css', '.html', '.json', '.png', '.jpg', '.svg', '.ico')):
            self.send_header('Cache-Control', 'public, max-age=3600')
        else:
            self.send_header('Cache-Control', 'no-cache')
        # CORS for local dev
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        # Block access to config.json and any file outside viewer/
        if self.path.startswith('/config.json') or '..' in Path(self.path.lstrip('/')).parts:
            self.send_error(403, "Forbidden")
            return
        super().do_GET()

    def do_POST(self):
        if self.path == '/chat':
            self.handle_chat()
        elif self.path == '/remember':
            self.handle_remember()
        else:
            self.send_error(404, "Not Found")

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

        # Score notes
        top_ids = score_notes(question)
        context_notes = [n for n in NOTE_DATA if n["id"] in top_ids]

        # Determine if this is a note question or small talk
        is_note_question = len(top_ids) > 0 and not self._is_small_talk(question)

        if is_note_question:
            # Call LLM with context
            answer = call_llm(question, context_notes, session["history"], is_boot=False)
        else:
            # Small talk - no context notes needed, just personality
            answer = call_llm(question, [], session["history"], is_boot=False)

        # Update history
        session["history"].append({"role": "user", "content": question})
        session["history"].append({"role": "assistant", "content": answer})

        # Respond
        self.send_json(HTTPStatus.OK, {
            "answer": answer,
            "nodes": top_ids if is_note_question else [],
            "session_id": session_id,
            "is_note_question": is_note_question,
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
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


def main():
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
    print(f"Model: {MODEL}")
    print("Press Ctrl+C to stop")

    with socketserver.TCPServer(("", PORT), ViewerHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            httpd.shutdown()


if __name__ == "__main__":
    main()