"""The telephone.

Retell AI is the provider: one key, one number to ring from, one number to
ring. Nothing in here talks to the brain. The agent is given a script and a
set of notes, and it says what it is told and nothing else.

Everything the phone will say goes through speakable() first. A voice agent
reads "$1,500" as symbol soup and "+1 555 123 4567" as one enormous number,
and a stray asterisk is read aloud as "asterisk" rather than ignored.

The call is watched by POLLING, not by a webhook. A webhook is a door anyone
on the internet can knock on, and a forged "call ended" event would put a lie
on the desk.
"""

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
NOTES_DIR = PROJECT_ROOT / "notes"

BASE_URL = "https://api.retellai.com"
AGENT_NAME = "Jarvis"
LANGUAGE = "en-US"

# The statuses Retell reports once a call is over.
ENDED_STATUSES = {"completed", "failed", "no-answer", "busy", "canceled", "rejected"}

# The tool that ends the call. It is a general tool, so the model may call it
# at any point in the conversation.
END_CALL_TOOL = {
    "type": "end_call",
    "name": "end_call",
    "description": ("End the call. Say your short sign-off first, then call this "
                    "tool in the same breath."),
}

GREETING = "Good evening, sir. Jarvis here."


class TelephonyError(RuntimeError):
    """Retell refused, or could not be reached."""


# ─── configuration ──────────────────────────────────────────────────────────

def telephony_config():
    """The telephony block from config.json, or an empty dict."""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    block = config.get("telephony")
    return block if isinstance(block, dict) else {}


def api_key():
    return str(telephony_config().get("api_key") or "").strip()


def from_number():
    return str(telephony_config().get("from") or "").strip()


def callback_number():
    return str(telephony_config().get("callback") or "").strip()


def agent_id():
    return str(telephony_config().get("agent_id") or "").strip()


def llm_id():
    return str(telephony_config().get("llm_id") or "").strip()


def voice_id():
    return str(telephony_config().get("voice_id") or "").strip()


def missing_pieces():
    """What the phone still needs, as a list of names."""
    missing = []
    if not api_key():
        missing.append("api_key")
    if not from_number():
        missing.append("from")
    if not callback_number():
        missing.append("callback")
    if not agent_id():
        missing.append("agent_id")
    return missing


def ready():
    return not missing_pieces()


# ─── the API ────────────────────────────────────────────────────────────────

def request(method, path, body=None):
    """One call to Retell."""
    key = api_key()
    if not key:
        raise TelephonyError("there is no Retell API key in config.json")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    call = urllib.request.Request(BASE_URL + path, data=data, method=method)
    call.add_header("Authorization", "Bearer " + key)
    call.add_header("Content-Type", "application/json")
    call.add_header("Accept", "application/json")
    call.add_header("User-Agent", "Jarvis/1.0 (local; +http://127.0.0.1:4703)")
    try:
        with urllib.request.urlopen(call, timeout=60) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise TelephonyError("Retell refused %s %s: %s %s"
                             % (method, path, exc.code, detail[:300]))
    except Exception as exc:
        raise TelephonyError("could not reach Retell: %s" % exc)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise TelephonyError("Retell sent something that is not JSON: %s" % raw[:200])


def list_voices():
    """The voices Retell offers."""
    return request("GET", "/list-voices").get("voices") or []


def create_llm(prompt, greeting=GREETING):
    """Create the response engine that carries the prompt and the end_call tool."""
    return request("POST", "/create-retell-llm", {
        "start_speaker": "agent",
        "begin_message": greeting,
        "general_prompt": prompt,
        "general_tools": [END_CALL_TOOL],
    })


def update_llm(target_llm_id, prompt, greeting=GREETING):
    """Push a new script into the response engine."""
    return request("PATCH", "/update-retell-llm/" + target_llm_id, {
        "general_prompt": prompt,
        "begin_message": greeting,
    })


