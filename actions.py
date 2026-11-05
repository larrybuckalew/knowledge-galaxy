"""Allowlisted local actions so Jarvis can actually drive this PC.

Safety model
------------
* The model never supplies a shell string. It picks a structured action from a
  fixed schema, and each action type maps to one reviewed implementation.
* File access is confined to ALLOWED_ROOTS; anything outside is refused.
* Actions that change the machine (launching apps, opening URLs, running
  commands) are returned as `confirm_required` and only execute when the
  caller explicitly confirms.
* `run_command` is further restricted to an allowlist of exact commands.
"""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
HOME = Path.home()

# ─── Allowlists ──────────────────────────────────────────────────────────

#: Directories Jarvis may read from.
ALLOWED_ROOTS = [
    HOME / "Documents",
    HOME / "Downloads",
    HOME / "Desktop",
    HOME / "Pictures",
    HOME / "Videos",
    HOME / "Music",
    PROJECT_ROOT,
]

#: app name -> candidate executables, tried in order.
APP_ALIASES = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "terminal": ["wt.exe", "powershell.exe", "cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "paint": ["mspaint.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "opera": ["opera.exe"],
    "opera gx": ["opera.exe"],
    "vscode": ["code.cmd", "Code.exe"],
    "visual studio code": ["code.cmd", "Code.exe"],
    "spotify": ["Spotify.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "outlook": ["outlook.exe"],
    "discord": ["Discord.exe"],
    "whatsapp": ["WhatsApp.exe"],
    "notion": ["Notion.exe"],
}

#: exact command -> argv. Only these may ever be run.
ALLOWED_COMMANDS = {
    "git status": ["git", "status"],
    "git log": ["git", "log"],
    "git branch": ["git", "branch"],
    "git diff": ["git", "diff"],
    "whoami": ["whoami"],
    "hostname": ["hostname"],
    "systeminfo": ["systeminfo"],
    "ipconfig": ["ipconfig"],
    "date": ["date"],
    "time": ["time"],
    "ver": ["ver"],
    "python --version": ["python", "--version"],
    "node --version": ["node", "--version"],
    "ollama list": ["ollama", "list"],
}

#: Actions that change the machine and therefore need explicit confirmation.
CONFIRM_REQUIRED = {"open_app", "open_path", "open_url", "run_command"}

#: Actions that only read. Safe to run without confirmation.
SAFE_ACTIONS = {"system_status", "list_dir", "read_file", "search_files"}

MAX_READ_BYTES = 200_000
MAX_LIST_ENTRIES = 300
MAX_SEARCH_RESULTS = 100


# ─── Helpers ─────────────────────────────────────────────────────────────

class ActionError(Exception):
    """Raised when an action is refused or fails."""


def _within_allowed_roots(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _resolve_path(raw: str) -> Path:
    """Expand and validate a user-supplied path against ALLOWED_ROOTS."""
    if not raw or not raw.strip():
        raise ActionError("No path given.")
    expanded = Path(os.path.expandvars(os.path.expanduser(raw.strip())))
    if not expanded.is_absolute():
        expanded = (HOME / expanded)
    if not _within_allowed_roots(expanded):
        roots = ", ".join(str(r) for r in ALLOWED_ROOTS)
        raise ActionError(
            f"Refused: '{raw}' is outside the folders Jarvis may read ({roots})."
        )
    return expanded


def resolve_app(name: str) -> str | None:
    """Find the executable for an app alias, or None if unknown."""
    if not name:
        return None
    key = name.strip().lower()
    candidates = APP_ALIASES.get(key, [])
    # Also allow a bare executable name that is already in the allowlist.
    if not candidates and key.endswith(".exe") and key[:-4] in APP_ALIASES:
        candidates = APP_ALIASES[key[:-4]]
    for exe in candidates:
        found = shutil.which(exe)
        if found:
            return found
    return None


def _launch(exe: str, args=None) -> None:
    if platform.system() == "Windows":
        os.startfile(exe) if not args else subprocess.Popen(
            [exe, *args], shell=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:  # pragma: no cover - this project targets Windows
        subprocess.Popen([exe, *(args or [])], stdout=subprocess.DEVNULL)


# ─── Actions ─────────────────────────────────────────────────────────────

def action_system_status(**_) -> dict:
    """Machine vitals: CPU load, RAM, disk, uptime."""
    return {
        "host": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_load_percent": _cpu_load(),
        "ram_used_gb": _ram_used_gb(),
        "ram_total_gb": _ram_total_gb(),
        "disk_free_gb": _disk_free_gb(),
        "uptime_hours": round((time.time() - os.statvfs.__self__ if False else 0), 1) if False else _uptime_hours(),
    }


def _cpu_load() -> float | None:
    try:
        import psutil
        return round(psutil.cpu_percent(interval=0.4), 1)
    except Exception:
        return None


def _ram_used_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().used / 1e9, 1)
    except Exception:
        return None


def _ram_total_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        return None


def _disk_free_gb() -> float | None:
    try:
        usage = shutil.disk_usage(str(HOME))
        return round(usage.free / 1e9, 1)
    except Exception:
        return None


def _uptime_hours() -> float | None:
    try:
        import psutil
        return round((time.time() - psutil.boot_time()) / 3600, 1)
    except Exception:
        return None


def action_list_dir(path: str = "", **_) -> dict:
    """List the contents of a directory."""
    target = _resolve_path(path) if path else (HOME / "Documents")
    if not target.is_dir():
        raise ActionError(f"'{target}' is not a folder.")
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:MAX_LIST_ENTRIES]:
        try:
            size = item.stat().st_size if item.is_file() else None
        except OSError:
            size = None
        entries.append({
            "name": item.name,
            "type": "folder" if item.is_dir() else "file",
            "size": size,
        })
    return {"path": str(target), "count": len(entries), "entries": entries}


def action_read_file(path: str = "", **_) -> dict:
    """Read a text file from an allowed folder."""
    target = _resolve_path(path)
    if not target.is_file():
        raise ActionError(f"'{target}' is not a file.")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise ActionError(f"'{target.name}' is {size} bytes; too large to read whole.")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ActionError(f"Could not read '{target.name}': {e}") from e
    return {"path": str(target), "size": size, "text": text}


def action_search_files(pattern: str = "", root: str = "", **_) -> dict:
    """Find files by glob pattern under an allowed folder."""
    if not pattern:
        raise ActionError("No search pattern given.")
    base = _resolve_path(root) if root else (HOME / "Documents")
    if not base.is_dir():
        raise ActionError(f"'{base}' is not a folder.")
    hits = []
    try:
        for p in base.rglob(pattern):
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
            hits.append(str(p))
    except OSError as e:
        raise ActionError(f"Search failed: {e}") from e
    return {"root": str(base), "pattern": pattern, "count": len(hits), "matches": hits}


def action_open_app(app: str = "", **_) -> dict:
    """Launch a desktop application."""
    exe = resolve_app(app)
    if not exe:
        known = ", ".join(sorted(APP_ALIASES))
        raise ActionError(f"Jarvis does not know how to open '{app}'. Known: {known}")
    _launch(exe)
    return {"app": app, "executable": exe, "message": f"Opened {app}, sir."}


def action_open_path(path: str = "", **_) -> dict:
    """Open a file or folder in Explorer."""
    target = _resolve_path(path)
    if not target.exists():
        raise ActionError(f"'{target}' does not exist.")
    if platform.system() == "Windows":
        os.startfile(str(target))
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", str(target)])
    return {"path": str(target), "message": f"Opened {target.name}, sir."}


def action_open_url(url: str = "", **_) -> dict:
    """Open an http(s) URL in the default browser."""
    if not url:
        raise ActionError("No URL given.")
    lowered = url.strip().lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ActionError("Only http and https URLs are permitted.")
    import webbrowser
    webbrowser.open(url)
    return {"url": url, "message": "Opening the link, sir."}


def action_run_command(command: str = "", **_) -> dict:
    """Run one of the allowlisted read-only commands."""
    key = " ".join(command.strip().split()).lower()
    argv = ALLOWED_COMMANDS.get(key)
    if argv is None:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        raise ActionError(f"'{command}' is not an allowed command. Allowed: {allowed}")
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=20,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired as e:
        raise ActionError(f"'{key}' timed out.") from e
    return {
        "command": key,
        "exit_code": proc.returncode,
        "output": (proc.stdout or proc.stderr or "").strip()[:4000],
    }


#: action type -> implementation
HANDLERS = {
    "system_status": action_system_status,
    "list_dir": action_list_dir,
    "read_file": action_read_file,
    "search_files": action_search_files,
    "open_app": action_open_app,
    "open_path": action_open_path,
    "open_url": action_open_url,
    "run_command": action_run_command,
}

#: Human-readable summary of what an action will do, for the confirm card.
DESCRIPTIONS = {
    "system_status": "read CPU, memory and disk status",
    "list_dir": "list the contents of a folder",
    "read_file": "read a text file",
    "search_files": "search for files by name",
    "open_app": "launch an application",
    "open_path": "open a file or folder",
    "open_url": "open a link in the browser",
    "run_command": "run a command",
}


def validate(action: dict) -> tuple[dict, str | None]:
    """Return (clean_action, error). Cleaned action is safe to execute."""
    if not isinstance(action, dict):
        return {}, "Action must be an object."
    atype = str(action.get("type", "")).strip().lower()
    if atype not in HANDLERS:
        return {}, (f"Unknown action '{atype}'. "
                    f"Available: {', '.join(sorted(HANDLERS))}")
    clean = {"type": atype}
    for key in ("app", "path", "url", "command", "pattern", "root"):
        if key in action and action[key] is not None:
            clean[key] = str(action[key])[:2000]
    return clean, None


def needs_confirmation(action: dict) -> bool:
    return action.get("type") in CONFIRM_REQUIRED


def describe(action: dict) -> str:
    """One-line human summary for the confirmation card."""
    atype = action.get("type", "")
    base = DESCRIPTIONS.get(atype, atype)
    detail = {
        "open_app": action.get("app"),
        "open_path": action.get("path"),
        "open_url": action.get("url"),
        "run_command": action.get("command"),
        "read_file": action.get("path"),
        "list_dir": action.get("path"),
        "search_files": action.get("pattern"),
    }.get(atype)
    return f"{base}: {detail}" if detail else base


def execute(action: dict) -> dict:
    """Run a validated action. Raises ActionError on refusal/failure."""
    handler = HANDLERS[action["type"]]
    return handler(**action)
