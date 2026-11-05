"""Set up the phone.

One command. It creates the calling agent through the Retell API, with the
end_call tool the agent needs to hang up properly, and writes the agent's id
into config.json.

Running it twice never makes a second agent: if config.json already holds an
agent id and Retell still knows it, that agent is reused. --dry shows what
would happen and touches nothing. With no key it stops and says where to get
one.

    python setup_phone.py --dry
    python setup_phone.py

The key, the number to ring from and the number to ring go in config.json,
like this:

    "telephony": {
        "api_key": "retell_...",
        "from": "+1 555 010 1234",
        "callback": "+1 555 987 6543"
    }
"""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import telephony  # noqa: E402

NO_KEY = ("No Retell API key yet, sir - make a free account at retellai.com, "
          "copy the key out of the dashboard, and put it in config.json under "
          "telephony, then run me again.")

DEFAULT_HEADLINE = "Jarvis here, sir. Nothing in particular, as yet."
DEFAULT_NOTES = ("There are no notes loaded for this call. Say that the desk is "
                 "empty and offer to bring the real notes.")


def read_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_config_atomically(config):
    """Write config.json without ever leaving it half-written.

    A crash halfway through a write would take the key with it, so the new
    file is written beside the old one and then moved into place, which is
    atomic on Windows and on everything else.
    """
    text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(dir=str(PROJECT_ROOT), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, CONFIG_FILE)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def pick_voice():
    """A voice for the agent, preferring British English if Retell offers one."""
    voices = telephony.list_voices()
    if not voices:
        raise telephony.TelephonyError("Retell offered no voices at all")
    preferred = None
    for voice in voices:
        label = (voice.get("voice_name") or voice.get("name") or "").lower()
        if "british" in label or "uk" in label or "england" in label:
            preferred = voice
            break
    chosen = preferred or voices[0]
    return chosen.get("voice_id") or chosen.get("agent_id") or chosen.get("id")


def main(argv):
    dry = "--dry" in argv
    missing = telephony.missing_pieces()
    if "api_key" in missing:
        print(NO_KEY)
        return 0

    config = read_config()
    block = config.setdefault("telephony", {})
    existing = str(block.get("agent_id") or "").strip()

    if existing:
        try:
            telephony.get_agent(existing)
            print("The agent is already set up (%s), sir - I shall not make "
                  "another one." % existing)
            if not block.get("voice_id"):
                block["voice_id"] = telephony.voice_id() or pick_voice()
                write_config_atomically(config)
            return 0
        except telephony.TelephonyError as exc:
            print("The agent in config.json (%s) is not answering any more "
                  "(%s), so I shall make a new one." % (existing, exc))

    voice = str(block.get("voice_id") or "").strip() or pick_voice()
    prompt = telephony.render_prompt(DEFAULT_HEADLINE, DEFAULT_NOTES)

    if dry:
        print("Dry run. I would:")
        print("  - use the voice %s" % voice)
        print("  - create a response engine with the end_call tool")
        print("  - create an agent called %s" % telephony.AGENT_NAME)
        print("  - write its ids into config.json under telephony")
        print("  - ring %s from %s" % (telephony.callback_number() or "<your cell>",
                                        telephony.from_number() or "<your number>"))
        print("Nothing has been created.")
        return 0

    llm = telephony.create_llm(prompt)
    agent = telephony.create_agent(llm["llm_id"], voice)
    block["llm_id"] = llm["llm_id"]
    block["agent_id"] = agent["agent_id"]
    block["voice_id"] = voice
    write_config_atomically(config)
    print("The phone is ready, sir. Agent %s, voice %s."
          % (agent["agent_id"], voice))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except telephony.TelephonyError as exc:
        print("That did not work, sir: %s" % exc)
        raise SystemExit(1)
