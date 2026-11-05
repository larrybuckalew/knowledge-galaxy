#!/usr/bin/env python3
"""
brain_test.py - the safety battery for the brain resolver.

The rule under test: a spoken request is built into a candidate model id and
checked against the explicit set of ids that really exist. If it is not there,
the request is REFUSED. It is never quietly downgraded to the nearest match -
"opus 5.5" must not become "opus 5", and "glm 5.3" must not become "glm 5.3
flash" when the words are not there.

Run it after adding a model to MODELS in server.py:

    python brain_test.py
"""
import importlib.util
from pathlib import Path

SERVER = Path(__file__).resolve().parent / "server.py"
spec = importlib.util.spec_from_file_location("kg", str(SERVER))
kg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kg)

# (phrase, expected action, expected id or error)
CASES = [
    # ── Claude, direct to Anthropic ────────────────────────────────────
    ("try on Opus 5",                "swap", "claude-opus-5"),
    ("switch to Fable 5.1",          "swap", ("claude-fable-5-1",
                                               "opencode/claude-fable-5-1")),
    ("go back to your normal brain", "reset", None),
    ("opus 5.5",                     "swap", ("claude-opus-5-5",
                                               "opencode/claude-opus-5-5")),
    ("opus5.5",                      "swap", ("claude-opus-5-5",
                                               "opencode/claude-opus-5-5")),
    ("opus5",                        "swap", "claude-opus-5"),
    ("opus 5.1",                     "error", "unknown_model"),
    ("ask for opus 6",               "error", "unknown_model"),
    ("ask for opus 5.5",             "swap", ("claude-opus-5-5",
                                               "opencode/claude-opus-5-5")),
    ("try on haiku",                 "swap", ("claude-haiku-4-5",
                                               "opencode/claude-haiku-4-5")),
    ("switch to sonnet 5",           "swap", ("claude-sonnet-5",
                                               "opencode/claude-sonnet-5")),
    ("opus",                         "error", "ambiguous"),

    # ── OpenRouter, zero cost ──────────────────────────────────────────
    ("switch to crouton",            "swap", "stealth/crouton-alpha"),
    ("switch to nemotron 3",         "swap", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("switch to gemma 4",            "swap", "google/gemma-4-31b-it:free"),
    ("switch to xing 4",             "swap", "xingchen-agi/xing4.0-29b-a4b:free"),
    ("switch to astra",              "swap", "openai/gpt-6-astra"),

    # ── apinex.bond, zero cost ─────────────────────────────────────────
    ("switch to glm 5.3",            "swap", "free/glm-5.3"),
    ("switch to glm 5.3 flash",      "swap", "free/glm-5.3-flash"),
    ("switch to qwen 3.8 max",       "swap", "free/qwen-3.8-max"),
    ("switch to kimi k3",            "swap", "free/kimi-k3"),
    ("switch to gemini 3.8 flash",   "swap", "free/gemini-3.8-flash"),
    ("switch to deepseek 4.1 flash", "swap", "free/deepseek-v4.1-flash"),
    ("switch to deepseek v4 flash",  "swap", "free/deepseek-v4-flash-0731"),
    ("switch to minimax m3.1 flash", "swap", "free/minimax-m3.1-flash"),
    ("switch to mimo 2.6 flash",     "swap", "free/mimo-v2.6-flash"),
    ("switch to gpt 6 luna",         "swap", "free/gpt-6-luna"),
    ("switch to gpt 6",              "swap", "free/gpt-6-luna"),
    ("switch to muse spark",         "swap", "free/muse-spark-1.3"),
    ("switch to hy 4",               "swap", "free/hy4"),

    # ── together.ai, zero cost ─────────────────────────────────────────
    ("switch to llama 3.3",          "swap", "meta-llama/Llama-3.3-70B-Instruct"),
    ("switch to qwen 2.5 72b",       "swap", "Qwen/Qwen2.5-72B"),
    ("switch to gemma 3",            "swap", "google/gemma-3-27b-it"),

    # ── OpenCode Zen ───────────────────────────────────────────────────
    ("switch to zen opus 5.5",       "swap", "opencode/claude-opus-5-5"),
    ("switch to zen sonnet 5",       "swap", "opencode/claude-sonnet-5"),
    ("switch to zen fable 5.1",      "swap", "opencode/claude-fable-5-1"),
    ("switch to zen haiku 4.5",      "swap", "opencode/claude-haiku-4-5"),
    ("switch to zen astra",          "swap", "gpt-6-astra"),
    ("switch to zen glm 5.3",        "swap", "glm-5.3"),
    ("switch to zen kimi k3",        "swap", "kimi-k3"),
    ("switch to zen qwen 3.8 max",   "swap", "qwen3.8-max"),
    ("switch to zen crouton",        "swap", "crouton-alpha-free"),
    ("switch to zen pickle",         "swap", "big-pickle"),
    ("switch to zen pulse",          "swap", "pulse-alpha-free"),
    ("ask for zen opus 6",           "error", "unknown_model"),
    ("ask for zen nonsense",         "error", "unknown_model"),
    # With no Anthropic key, Opus 5.5 is answered by whichever provider has
    # one - today that is OpenCode Zen. With a key it would be Anthropic, so
    # either answer is correct.
    ("try on Opus 5.5",              "swap", ("claude-opus-5-5",
                                               "opencode/claude-opus-5-5")),

    # ── NVIDIA and Vercel ────────────────────────────────────────────────
    ("switch to nvidia 3",            "swap", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("switch to nvidia 3.5",          "swap", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    ("switch to nvidia 4",            "swap", "google/gemma-4-31b-it"),
    ("switch to nvidia 4.1",          "swap", "mistralai/mistral-large-4-1t-a52b"),
    ("switch to vercel opus 5.5",     "swap", "vercel/anthropic-claude-opus-5.5"),
    ("switch to vercel sonnet 5",     "swap", "vercel/anthropic-claude-sonnet-5"),
    ("ask for nvidia 9",              "error", "unknown_model"),

    # ── Refusals: a version that is not in the set ─────────────────────
    ("ask for gpt 7",                "error", "unknown_model"),
    ("ask for glm 4",                "error", "unknown_model"),
    ("ask for kimi 4",               "error", "unknown_model"),
    ("ask for claude opus 4.6",      "error", "unknown_model"),
    ("ask for gemini 3.1 pro",       "error", "unknown_model"),
    ("switch to kimi 2.8",           "error", "unknown_model"),
    ("switch to qwen 3.8",           "error", "unknown_model"),

    # ── Not brain requests: ordinary questions stay ordinary ───────────
    ("what is the cupping protocol", "none", None),
    ("what did we decide about sonnet pricing", "none", None),
    ("is gpt better than opus 5",    "none", None),
    ("good morning",                 "none", None),
    ("tell me about the signature series", "none", None),
    ("what is the churn rate",       "none", None),
]

# (model id, expected chip label)
LABELS = [
    ("claude-opus-5-5",    "OPUS 5.5"),
    ("claude-opus5-5",     "OPUS 5.5"),
    ("claude-opus-5",      "OPUS 5"),
    ("claude-haiku-4-5",   "HAIKU 4.5"),
    ("claude-fable-5-1",   "FABLE 5.1"),
    ("claude-sonnet-5",    "SONNET 5"),
    ("openai/gpt-6-astra", "ASTRA"),
    ("stealth/crouton-alpha", "CROUTON"),
    ("free/glm-5.3",      "GLM 5.3"),
    ("free/qwen-3.8-max", "QWEN 3.8 MAX"),
    ("free/kimi-k3",      "KIMI K3"),
    ("free/gemini-3.8-flash", "GEMINI 3.8 FLASH"),
    ("free/muse-spark-1.3", "MUSE SPARK"),
    ("free/hy4",          "HY 4"),
    ("meta-llama/Llama-3.3-70B-Instruct", "LLAMA 3.3"),
    ("Qwen/Qwen2.5-72B",  "QWEN 2.5 72B"),
    ("opencode/claude-opus-5-5", "ZEN OPUS 5.5"),
    ("opencode/claude-sonnet-5", "ZEN SONNET 5"),
    ("gpt-6-astra",       "ZEN ASTRA"),
    ("crouton-alpha-free", "ZEN CROUTON"),
    ("big-pickle",        "ZEN PICKLE"),
]

fails = 0

print("RESOLVER")
for phrase, want_action, want in CASES:
    result = kg.resolve_model_request(phrase)
    action = result["action"]
    got = result.get("id") or result.get("error") or ""
    if isinstance(want, tuple):
        ok = action == want_action and got in want
    else:
        ok = action == want_action and (want is None or got == want)
    if action == "error" and want_action == "error":
        ok = ok and result.get("error") == want
    if not ok:
        fails += 1
    print("  %-42s %-6s %-26s %s" % (
        repr(phrase)[:42], action, str(got)[:26], "ok" if ok else "FAIL"))

print("\nLABELS")
for model_id, want in LABELS:
    got = kg.model_label(model_id)
    ok = got == want
    if not ok:
        fails += 1
    print("  %-22s -> %-12s %s" % (model_id, got, "ok" if ok else "FAIL"))

print("\nBLOCKED PROVIDERS")
# A key is not a working route. The Vercel gateway takes the key and then
# refuses every request until a card is on file, so a swap onto one of its
# models has to be refused with that reason.
blocked_result = kg.apply_model_request("switch to vercel opus 5.5")
blocked_ok = (not blocked_result.get("ok")
              and blocked_result.get("error") == "provider_blocked")
if not blocked_ok:
    fails += 1
    print("  vercel route not refused: %r FAIL" % (blocked_result,))
else:
    print("  vercel refused: %s" % blocked_result["message"][:88])

print("\nBLOCKED MODELS")
# One model can be down while the rest of its provider is up - NVIDIA's
# nemotron 3 ultra stopped answering on this key while the other NVIDIA routes
# carried on. Such a model is refused with its own reason, and it is kept
# out of every fallback chain: a fallback that cannot answer only makes the
# user wait longer before the next route is tried.
for model_id, spec in kg.MODELS.items():
    reason = spec.get("blocked")
    if not reason:
        continue
    if not str(reason).strip():
        fails += 1
        print("  %-44s blocked without a reason FAIL" % model_id)
        continue
    result = kg.apply_model_request("switch to %s" % (spec.get("spoken") or model_id))
    refused = (not result.get("ok")
               and result.get("error") == "model_blocked"
               and str(reason)[:30] in str(result.get("message") or ""))
    if not refused:
        fails += 1
        print("  %-44s not refused with its reason: %r FAIL" % (model_id, result))
    else:
        print("  %-44s refused: %s" % (model_id, result["message"][:70]))
    for other_id, other_spec in kg.MODELS.items():
        if model_id in (other_spec.get("fallbacks") or []):
            fails += 1
            print("  %-44s is a fallback for %s FAIL" % (model_id, other_id))
    if kg.CURRENT_MODEL_ID == model_id:
        fails += 1
        print("  %-44s is the brain in place FAIL" % model_id)

print("\nREGISTRY")
# Every route must name a provider that exists and point at a real model.
for model_id, spec in kg.MODELS.items():
    provider = spec.get("provider")
    if provider not in ("anthropic",) and provider not in kg.PROVIDERS:
        fails += 1
        print("  %-44s unknown provider %r FAIL" % (model_id, provider))
    for fallback in spec.get("fallbacks", []):
        if fallback not in kg.MODELS:
            fails += 1
            print("  %-44s fallback %r not in registry FAIL" % (model_id, fallback))
    # The id we actually send must never be empty.
    if not kg.api_model_id(model_id):
        fails += 1
        print("  %-44s sends an empty model id FAIL" % model_id)
    # NVIDIA's own ids already carry a vendor prefix ("nvidia/...",
    # "z-ai/...", "google/..."), so the prefix rule must not touch them:
    # without an explicit api_id it would strip the first part and send a
    # name the endpoint has never heard of. This is the OpenCode bug in a
    # second costume.
    if provider == "nvidia" and not spec.get("api_id"):
        fails += 1
        print("  %-44s nvidia id needs an explicit api_id FAIL" % model_id)
print("  %d models, every provider and fallback known" % len(kg.MODELS))

print("\nKNOWN MODEL IDS:", sorted(kg.KNOWN_MODEL_IDS))
print("\n%s" % ("ALL PASSED" if fails == 0 else "%d FAILURES" % fails))
raise SystemExit(1 if fails else 0)
