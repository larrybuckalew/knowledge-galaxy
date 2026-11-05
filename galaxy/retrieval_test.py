"""Standing proof that the galaxy points at the right note.

The scorer decides two things the whole product hangs off: which notes an
answer is built from, and which note the camera flies to. A wrong pick is a
provenance lie, so these expectations are pinned here.

Run:  python retrieval_test.py
"""

import importlib.util
import re
import sys

SPEC = importlib.util.spec_from_file_location(
    "srv", r"C:\Users\larry\knowledge-galaxy\server.py")
srv = importlib.util.module_from_spec(SPEC)
sys.argv = ["server.py"]
SPEC.loader.exec_module(srv)

TITLE = {n.id: n.title for n in srv.NOTES}


def short(note_id):
    # The notes name people with a dash: "Lena Kowalski — Founder/CEO".
    return re.split(r"\s*[\u2013\u2014-]\s*", TITLE[note_id])[0].strip()


# (question, expected source titles, expected number of sources or None)
CASES = [
    # A headline figure belongs to the note that reports it.
    ("What is our revenue?", ["Financials"], 1),
    ("What is our COGS?", ["Financials"], 1),
    ("What is our gross margin?", ["Financials"], 1),

    # A word only one note owns names that note.
    ("churn", ["Subscription Program"], 1),
    ("What is the churn rate and lifetime value?", ["Subscription Program"], None),
    ("What is the price of a subscription?", ["Subscription Program"], 1),

    # The verb of asking is not a topic.
    ("What did we decide about the subscription churn program?",
     ["Subscription Program"], 1),
    ("What did we decide last quarter?", [], 0),

    # A title is the note's own name.
    ("signature series", ["Signature Series"], 1),
    ("Who is the CEO?", ["Lena Kowalski"], None),
    ("Tell me about Cropster", ["Cropster"], 1),
    ("What is the cupping protocol?", ["Cupping Protocol"], 1),

    # Words match across their endings.
    ("How do we pack the coffee?", ["Packaging Team"], None),
    ("What is the roast profile?", ["Roasting Process"], None),
    ("Where do we source green coffee?", ["Green Coffee Inventory"], 1),

    # A passing mention is not a source.
    ("What events do we run?", ["Events"], 1),
    ("How do we run the Instagram account?", ["Instagram"], 1),
    ("What is our email marketing setup?", ["Email Marketing"], 1),
    ("How do we manage inventory?", ["Inventory Management"], None),
]

# Questions that must never drag a note into the answer.
SMALL_TALK = ["hello", "thanks!", "tell me a joke", "how are you?",
              "good morning", "who are you?", "what can you do"]

failures = []


def check(label, condition, detail):
    if condition:
        return
    failures.append(f"{label}: {detail}")


print("RETRIEVAL")
for question, expected, exact_count in CASES:
    picked = srv.select_source_notes(srv.score_notes(question))
    names = [short(i) for i in picked]

    check(question, names and names[0] == expected[0] if expected else not names,
          f"top source is {names[:1]}, expected {expected[:1]}")
    for want in expected:
        check(question, want in names, f"{want!r} missing from {names}")
    if exact_count is not None:
        check(question, len(picked) == exact_count,
              f"{len(picked)} sources, expected {exact_count}: {names}")
    print(f"  {question!r:<58} -> {names}")

print()
print("SMALL TALK")
for chatter in SMALL_TALK:
    small = srv.is_small_talk(chatter)
    sources = srv.select_source_notes(srv.score_notes(chatter))
    check(chatter, small, "not detected as small talk")
    check(chatter, not sources, f"pulled in {sources}")
    print(f"  {chatter!r:<24} small_talk={small} sources={sources}")

print()
print("NOTE IDS")
for note in srv.NOTES:
    check("ids", 0 <= note.id < len(srv.NOTES), f"id {note.id} out of range")
print(f"  {len(srv.NOTES)} notes, ids {min(n.id for n in srv.NOTES)}"
      f"..{max(n.id for n in srv.NOTES)}")

print()
if failures:
    print(f"FAILED ({len(failures)})")
    for line in failures:
        print("  -", line)
    sys.exit(1)

print("ALL PASSED")