def create_agent(target_llm_id, target_voice_id):
    """Create the agent that will ring the number."""
    return request("POST", "/create-agent", {
        "agent_name": AGENT_NAME,
        "response_engine": {"type": "retell-llm", "llm_id": target_llm_id},
        "voice_id": target_voice_id,
        "language": LANGUAGE,
        "max_call_duration_ms": 15 * 60 * 1000,
        "end_call_after_silence_ms": 90 * 1000,
    })


def get_agent(target_agent_id):
    return request("GET", "/get-agent/" + target_agent_id)


def create_call(target_agent_id, to_value=None, from_value=None):
    """Dial the number."""
    return request("POST", "/v2/create-phone-call", {
        "agent_id": target_agent_id,
        "from_number": from_value or from_number(),
        "to_number": to_value or callback_number(),
    })


def get_call(target_call_id):
    return request("GET", "/v2/get-call/" + target_call_id)


# ─── speakable ──────────────────────────────────────────────────────────────

SCALES = {"k": "thousand", "m": "million", "b": "billion"}


def _phone_words(match):
    """A phone number, read in groups: 1, 555, 123, 4567.

    Eleven digits that begin with a 1 are a North American number: the 1 is
    the country code, and the rest reads as three, three, four. Anything else
    is grouped from the right in threes.
    """
    text = match.group(0)
    digits = re.sub(r"\D", "", text)
    if len(digits) < 10:
        return text
    if len(digits) == 11 and digits.startswith("1"):
        return "1, %s, %s, %s" % (digits[1:4], digits[4:7], digits[7:])
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return ", ".join(groups)


def _money_words(match):
    """$1,500 reads as 1,500 dollars; $2.84M reads as 2.84 million dollars."""
    amount = match.group(1)
    scale = (match.group(2) or "").lower()
    if scale:
        return "%s %s dollars" % (amount, SCALES[scale])
    whole, _, fraction = amount.partition(".")
    if not fraction:
        return "%s dollars" % whole
    cents = fraction.ljust(2, "0")[:2]
    if int(whole) == 0:
        return "%s cents" % cents
    if int(cents) == 0:
        return "%s dollars" % whole
    return "%s dollars and %s cents" % (whole, cents)


