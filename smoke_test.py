"""Final end-to-end smoke test: STT, chat, actions, and the safety guards."""
import json
import os
import subprocess
import urllib.error
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
WAV = os.path.join(HERE, "_v.wav")
WEBM = os.path.join(HERE, "_v.webm")
ORIGIN = {"Origin": "http://localhost:4703", "Sec-Fetch-Site": "same-origin"}
BASE = "http://localhost:4703"


def post(path, payload=None, raw=None, ctype="application/json", headers=None):
    hdrs = dict(ORIGIN if headers is None else headers)
    if raw is not None:
        data = raw
        hdrs["Content-Type"] = ctype
    else:
        data = json.dumps(payload).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


ok = True


def check(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""), flush=True)


print("1. static page + graph data", flush=True)
s, body = get("/")
check("GET / serves the app", s == 200 and "Knowledge Galaxy" in body, f"HTTP {s}")
s, body = get("/graph-data.js")
check("graph-data.js served", s == 200 and "nodes" in body, f"HTTP {s}")

print("2. local speech-to-text", flush=True)
subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Add-Type -AssemblyName System.Speech; "
     "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
     f"$s.SetOutputToWaveFile('{WAV}'); $s.Speak('Jarvis, open the calculator'); $s.Dispose();"],
    capture_output=True, text=True)
subprocess.run(["ffmpeg", "-y", "-i", WAV, "-c:a", "libopus", "-b:a", "32k", WEBM], capture_output=True)
s, body = post("/transcribe", raw=open(WEBM, "rb").read(), ctype="application/octet-stream")
text = body.get("text", "")
check("transcribe returns the spoken words", "calculator" in text.lower(), repr(text))
os.remove(WAV)
os.remove(WEBM)

print("3. brain + action routing", flush=True)
s, body = post("/chat", {"question": "What is our signature series?", "session_id": "f1"})
check("note question answered", s == 200 and len(body.get("answer", "")) > 20 and body.get("is_note_question"),
      body.get("answer", "")[:60])
check("note question cites sources", len(body.get("nodes", [])) > 0, f"{len(body.get('nodes', []))} notes")

s, body = post("/chat", {"question": "Open the calculator for me", "session_id": "f2"})
act = body.get("action") or {}
inner = act.get("action") or {}
check("action request detected", inner.get("type") == "open_app", json.dumps(act))
check("action held for confirmation", act.get("status") == "confirm_required", act.get("status", ""))

print("4. safety guards", flush=True)
s, body = post("/act", {"action": {"type": "open_app", "app": "calculator"}})
check("unconfirmed action is not executed", body.get("status") == "confirm_required", body.get("message", ""))

s, body = post("/act", {"action": {"type": "read_file", "path": "C:/Windows/win.ini"}})
check("read outside allowed roots refused", "outside" in (body.get("error") or ""), (body.get("error") or "")[:60])

s, body = post("/act", {"action": {"type": "run_command", "command": "format c:"}, "confirm": True})
check("non-allowlisted command refused", body.get("status") == "error", (body.get("error") or "")[:60])

s, body = post("/act", {"action": {"type": "system_status"}})
check("system status returns vitals", bool(body.get("result", {}).get("ram_total_gb")),
      json.dumps(body.get("result", {}))[:90])

evil = {"Origin": "https://evil.example.com", "Sec-Fetch-Site": "cross-site"}
s, body = post("/act", {"action": {"type": "open_app", "app": "calculator"}, "confirm": True}, headers=evil)
check("cross-origin POST blocked", s == 403, f"HTTP {s}")

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"), flush=True)
