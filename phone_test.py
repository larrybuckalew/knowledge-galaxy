"""The phone, proved without a Retell account.

A stub Retell API stands in for the real one, so the whole path can be
exercised: the script is rendered with this call's headline and notes, it is
pushed to the agent, the cell is dialled, the call is watched by POLLING, and
when it ends there is exactly one spoken line on the desk.

    python phone_test.py

Nothing here touches config.json or the network. The accessors are stubbed, so
no key is read and none is written.
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\larry\my-jarvis")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import telephony  # noqa: E402
import server  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s %s" % (label, detail))
        FAILURES.append(label)


# ─── the stub Retell ────────────────────────────────────────────────────────

CALLS = {"get_call": 0, "prompt": None, "tools": None, "placed": None,
         "voices": 0, "agent": None}


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _read(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/list-voices":
            CALLS["voices"] += 1
            self._send({"voices": [
                {"voice_id": "voice_us", "voice_name": "American Warm"},
                {"voice_id": "voice_uk", "voice_name": "British Gentleman"},
            ]})
            return
        if self.path.startswith("/v2/get-call/"):
            CALLS["get_call"] += 1
            if CALLS["get_call"] < 3:
                self._send({"call_id": "call_test_1", "status": "in-progress",
                            "transcript": []})
                return
            self._send({
                "call_id": "call_test_1", "status": "completed",
                "transcript": [
                    {"content": "What is the revenue?", "role": "user"},
                    {"content": "Two point eight four million dollars, sir.",
                     "role": "agent"},
                ],
            })
            return
        self._send({"error": "no such route"}, 404)

    def do_POST(self):
        body = self._read()
        if self.path == "/create-retell-llm":
            CALLS["prompt"] = body.get("general_prompt")
            CALLS["tools"] = body.get("general_tools")
            self._send({"llm_id": "llm_test_1"})
            return
        if self.path == "/create-agent":
            CALLS["agent"] = body
            self._send({"agent_id": "agent_test_1"})
            return
        if self.path == "/v2/create-phone-call":
            CALLS["placed"] = body
            self._send({"call_id": "call_test_1"})
            return
        self._send({"error": "no such route"}, 404)

    def do_PATCH(self):
        body = self._read()
        if self.path.startswith("/update-retell-llm/"):
            CALLS["prompt"] = body.get("general_prompt")
            self._send({"llm_id": "llm_test_1"})
            return
        self._send({"error": "no such route"}, 404)


def start_stub():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


# ─── the stubs for the config accessors ─────────────────────────────────────

def stub_accessors():
    telephony.api_key = lambda: "retell_test_key"
    telephony.from_number = lambda: "+15550101234"
    telephony.callback_number = lambda: "+15559876543"
    telephony.agent_id = lambda: "agent_test_1"
    telephony.llm_id = lambda: "llm_test_1"
    telephony.voice_id = lambda: "voice_uk"


def main():
    httpd, base = start_stub()
    telephony.BASE_URL = base
    stub_accessors()

    print("speakable:")
    check("money reads as words",
          telephony.speakable("$1,500") == "1,500 dollars",
          telephony.speakable("$1,500"))
    check("millions read as words",
          telephony.speakable("$2.84M") == "2.84 million dollars",
          telephony.speakable("$2.84M"))
    check("cents read as words",
          telephony.speakable("$0.50") == "50 cents",
          telephony.speakable("$0.50"))
    check("percent read as a word",
          telephony.speakable("35%") == "35 percent",
          telephony.speakable("35%"))
    check("phone numbers read in groups",
          telephony.speakable("+1 555 123 4567") == "1, 555, 123, 4567",
          telephony.speakable("+1 555 123 4567"))
    check("bold and symbols are gone",
          telephony.speakable("**Revenue: $2.84M**") == "Revenue: 2.84 million dollars",
          telephony.speakable("**Revenue: $2.84M**"))
    check("no stray asterisk survives",
          "*" not in telephony.speakable("a * b"),
          telephony.speakable("a * b"))

    print("script:")
    prompt = telephony.render_prompt("The headline is here.", "The note is here.")
    check("the headline is in the prompt", "The headline is here." in prompt)
    check("the notes are in the prompt", "The note is here." in prompt)

    telephony.create_llm(prompt)
    tools = CALLS["tools"] or []
    check("the agent is given the end_call tool",
          any(t.get("type") == "end_call" for t in tools), str(tools))
    check("the tool is named end_call",
          any(t.get("name") == "end_call" for t in tools), str(tools))

    print("brief:")
    headline, notes = telephony.standing_brief()
    check("the brief names a day of the week",
          any(day in headline for day in
              ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday")), headline)
    check("the brief has notes", bool(notes.strip()))
    check("the brief mentions the desk or the latest",
          "desk" in notes.lower() or "latest" in notes.lower(), notes)

    print("the call:")
    check("the request is recognised", server.is_call_request("call me"))
    check("a question about notes is not a call request",
          not server.is_call_request("what is our revenue?"))

    # The summary of the transcript is the brain's job, not the phone's. It is
    # stubbed here so this file proves the phone and never depends on a
    # provider being awake.
    server.call_llm = (
        lambda question, context_notes, history, is_boot=False:
        "Revenue was two point eight four million dollars.")

    server.call_me("The revenue is two point eight four million dollars.",
                   "Revenue is $2.84M this quarter.")

    check("the agent was dialled", CALLS["placed"] is not None)
    placed = CALLS["placed"] or {}
    check("it rings the cell", placed.get("to_number") == "+15559876543", str(placed))
    check("it rings from our number", placed.get("from_number") == "+15550101234", str(placed))
    check("the agent is the one we set up",
          placed.get("agent_id") == "agent_test_1", str(placed))

    pushed = CALLS["prompt"] or ""
    check("this call's headline was pushed to the agent",
          "two point eight four million dollars" in pushed.lower(), pushed[:200])
    check("this call's notes were pushed to the agent",
          "2.84 million dollars" in pushed, pushed[:200])

    deadline = time.time() + 20
    line = ""
    while time.time() < deadline:
        line = (server.desk_line().get("line") or "")
        if line:
            break
        time.sleep(0.3)
    check("the call was watched by polling",
          CALLS["get_call"] >= 3, "polls=%s" % CALLS["get_call"])
    check("there is one line on the desk", bool(line), "line=%r" % line)
    check("the desk line says the call ended",
          "revenue" in line.lower() or "call" in line.lower(), line)

    httpd.shutdown()
    print("\n%d checks, %d failed" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        print("failed:", ", ".join(FAILURES))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