def speakable(text):
    """Text a voice agent can say out loud without stumbling.

    "$1,500" becomes "1,500 dollars", "35%" becomes "35 percent", a phone
    number is read in groups, and no stray symbol is left over to be read
    aloud as a word.
    """
    if not text:
        return ""
    out = str(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)          # bold
    out = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", out)      # links
    out = re.sub(r"\[\[([^\]]+)\]\]", r"\1", out)           # wiki links
    out = re.sub(r"[*_`~#>|]+", " ", out)                   # stray symbols
    out = re.sub(r"(?<![\w$])\+?[\d][\d\s().\-]{8,}\d(?![\w])", _phone_words, out)
    out = re.sub(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([KkMmBb])?", _money_words, out)
    out = re.sub(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*%", r"\1 percent", out)
    out = out.replace("&", " and ").replace("@", " at ")
    out = out.replace("+", " plus ").replace("=", " equals ")
    out = re.sub(r"[—–]", ", ", out)
    out = re.sub(r"[;\[\]{}<>\"'`]", " ", out)
    out = re.sub(r"\.\.\.+", ", ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


# ─── the script for one call ────────────────────────────────────────────────

def render_prompt(headline, notes, greeting=GREETING):
    """The script for THIS call, with the headline and the notes in it.

    The headline and the notes are written into the prompt text itself, so
    the agent cannot answer from anything else: there is nothing else in
    front of it.
    """
    return "\n".join([
        "You are Jarvis, a butler, speaking on the telephone to the person you called.",
        "",
        "HOW TO BEHAVE:",
        "- Greet them at pickup, then wait for them to speak.",
        "- The moment they speak, tell them the headline below, before anything else.",
        "- Then answer their questions using ONLY the notes below.",
        "- If a fact is not in the notes, say plainly that you do not know it.",
        "  Never invent a fact, and never guess a number.",
        "- Keep every answer to one or two sentences.",
        "- When they say goodbye, say one short sign-off and then call the",
        "  end_call tool in the same breath.",
        "",
        "THE HEADLINE:",
        speakable(headline),
        "",
        "THE NOTES - the only facts you may use:",
        speakable(notes),
    ])


# ─── the desk ───────────────────────────────────────────────────────────────

CAPTURE_STAMP = re.compile(r"(\d{8})-(\d{6})")


def _note_title(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return path.stem.replace("-", " ").strip()


def desk_items(limit=3):
    """What is open on the desk.

    Two kinds of thing and no others: the loose captures - quick notes nobody
    has filed into the graph yet - and the explicit next steps written into
    the notes themselves.
    """
    items = []
    captures = NOTES_DIR / "captures"
    if captures.exists():
        for path in sorted(captures.glob("*.md")):
            title = _note_title(path)
            if title:
                items.append(title)
    for path in sorted(NOTES_DIR.rglob("*.md")):
        if captures.exists() and captures in path.parents:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.lower().startswith("next:"):
                detail = line.split(":", 1)[1].strip()
                title = _note_title(path)
                if detail and title:
                    items.append("%s: %s" % (title, detail))
    return items[:limit]


def latest_activity():
    """What happened last.

    The captures are the activity log - quick notes taken as the day went on,
    each with the moment it was taken in its name - so the newest capture is
    the latest thing that happened. If there are no captures, the most
    recently edited note is.
    """
    captures = NOTES_DIR / "captures"
    newest = None
    if captures.exists():
        for path in captures.glob("*.md"):
            match = CAPTURE_STAMP.search(path.name)
            if not match:
                continue
            stamp = match.group(1) + match.group(2)
            if newest is None or stamp > newest[0]:
                newest = (stamp, path)
    if newest is not None:
        return _note_title(newest[1])
    edited = None
    for path in NOTES_DIR.rglob("*.md"):
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if edited is None or stamp > edited[0]:
            edited = (stamp, path)
    return _note_title(edited[1]) if edited else None


def standing_brief(now=None):
    """The short brief for a "call me" with nothing else specified.

    The date, what is open on the desk, and the latest activity - the three
    things worth hearing if you are on your way out of the door.
    """
    from datetime import datetime
    stamp = (now or datetime.now()).strftime("%A, %d %B %Y")
    items = desk_items()
    latest = latest_activity()

    parts = ["It is %s." % stamp]
    if items:
        parts.append("Open on your desk: %s." % "; ".join(items))
    else:
        parts.append("Nothing is open on the desk.")
    if latest:
        parts.append("The latest activity: %s." % latest)

    headline = "Jarvis here, sir. " + " ".join(parts)
    notes = "\n".join([
        "The date is %s." % stamp,
        "Open on the desk:",
    ] + (["- %s" % item for item in items] or ["- nothing"]) + [
        "The latest activity: %s" % (latest or "nothing recorded"),
    ])
    return headline, notes


# ─── watching the call ──────────────────────────────────────────────────────

def wait_for_call(target_call_id, interval=5, timeout=1800):
    """Poll Retell until the call is over, then return the final record.

    Polling, not a webhook. A webhook is a door anyone on the internet can
    knock on, and a forged "call ended" event would put a lie on the desk.
    """
    deadline = time.time() + timeout
    while True:
        record = get_call(target_call_id)
        status = str(record.get("status") or "").lower()
        if status in ENDED_STATUSES:
            return record
        if time.time() >= deadline:
            record["status"] = "timeout"
            return record
        time.sleep(interval)


def transcript_lines(record):
    """The transcript as plain lines: what was said, and by whom."""
    lines = []
    for entry in record.get("transcript") or []:
        content = str(entry.get("content") or "").strip()
        role = str(entry.get("role") or "").strip()
        if content:
            lines.append("%s: %s" % (role, content))
    return lines


def call_summary(record):
    """The raw material for the desk line: the transcript, cleaned for the ear."""
    lines = transcript_lines(record)
    if not lines:
        return ""
    return speakable(" ".join(lines))
