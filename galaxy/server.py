#!/usr/bin/env python3
"""
server.py - Tiny static server for the Knowledge Galaxy viewer plus a chat brain.

Serves ONLY the viewer/ folder, on 127.0.0.1:4700. config.json lives in the
project root and is never reachable from the browser.

The brain uses the official `anthropic` Python package. Model-specific rules
for Opus 5.5:

  * thinking is always on - never send a thinking-disabled setting
  * never force a tool choice
  * effort defaults to medium and is set per route via output_config
  * max_tokens covers the thinking AND the answer together, so chat gets at
    least 2000 and retries once with a bigger budget if the text comes back
    empty
"""

import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

import anthropic

# ═══════════════════════════════════════════════════════════════════════════
#  THE BUTLER - the entire character of this assistant lives in this block.
#
#  Rewrite the character here and nowhere else. Three pieces:
#
#    BOOT_GREETING  - the one short line shown when the page loads.
#    SYSTEM_NOTES   - used when the question really is about the notes.
#    SYSTEM_CASUAL  - used for small talk.
#
#  The house rules that come with the voice:
#    * "sir" is seasoning, not a garnish. A pinch, never in every sentence.
#    * One genuinely funny line beats three bland ones. If nothing funny is
#      available, be brief instead of forcing it.
#    * Never recite a note. It is already on the user's screen.
#    * Never invent a source, never pad, and never pass a merely related note
#      off as the answer.
#    * Small talk must not drag the camera around the graph.
# ═══════════════════════════════════════════════════════════════════════════

BOOT_GREETING = "Hello, sir."

SYSTEM_NOTES = (
    "You are the user's butler: dry, impeccably polite, British, with a "
    "razor wit.\n"
    "You answer questions about their notes and nothing else. Answer only "
    "from the notes provided; never add outside knowledge.\n"
    "\n"
    "How you answer:\n"
    "- Lead with ONE genuinely funny line, then give the facts. One good line "
    "beats three bland ones. If no funny line is available, do not force one - "
    "be brief instead.\n"
    "- Call the user \"sir\" occasionally - once or twice in an answer at most, "
    "never in every sentence. Overusing it is the difference between charming "
    "and grating.\n"
    "- Then the facts, in one or two sentences. Brevity is respect.\n"
    "- Never recite the note back; it is already on their screen. Give the "
    "facts, not the transcript.\n"
    "- If the notes do not cover the question, say so plainly and with a little "
    "dignity - \"The notes do not cover that, sir.\" Never invent a source, "
    "never pad, and never pass a merely related note off as the answer.\n"
    "- The notes below have already been chosen for you as the relevant ones. "
    "If the answer is in there, give it. Only say the notes do not cover it "
    "when you genuinely cannot find it.\n"
    "- Plain prose only. No lists, no headings, no emoji, no \"Great question\" "
    "preamble. Just the line and the facts."
)

SYSTEM_CASUAL = (
    "You are the user's butler: dry, impeccably polite, British, with a "
    "razor wit.\n"
    "Answer in one short sentence. Call the user \"sir\" at most once, and only "
    "if it lands.\n"
    "One witty line is plenty; never force one where there is nothing funny.\n"
    "Do not mention notes, files or citations unless the user asks about them, "
    "and do not steer the conversation towards them.\n"
    "Plain prose only. No lists, no headings, no emoji, no preamble."
)

PORT = 4700
PROJECT_ROOT = Path(__file__).resolve().parent
VIEWER_DIR = PROJECT_ROOT / "viewer"
NOTES_DIR = PROJECT_ROOT / "notes"
CONFIG_FILE = PROJECT_ROOT / "config.json"

PLACEHOLDER_KEY = "PUT-YOUR-KEY-HERE"

# The brain used when config.json does not name one. It has to be a route
# that works without an Anthropic key, because there may not be one.
DEFAULT_MODEL = "free/glm-5.3"

# ═══════════════════════════════════════════════════════════════════════════
#  THE BRAIN - every model this assistant is allowed to think with.
#
#  One dictionary. The real model id is the key; beside it live the spoken
#  name, the family, the version as it is spoken, the transport, and the
#  request quirks for that model.
#
#  THE RULE THAT MAKES THIS SAFE:
#  KNOWN_MODEL_IDS is the explicit set of ids that really exist. A spoken
#  request is built into a candidate id - the family plus the version read
#  immediately after the family word, glued forms included - and then checked
#  against that set. If it is not in there, the request is REFUSED and we say
#  what we do have.
#
#  Never fall back to the nearest match. "opus 5.5" must never quietly
#  become "opus 5" - an hour lost to testing the wrong model is far more
#  expensive than an honest error. An honest error is worth more than a
#  helpful guess, every single time.
#
#  A new model ships: add one entry here and it is available by voice.
# ═══════════════════════════════════════════════════════════════════════════

# How a route is asked about thinking. Not interchangeable:
#   "required" - the endpoint insists on thinking and REJECTS any attempt to
#                switch it off, so the only correct thing is to send nothing.
#   "off"      - thinking may be switched off, and on a free route it should
#                be: the thinking tokens are slow and mostly wasted.
#   "auto"     - the endpoint decides; send nothing and let it.
REASONING_REQUIRED = "required"
REASONING_OFF = "off"
REASONING_AUTO = "auto"
# NVIDIA speaks its own dialect: it 400s on "include_reasoning" and
# ignores "exclude", but it does honour {"reasoning": {"enabled": false}},
# which is the difference between an answer and the model's own notes.
REASONING_NVIDIA_OFF = "nvidia_off"

# ═══ THE PROVIDERS ═══
# Every provider except Anthropic speaks the same OpenAI-compatible
# /chat/completions dialect, so they all share one code path. One key each;
# every key lives in config.json in the project root and never reaches the
# browser.
PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "base_url_field": "openrouter_base_url",
        "key_field": "openrouter_api_key",
        "user_agent": None,
        "headers": {
            "HTTP-Referer": "http://127.0.0.1:%d" % PORT,
            "X-Title": "Knowledge Galaxy",
        },
    },
    "apinex": {
        "base_url": "https://apinex.bond/v1",
        "base_url_field": "apinex_base_url",
        "key_field": "apinex_api_key",
        "user_agent": None,
        "headers": {},
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "base_url_field": "together_base_url",
        "key_field": "together_api_key",
        # Cloudflare in front of Together answers urllib's own signature
        # with a 403 "browser signature banned". Any other User-Agent gets
        # through, so this one identifies itself honestly.
        "user_agent": "KnowledgeGalaxy/1.0 (local knowledge galaxy; +http://127.0.0.1:4700)",
        "headers": {},
    },
    "opencode": {
        "base_url": "https://opencode.ai/zen/v1",
        "base_url_field": "opencode_base_url",
        "key_field": "opencode_api_key",
        "user_agent": "KnowledgeGalaxy/1.0 (local knowledge galaxy; +http://127.0.0.1:4700)",
        "headers": {},
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "base_url_field": "nvidia_base_url",
        "key_field": "nvidia_api_key",
        "user_agent": "KnowledgeGalaxy/1.0 (local knowledge galaxy; +http://127.0.0.1:4700)",
        "headers": {},
        # The healthy NVIDIA routes answer in about a second; the
        # slowest of them, mistral-large, took seventeen. Two minutes
        # is patience enough.
        "timeout": 120,
    },
    "vercel": {
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "base_url_field": "vercel_base_url",
        "key_field": "vercel_api_key",
        "user_agent": "KnowledgeGalaxy/1.0 (local knowledge galaxy; +http://127.0.0.1:4700)",
        "headers": {},
        # The key is good; the account is not funded. The gateway answers
        # every request with "requires a valid credit card on file", so
        # these routes are refused with that reason rather than offered
        # as though they worked. Delete this line once a card is on file.
        "blocked": "the Vercel AI Gateway needs a credit card on file before it serves anything",
    },
}

MODELS = {
    # ── Claude, straight to the Anthropic API ────────────────────────────
    "claude-opus-5-5": {
        "spoken": "opus 5.5",
        "family": "opus",
        "version": "5.5",
        "provider": "anthropic",
        "effort": True,
    },
    "claude-opus-5": {
        "spoken": "opus 5",
        "family": "opus",
        "version": "5",
        "provider": "anthropic",
        "effort": True,
    },
    "claude-fable-5-1": {
        "spoken": "fable 5.1",
        "family": "fable",
        "version": "5.1",
        "provider": "anthropic",
        "effort": True,
    },
    "claude-sonnet-5": {
        "spoken": "sonnet 5",
        "family": "sonnet",
        "version": "5",
        "provider": "anthropic",
        "effort": True,
    },
    "claude-haiku-4-5": {
        "spoken": "haiku",
        "family": "haiku",
        "version": None,
        "provider": "anthropic",
        "effort": False,          # Haiku takes no effort setting
    },

    # ── OpenRouter ──────────────────────────────────────────────────────
    "openai/gpt-6-astra": {
        "spoken": "astra",
        "family": "astra",
        "version": None,
        "provider": "openrouter",
        "effort": False,          # OpenRouter models take no output_config
        "reasoning": REASONING_AUTO,
        "label": "ASTRA",
        "free": False,            # priced, not zero-cost
    },

    # ── OpenRouter, zero cost ───────────────────────────────────────────
    # Two pieces of arithmetic worth keeping in your head:
    #
    #   1. OpenRouter caps the daily free-model requests PER ACCOUNT, and
    #      that cap only applies to ids ending in ":free". A zero-priced id
    #      WITHOUT that suffix is not capped, and keeps working when the
    #      cap is spent. So the first route below is a zero-priced id.
    #
    #   2. A cap is per account, so a second ":free" route is no use as a
    #      fallback. The fallbacks therefore cross to a provider.
    "stealth/crouton-alpha": {
        "spoken": "crouton",
        "family": "crouton",
        "version": None,
        "provider": "openrouter",
        "effort": False,
        "reasoning": REASONING_REQUIRED,   # it insists on thinking
        "label": "CROUTON",
        "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "nvidia/nemotron-3-ultra-550b-a55b:free": {
        "spoken": "nemotron 3",
        "family": "nemotron",
        "version": "3",
        "provider": "openrouter",
        "effort": False,
        "reasoning": REASONING_OFF,
        "label": "NEMOTRON 3",
        "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "google/gemma-4-31b-it:free": {
        "spoken": "gemma 4",
        "family": "gemma",
        "version": "4",
        "provider": "openrouter",
        "effort": False,
        "reasoning": REASONING_OFF,
        "label": "GEMMA 4",
        "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "xingchen-agi/xing4.0-29b-a4b:free": {
        "spoken": "xing 4",
        "family": "xing",
        "version": "4",
        "provider": "openrouter",
        "effort": False,
        # Without this flag it puts its whole scratchpad in the answer.
        "reasoning": REASONING_OFF,
        "label": "XING 4",
        "free": True,
        # Deliberately no fallback: it is the flakiest route we have.
    },

    # ── apinex.bond, zero cost ──────────────────────────────────────────
    # Every id here carries the "free/" prefix the provider itself puts on
    # its zero-cost catalogue. It is not a promise: some of them still ask
    # for a subscription, and those are simply not in this list.
    "free/glm-5.3": {
        "spoken": "glm 5.3",
        "family": "glm",
        "version": "5.3",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "GLM 5.3",
        "free": True,
        "fallbacks": ["free/qwen-3.8-max", "stealth/crouton-alpha"],
    },
    "free/qwen-3.8-max": {
        "spoken": "qwen 3.8 max",
        "family": "qwen",
        "version": "3.8 max",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "QWEN 3.8 MAX",
        "free": True,
        "fallbacks": ["free/kimi-k3", "stealth/crouton-alpha"],
    },
    "free/kimi-k3": {
        "spoken": "kimi k3",
        "family": "kimi",
        "version": "3",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "KIMI K3",
        "free": True,
        "fallbacks": ["free/gemini-3.8-flash", "stealth/crouton-alpha"],
    },
    "free/gemini-3.8-flash": {
        "spoken": "gemini 3.8 flash",
        "family": "gemini",
        "version": "3.8 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "GEMINI 3.8 FLASH",
        "free": True,
        "fallbacks": ["free/glm-5.3", "stealth/crouton-alpha"],
    },
    "free/deepseek-v4.1-flash": {
        "spoken": "deepseek 4.1 flash",
        "family": "deepseek",
        "version": "4.1 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "DEEPSEEK 4.1 FLASH",
        "free": True,
        "fallbacks": ["free/gpt-6-luna", "stealth/crouton-alpha"],
    },
    "free/gpt-6-luna": {
        "spoken": "gpt 6 luna",
        "family": "gpt",
        "version": "6",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "GPT 6 LUNA",
        "free": True,
        "fallbacks": ["free/glm-5.3", "stealth/crouton-alpha"],
    },
    "free/muse-spark-1.3": {
        "spoken": "muse spark",
        "family": "muse",
        "version": "1.3",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "MUSE SPARK",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },
    "free/minimax-m3.1-flash": {
        "spoken": "minimax m3.1 flash",
        "family": "minimax",
        "version": "3.1 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "MINIMAX M3.1 FLASH",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },
    "free/mimo-v2.6-flash": {
        "spoken": "mimo 2.6 flash",
        "family": "mimo",
        "version": "2.6 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "MIMO 2.6 FLASH",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },
    "free/glm-5.3-flash": {
        "spoken": "glm 5.3 flash",
        "family": "glm",
        "version": "5.3 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "GLM 5.3 FLASH",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },
    "free/deepseek-v4-flash-0731": {
        "spoken": "deepseek v4 flash",
        "family": "deepseek",
        "version": "4 flash",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "DEEPSEEK V4 FLASH",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },
    "free/hy4": {
        "spoken": "hy 4",
        "family": "hy",
        "version": "4",
        "provider": "apinex",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "HY 4",
        "free": True,
        "fallbacks": ["stealth/crouton-alpha"],
    },

    # ── together.ai ─────────────────────────────────────────────────────
    # These ids are real and genuinely zero-priced, but Together refuses
    # every call until the account has a positive balance - the free ones
    # included. They are here so that topping up the account is all it takes.
    "meta-llama/Llama-3.3-70B-Instruct": {
        "spoken": "llama 3.3",
        "family": "llama",
        "version": "3.3",
        "provider": "together",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "LLAMA 3.3",
        "free": True,
        "fallbacks": ["free/glm-5.3", "stealth/crouton-alpha"],
    },
    "Qwen/Qwen2.5-72B": {
        "spoken": "qwen 2.5 72b",
        "family": "qwen",
        "version": "2.5 72b",
        "provider": "together",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "QWEN 2.5 72B",
        "free": True,
        "fallbacks": ["free/glm-5.3", "stealth/crouton-alpha"],
    },
    "google/gemma-3-27b-it": {
        "spoken": "gemma 3",
        "family": "gemma",
        "version": "3",
        "provider": "together",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "GEMMA 3",
        "free": True,
        "fallbacks": ["free/glm-5.3", "stealth/crouton-alpha"],
    },

    # ── OpenCode Zen ───────────────────────────────────────────────────
    # One key reaches a whole gateway, including the Claude models - so
    # Opus 5.5 is reachable here even without an Anthropic key. Every one
    # of these is spoken with a "zen" in front of it, which is how you say
    # that you want this provider's copy of a model rather than another's.
    #
    # The registry key is the provider's own model id. Where that id is
    # already taken - the Claude ones - it is prefixed, so one id never
    # means two things.
    "opencode/claude-opus-5-5": {
        "spoken": "zen opus 5.5",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN OPUS 5.5",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "opencode/claude-sonnet-5": {
        "spoken": "zen sonnet 5",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN SONNET 5",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "opencode/claude-fable-5-1": {
        "spoken": "zen fable 5.1",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN FABLE 5.1",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "opencode/claude-haiku-4-5": {
        "spoken": "zen haiku 4.5",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN HAIKU 4.5",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "gpt-6-astra": {
        "spoken": "zen astra",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN ASTRA",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "glm-5.3": {
        "spoken": "zen glm 5.3",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN GLM 5.3",
        "free": False,
        "fallbacks": ["free/glm-5.3"],
    },
    "kimi-k3": {
        "spoken": "zen kimi k3",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN KIMI K3",
        "free": False,
        "fallbacks": ["free/kimi-k3"],
    },
    "qwen3.8-max": {
        "spoken": "zen qwen 3.8 max",
        "family": "zen",
        "version": None,
        "provider": "opencode",
        "effort": False,
        "reasoning": REASONING_AUTO,
        "label": "ZEN QWEN 3.8 MAX",
        "free": False,
        "fallbacks": ["free/qwen-3.8-max"],
    },

    # The zero-cost routes on this gateway. They are genuinely free - the
    # price is zero - but the gateway will not serve them to a key without
    # an OpenCode Go subscription, so each one carries a fallback and the
    # response says which route actually answered.
    "crouton-alpha-free": {
        "spoken": "zen crouton",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN CROUTON", "free": True,
        "fallbacks": ["stealth/crouton-alpha", "free/glm-5.3"],
    },
    "glm-5.3-flash-free": {
        "spoken": "zen glm flash",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN GLM FLASH", "free": True,
        "fallbacks": ["free/glm-5.3-flash", "free/glm-5.3"],
    },
    "deepseek-v4.1-flash-free": {
        "spoken": "zen deepseek flash",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN DEEPSEEK FLASH", "free": True,
        "fallbacks": ["free/deepseek-v4.1-flash", "free/glm-5.3"],
    },
    "big-pickle": {
        "spoken": "zen pickle",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN PICKLE", "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "pulse-alpha-free": {
        "spoken": "zen pulse",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN PULSE", "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "beam-free": {
        "spoken": "zen beam",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN BEAM", "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "flint-40b-free": {
        "spoken": "zen flint",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN FLINT", "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "mimo-v2.6-flash-free": {
        "spoken": "zen mimo",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN MIMO", "free": True,
        "fallbacks": ["free/mimo-v2.6-flash", "free/glm-5.3"],
    },
    "nemotron-3.5-lightning-free": {
        "spoken": "zen nemotron",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN NEMOTRON", "free": True,
        "fallbacks": ["nvidia/nemotron-3-ultra-550b-a55b:free", "free/glm-5.3"],
    },
    "nemotron-3.5-super-vl-free": {
        "spoken": "zen super vl",
        "family": "zen", "version": None, "provider": "opencode",
        "effort": False, "reasoning": REASONING_AUTO,
        "label": "ZEN SUPER VL", "free": True,
        "fallbacks": ["free/glm-5.3"],
    },

    # ── NVIDIA NIM, the free developer tier ─────────────────────────────
    # NVIDIA's catalogue lists 84 models, but only the ones actually
    # deployed for chat answer at all: four of the ids 404 with "Function
    # not found" and four more take longer than ninety seconds. These five
    # were tested on this key and answered. They carry an explicit api_id,
    # because their own ids begin with "nvidia/" and the prefix rule would
    # otherwise strip it off and send a name the endpoint has never heard
    # of.
    "nvidia/nemotron-3-ultra-550b-a55b": {
        "spoken": "nvidia nemotron 3 ultra",
        "family": "nvidia",
        "version": "3",
        "provider": "nvidia",
        "api_id": "nvidia/nemotron-3-ultra-550b-a55b",
        "reasoning": REASONING_AUTO,   # NVIDIA 400s on include_reasoning
        "label": "NVIDIA NEMOTRON 3 ULTRA",
        "free": True,
        # It answered in a second this morning and has not answered at
        # all since. Refused with the fact, rather than left in the
        # registry looking ready. Delete this line when it comes back.
        "blocked": ("NVIDIA's nemotron 3 ultra stopped answering - no reply "
                    "within three minutes when I tried it on 5 November 2026"),
        "timeout": 30,
    },
    "nvidia/nemotron-3.5-bolt-e4b": {
        "spoken": "nvidia nemotron 3.5 bolt",
        "family": "nvidia",
        "version": "3.5 bolt",
        "provider": "nvidia",
        "api_id": "nvidia/nemotron-3.5-bolt-e4b",
        "reasoning": REASONING_AUTO,
        "label": "NVIDIA NEMOTRON 3.5 BOLT",
        "free": True,
        "fallbacks": ["free/glm-5.3"],
    },
    "nvidia/nemotron-3.5-lightning-30b-a3b": {
        "spoken": "nvidia nemotron 3.5 lightning",
        "family": "nvidia",
        "version": "3.5",
        "provider": "nvidia",
        "api_id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "reasoning": REASONING_NVIDIA_OFF,
        "label": "NVIDIA NEMOTRON 3.5 LIGHTNING",
        "free": True,
        # It thinks before it answers, so it needs a token budget that
        # leaves room for the answer as well as the thinking.
        "fallbacks": ["nvidia/nemotron-3.5-bolt-e4b", "free/glm-5.3"],
    },
    "minimaxai/minimax-m3.1-flash": {
        "spoken": "nvidia minimax m3.1 flash",
        "family": "nvidia",
        "version": "3.1",
        "provider": "nvidia",
        "api_id": "minimaxai/minimax-m3.1-flash",
        "reasoning": REASONING_NVIDIA_OFF,
        "label": "NVIDIA MINIMAX M3.1 FLASH",
        "free": True,
        "fallbacks": ["nvidia/nemotron-3.5-bolt-e4b", "free/glm-5.3"],
    },
    "google/gemma-4-31b-it": {
        "spoken": "nvidia gemma 4",
        "family": "nvidia",
        "version": "4",
        "provider": "nvidia",
        "api_id": "google/gemma-4-31b-it",
        "reasoning": REASONING_AUTO,
        "label": "NVIDIA GEMMA 4",
        "free": True,
        "fallbacks": ["nvidia/nemotron-3.5-bolt-e4b", "free/glm-5.3"],
    },
    "mistralai/mistral-large-4-1t-a52b": {
        "spoken": "nvidia mistral large 4.1",
        "family": "nvidia",
        "version": "4.1",
        "provider": "nvidia",
        "api_id": "mistralai/mistral-large-4-1t-a52b",
        "reasoning": REASONING_AUTO,
        "label": "NVIDIA MISTRAL LARGE 4.1",
        "free": True,
        "fallbacks": ["nvidia/nemotron-3.5-bolt-e4b", "free/glm-5.3"],
    },

    # ── Vercel AI Gateway ───────────────────────────────────────────────
    # The key is valid, but the gateway refuses every request until a
    # credit card is on file, so these are registered and refused rather
    # than advertised as if they worked.
    "vercel/anthropic-claude-opus-5.5": {
        "spoken": "vercel opus 5.5",
        "family": "vercel",
        "version": "5.5",
        "provider": "vercel",
        "api_id": "anthropic/claude-opus-5.5",
        "reasoning": REASONING_AUTO,
        "label": "VERCEL OPUS 5.5",
        "free": False,
    },
    "vercel/anthropic-claude-sonnet-5": {
        "spoken": "vercel sonnet 5",
        "family": "vercel",
        "version": "5",
        "provider": "vercel",
        "api_id": "anthropic/claude-sonnet-5",
        "reasoning": REASONING_AUTO,
        "label": "VERCEL SONNET 5",
        "free": False,
    },
    "vercel/deepseek-v4-flash": {
        "spoken": "vercel deepseek v4 flash",
        "family": "vercel",
        "version": "4",
        "provider": "vercel",
        "api_id": "deepseek/deepseek-v4-flash",
        "reasoning": REASONING_AUTO,
        "label": "VERCEL DEEPSEEK V4 FLASH",
        "free": False,
    },
}

# The explicit set of model ids that really exist. A candidate id that is not
# in here does not exist, however much it looks like it does.
KNOWN_MODEL_IDS = frozenset(MODELS)

# Model words we recognise well enough to refuse honestly instead of guessing.
OTHER_MODEL_WORDS = ("gpt", "gemini", "llama", "mistral", "grok", "deepseek", "gemma")

# A prefix that names one provider's copy of a model, so the whole rest of
# the phrase is the name: "zen opus 5.5", "nvidia nemotron 3 ultra".
ROUTE_PREFIXES = {"zen": "zen", "nvidia": "nvidia", "vercel": "vercel"}

# "go back to your normal brain" and the rest of that family.
RESET_PHRASES = ("normal brain", "default brain", "original brain",
                 "usual brain", "config model")

# Words that make a phrase a brain command even without a version.
BRAIN_COMMANDS = ("switch to", "try on", "go back to", "change to", "swap to",
                  "put on", "load the", "use the")


# Effort per route. Chat with the notes runs at medium; casual chatter is
# happy at low effort and noticeably snappier.
EFFORT_NOTES = "medium"
EFFORT_CASUAL = "low"

# max_tokens covers thinking + answer together.
MAX_TOKENS_CHAT = 2000
MAX_TOKENS_RETRY = 6000

# A title is the note's own name, so a title match outranks a body word.
TITLE_MATCH_BOOST = 4
# A bold field label is a note reporting that term as one of its own
# headline figures. A word mentioned in passing is not.
LABEL_MATCH_BOOST = 2

# Words are matched on a shared prefix of PREFIX_MIN characters, so "pack"
# finds "Packaging Team" and "roast" finds "Roasting Process". Four
# characters is long enough that "cup" does not swallow "cupping" by
# accident, and short enough that the ending a word grew never hides it.
PREFIX_MIN = 4

# A prefix match is weaker evidence than the same word: "roast" landing on
# "roaster" (a job title) should not outrank "roasting" in
# "Roasting Process". It counts for half.
PREFIX_DISCOUNT = 0.5
TOP_N = 6
HISTORY_TURNS = 6
SESSION_TTL = 3600

# ── Is this question even about the notes? ──────────────────────────────
# Small talk must never drag notes into the answer, and the galaxy must
# never move for it. Greetings, jokes, weather and thanks are chatter.
SMALL_TALK_PATTERNS = [
    r"\b(good\s+(morning|afternoon|evening|night))\b",
    r"^\s*(hi|hey|hello|yo|hiya|howdy|greetings)\b",
    r"\bhow are (you|we)\b",
    r"\bhow('s| is) (it|everything) going\b",
    r"\b(tell me (a|another)|crack (a|another)|say (a|another)) joke\b",
    r"\bjoke(s)?\b.{0,30}\babout\b",
    r"\bwhat('s| is) the (weather|time|date|day)\b",
    r"\b(thank you|thanks|cheers|bye|goodbye|see you|good night)\b",
    r"\bwho are you\b",
    r"\bwhat can you do\b",
    r"\b(say|write|tell) (me )?(something|anything) (funny|random)\b",
]
SMALL_TALK_RE = re.compile("|".join(SMALL_TALK_PATTERNS), re.IGNORECASE)

# One incidental body word is not a reason to drag six notes into an answer.
# A note has to be named by the question: a title match, a word only it
# owns, or two words it owns outright. A shared rare word on its own - a
# passing mention - does not clear this.
MIN_NOTE_SCORE = 3

# A source also has to be comparable with the best note. One note that is
# clearly ahead means the others were passing mentions, and the galaxy should
# fly to that one rather than light a cluster. Notes that score alike are a
# real cluster, and all of them get lit.
SOURCE_RATIO = 0.6


# ─── Config ─────────────────────────────────────────────────────────────
def load_config():
    if not CONFIG_FILE.exists():
        print(f"Config not found: {CONFIG_FILE}", file=sys.stderr)
        print(f"Create it with: {{\"anthropic_api_key\": \"...\", \"model\": \"{DEFAULT_MODEL}\"}}",
              file=sys.stderr)
        sys.exit(1)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"config.json is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)


CONFIG = load_config()
API_KEY = str(CONFIG.get("anthropic_api_key", "") or "").strip()
MODEL = str(CONFIG.get("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()

# Every provider's key is read out of config.json by provider_key(), which
# looks the key up in the PROVIDERS table. Nothing else needs to know.

# The brain in config.json is the default brain. Swaps are runtime only, so a
# restart always returns here - you can never be stranded on a brain you did
# not mean to keep.
CONFIG_MODEL_ID = MODEL
CURRENT_MODEL_ID = CONFIG_MODEL_ID

KEY_IS_PLACEHOLDER = (not API_KEY) or API_KEY == PLACEHOLDER_KEY

# A brain named in config.json that is not in the registry would be a typo
# that only shows up when someone asks a question. Say so at startup instead.
if CURRENT_MODEL_ID not in MODELS:
    print("WARNING: config.json names model %r, which is not in the registry."
          % CURRENT_MODEL_ID, file=sys.stderr)
    print("         Known models: %s" % ", ".join(sorted(MODELS)), file=sys.stderr)


# ─── Notes ──────────────────────────────────────────────────────────────
# Words too common in English to tell one note from another. Left in, they
# made the same two capture notes match every question ever asked, because
# their titles contain "the", "new" and "next".
STOPWORDS = {
    "the", "and", "for", "our", "new", "next", "with", "that", "this", "are",
    "was", "were", "has", "have", "had", "not", "but", "you", "your", "all",
    "can", "will", "would", "should", "could", "from", "into", "than", "then",
    "they", "them", "their", "its", "who", "what", "when", "where", "which",
    "how", "why", "yes", "any", "per", "via", "out", "off", "over", "under",
    "more", "most", "some", "such", "only", "also", "been", "being", "each",
    "one", "two", "use", "used", "using", "made", "make", "get", "got", "may",
    "must", "need", "set", "see", "way", "well", "much", "many", "own", "same",
    "too", "very", "just", "about", "after", "before", "between", "because",
    "while", "still", "back", "down", "here", "there", "these", "those", "upon",
    "during", "without", "within", "against", "above", "below", "up", "again",
    "further", "say", "said", "says", "like", "who's", "it's", "there",
}

# The verb of asking is not a topic. "What did we DECIDE about the churn
# program?" is a question about churn, not a hunt for notes that use the
# word decide - and one note said "Decide at the lowest competent level",
# which was enough to drag it into the answer. Bare period words are framing
# for the same reason: these notes are evergreen, so "last quarter" points
# at no topic at all.
FRAMING_WORDS = {
    "decide", "decides", "decided", "deciding", "decision", "decisions",
    "know", "knows", "known", "mean", "means", "meant", "understand",
    "understands", "understood", "learn", "learns", "learnt", "learned",
    "think", "thinks", "thought", "happen", "happens", "happened",
    "occur", "occurs", "occurred", "want", "wants", "wanted", "prefer",
    "prefers", "preferred", "tell", "tells", "told", "explain", "explains",
    "explained", "describe", "describes", "described", "last", "latest",
    "current", "currently", "today", "yesterday", "tomorrow", "quarter",
    "week", "month", "year", "time", "times",
}

# How much a word in a note body counts towards a match. A word that turns
# up in a great many notes cannot tell one note from another; a word that
# turns up in only a few is a strong pointer. A title match always counts
# fully, because a title is a note's own name.
BODY_COMMON_FRACTION = 0.25     # in a quarter of the notes or more: no weight
BODY_RARE_FRACTION = 0.18       # in under a fifth: double weight
BODY_RARE_WEIGHT = 2
# A word only one note uses is that note's own vocabulary. It names the
# thing the note is about, so it counts for more than a shared rare word.
BODY_UNIQUE_WEIGHT = 3


def words_match(query_word, note_word):
    """Whether a query word and a note word are one word in two clothes."""
    if query_word == note_word:
        return True
    if len(query_word) >= PREFIX_MIN and note_word.startswith(query_word):
        return True
    if len(note_word) >= PREFIX_MIN and query_word.startswith(note_word):
        return True
    return False


def label_words(content):
    """The bold field labels in a note - the figures it reports as headlines.

    "**Revenue: $2.84M**" is a label: the note reports revenue as one of its
    own headline numbers. A word mentioned in passing ("40% of Signature
    Series revenue") is not. When a question asks for revenue, that
    difference decides which note the galaxy flies to.
    """
    found = set()
    for line in content.splitlines():
        match = re.match(r"^\s*\*\*([^*]+)\*\*\s*$", line)
        if not match:
            match = re.match(r"^\s*\*\*([^*\n]{2,40}?):", line)
        if not match:
            continue
        label = match.group(1).replace("**", " ")
        found |= set(re.findall(r"\b\w{3,}\b", label.lower())) - STOPWORDS - FRAMING_WORDS
    return found


class Note:
    __slots__ = ("id", "title", "content", "excerpt", "words", "title_words",
                 "labels")

    def __init__(self, note_id, title, content):
        self.id = note_id
        self.title = title
        self.content = content
        self.excerpt = content[:700]
        clean = strip_markdown(content)
        self.words = (set(re.findall(r"\b\w{3,}\b", clean.lower()))
                      - STOPWORDS - FRAMING_WORDS)
        self.title_words = (set(re.findall(r"\b\w{3,}\b", title.lower()))
                             - STOPWORDS - FRAMING_WORDS)
        self.labels = label_words(content)


def strip_markdown(text):
    text = re.sub(r"^---[\s\S]*?---", "", text)
    text = re.sub(r"^#+\s.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s*\|.*\|", "", text, flags=re.MULTILINE)
    return text


def load_notes():
    notes = []
    files = sorted(NOTES_DIR.rglob("*.md")) if NOTES_DIR.exists() else []
    for index, path in enumerate(files):
        content = path.read_text(encoding="utf-8", errors="replace")
        heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
        else:
            stem = re.sub(r"^\d{8}-\d{6}[-_ ]*", "", path.stem)
            stem = re.sub(r"^\d+[-_ ]+", "", stem)
            title = " ".join(w.capitalize() for w in re.split(r"[-_]+", stem) if w) or path.stem
        notes.append(Note(index, title, content))
    return notes


NOTES = load_notes()


def build_body_weights(notes):
    """How much each word counts when it appears in a note body.

    A word that turns up in a quarter of the notes or more cannot tell one
    note from another, so it counts for nothing. A word that turns up in
    only a few notes is a strong pointer, so it counts double.
    """
    total = len(notes) or 1
    document_frequency = {}
    for note in notes:
        for word in note.words:
            document_frequency[word] = document_frequency.get(word, 0) + 1

    common_cut = max(3, int(total * BODY_COMMON_FRACTION))
    rare_cut = max(2, int(total * BODY_RARE_FRACTION))
    weights = {}
    for word, count in document_frequency.items():
        if count == 1:
            weights[word] = BODY_UNIQUE_WEIGHT
        elif count >= common_cut:
            weights[word] = 0
        elif count <= rare_cut:
            weights[word] = BODY_RARE_WEIGHT
        else:
            weights[word] = 1
    return weights, document_frequency


BODY_WEIGHTS, DOCUMENT_FREQUENCY = build_body_weights(NOTES)

# Every word that appears in any note, so a query word can be matched
# against all of them at once.
ALL_WORDS = set()
for note in NOTES:
    ALL_WORDS |= note.words


# ─── Scoring ────────────────────────────────────────────────────────────
def label_value(word, exact):
    """How much a bold field label is worth as evidence.

    A label points harder when the word behind it is rare: "**Revenue:
    $2.84M**" names a figure only Financials reports, while "**Training
    program**" is a heading in three notes and says very little.
    """
    df = DOCUMENT_FREQUENCY.get(word, 0)
    share = 1.0 - (df / max(len(NOTES), 1))
    value = LABEL_MATCH_BOOST * max(0.0, share)
    return value if exact else value * PREFIX_DISCOUNT


def expand_query_word(word):
    """Every note word that answers to this query word.

    Each hit says whether the match was exact or only a prefix, because a
    prefix match is weaker evidence and counts for half.
    """
    hits = []
    for candidate in ALL_WORDS:
        if word == candidate:
            hits.append((candidate, BODY_WEIGHTS.get(candidate, 1), True))
        elif words_match(word, candidate):
            hits.append((candidate, BODY_WEIGHTS.get(candidate, 1), False))
    return hits


def score_notes(question):
    """Rank notes by keyword overlap, weighting title matches higher.

    Returns a list of (score, note_id), best first.
    """
    q_words = (set(re.findall(r"\b\w{3,}\b", question.lower()))
               - STOPWORDS - FRAMING_WORDS)
    if not q_words:
        return []
    expansions = {word: expand_query_word(word) for word in q_words}
    scored = []
    for note in NOTES:
        body = 0.0
        title = 0.0
        label = 0.0
        for hits in expansions.values():
            best = 0.0
            title_hit = 0.0
            label_hit = 0.0
            for word, weight, exact in hits:
                if word in note.words:
                    value = weight if exact else weight * PREFIX_DISCOUNT
                    if value > best:
                        best = value
                if word in note.title_words:
                    value = (TITLE_MATCH_BOOST if exact
                             else TITLE_MATCH_BOOST * PREFIX_DISCOUNT)
                    if value > title_hit:
                        title_hit = value
                if word in note.labels:
                    value = label_value(word, exact)
                    if value > label_hit:
                        label_hit = value
            body += best
            title += title_hit
            label += label_hit
        total = body + title + label
        if total > 0:
            scored.append((total, note.id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored


def select_source_notes(ranked):
    """The notes an answer may cite, and the galaxy may point at.

    A note has to earn its place twice over: it must score at all, and it
    must come within SOURCE_RATIO of the best score. That is what keeps a
    single incidental word from dragging a note into the answer, and what
    keeps one clearly-best note from being diluted by passing mentions.
    """
    if not ranked:
        return []
    floor = max(MIN_NOTE_SCORE, ranked[0][0] * SOURCE_RATIO)
    return [note_id for score, note_id in ranked if score >= floor][:TOP_N]


def is_small_talk(question):
    """True when the question is chatter rather than a question about the notes.

    This is the first decision the server makes, because the effort route,
    the note context and whether the galaxy is allowed to move all hang off it.
    """
    text = question.strip()
    if not text:
        return True
    return bool(SMALL_TALK_RE.search(text))


# ─── Conversation history ───────────────────────────────────────────────
SESSIONS = {}
SESSION_LOCK = threading.Lock()


def get_session(session_id):
    with SESSION_LOCK:
        now = time.time()
        session = SESSIONS.get(session_id)
        if session is not None:
            if now - session["last_access"] < SESSION_TTL:
                session["last_access"] = now
                return session
            del SESSIONS[session_id]
        session = {"history": [], "last_access": now}
        SESSIONS[session_id] = session
        return session


# ─── Brain ──────────────────────────────────────────────────────────────
# The two system prompts live in the BUTLER block at the top of this file.
# That block is the only place the character is defined.


# ─── Choosing a brain ───────────────────────────────────────────────────
def model_label(model_id):
    """A human label for a model id.

    Only a hyphen between two digits is a version dot: 5-5 reads 5.5, while
    opus-5 is not a dot at all and fable-5-1 is a version, not two numbers.
    """
    spec = MODELS.get(model_id)
    if spec and spec.get("label"):
        return spec["label"]
    text = str(model_id or "").strip().lower()
    text = re.sub(r"^claude[-_]", "", text)
    text = re.sub(r"(\d)-(\d)", r"\1.\2", text)
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)
    text = re.sub(r"[-_/]+", " ", text)
    return text.strip().upper() or "UNKNOWN"


def model_families():
    """family -> the model ids that belong to it."""
    families = {}
    for model_id, spec in MODELS.items():
        families.setdefault(spec["family"], []).append(model_id)
    return families


def build_candidate_ids(family, version):
    """Every id a family plus a version could name.

    Looked up in the registry rather than assembled from a pattern, because
    the ids are not all shaped alike: opus 5.5 is claude-opus-5-5, but
    nemotron 3 is nvidia/nemotron-3-ultra-550b-a55b:free. The lookup is
    what keeps the safety rule honest - a family and a version either name
    a model that is really there, or they name nothing at all.
    """
    found = []
    for model_id, spec in MODELS.items():
        if spec.get("family") != family:
            continue
        if version is None:
            if spec.get("version") is None:
                found.append(model_id)
        elif str(spec.get("version")) == str(version):
            found.append(model_id)
    return found


def build_candidate_id(family, version):
    """The first id a family plus a version would name, or None."""
    found = build_candidate_ids(family, version)
    return found[0] if found else None


def model_short_id(model_id):
    """The model's own id, without the prefix that disambiguates the route.

    "opencode/claude-opus-5-5" and "claude-opus-5-5" are two routes to the
    same model; the short id is how the server knows they are the same
    model and can offer the other route when one of them has no key.
    """
    return model_id.rsplit("/", 1)[-1]


def route_for_model(model_id):
    """Pick the route to a model that can actually answer.

    The route named in the registry comes first, then any other provider's
    copy of the same model. That is how "opus 5.5" reaches OpenCode Zen when
    there is no Anthropic key to reach it with.
    """
    spec = MODELS.get(model_id, {})
    if provider_key(spec.get("provider", "anthropic")):
        return model_id
    short = model_short_id(model_id)
    for other_id, other_spec in MODELS.items():
        if other_id == model_id:
            continue
        if model_short_id(other_id) != short:
            continue
        if provider_key(other_spec.get("provider", "anthropic")):
            return other_id
    return model_id


def normalise_phrase(text):
    """Put a spoken phrase into the same shape every time.

    "opus5" -> "opus 5", "5 point 5" -> "5.5", and "v 4" -> "v4" rather
    than the split the letter-digit rule would make of it. The registry's
    own spoken names go through this too, so a name like "kimi k3" is
    matched in either shape.
    """
    flat = re.sub(r"[^a-z0-9.]+", " ", str(text or "").lower())
    flat = re.sub(r"([a-z])(\d)", r"\1 \2", flat)              # "opus5" -> "opus 5"
    flat = re.sub(r"\bv\s+(\d)", r"v\1", flat)                 # "v 4" -> "v4" (not a split)
    flat = re.sub(r"\b(\d)\s+point\s+(\d)\b", r"\1.\2", flat)  # "5 point 5" -> "5.5"
    return re.sub(r"\s+", " ", flat).strip()


def route_by_spoken(prefix, rest):
    """The route whose spoken name is "<prefix> <rest>".

    An exact match wins. Failing that, a name that STARTS with the phrase
    is accepted when exactly one does, so "nvidia nemotron 3" finds
    "nvidia nemotron 3 ultra" without ever inventing a second candidate.
    """
    wanted = normalise_phrase(prefix + " " + rest)
    starts = []
    for model_id, spec in MODELS.items():
        spoken = normalise_phrase(spec.get("spoken") or "")
        if spoken == wanted:
            return model_id
        if spoken.startswith(wanted + " "):
            starts.append(model_id)
    if len(starts) == 1:
        return starts[0]
    return None


def zen_route(rest):
    """The OpenCode Zen route whose spoken name is "zen <rest>"."""
    return route_by_spoken("zen", rest)


def provider_blocked(provider):
    """Why this provider cannot answer right now, or None if it can.

    A key is not the same as a working route. The Vercel gateway takes the
    key, says it is valid, and then refuses every request until a credit
    card is on file. A route in that state is refused with its reason, not
    advertised as though it were ready.
    """
    spec = PROVIDERS.get(provider) or {}
    return spec.get("blocked")


def available_models_line():
    """What we do have, said like a butler listing the silver.

    Grouped by whether the route costs anything, because that is the first
    question anybody actually asks of a brain. The free list is trimmed -
    there are more than can be read in one line - and the whole registry is
    always available at GET /models.
    """
    free, paid = [], []
    for model_id, spec in MODELS.items():
        if not provider_key(spec.get("provider", "anthropic")):
            continue        # no key for that provider: we cannot use it
        if provider_blocked(spec.get("provider", "anthropic")):
            continue        # the key works but the route is refused upstream
        name = model_label(model_id).title()
        (free if spec.get("free") else paid).append(name)

    def join(names, limit=6):
        if not names:
            return ""
        if len(names) <= limit:
            return ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1 else names[0])
        return ", ".join(names[:limit]) + " and %d more" % (len(names) - limit)

    parts = []
    if free:
        parts.append("free and ready: %s" % join(free))
    if paid:
        parts.append("on credit: %s" % join(paid))
    if not parts:
        return "nothing at all, sir"
    return "; ".join(parts)


def resolve_model_request(text):
    """Read a spoken request for a different brain.

    Returns {"action": "none"|"reset"|"swap"|"error", ...}. The candidate id is
    built from the family and the version read immediately after the family
    word - glued forms included - and is then checked against
    KNOWN_MODEL_IDS. No near misses, ever.
    """
    flat = normalise_phrase(text)
    squashed = flat.replace(" ", "")

    for phrase in RESET_PHRASES:
        if phrase.replace(" ", "") in squashed:
            return {"action": "reset"}

    families = model_families()
    tokens = flat.split(" ") if flat else []
    has_command = any(command in flat for command in BRAIN_COMMANDS)

    for index, token in enumerate(tokens):
        known_family = token in families
        if not known_family and token not in OTHER_MODEL_WORDS:
            continue

        # A brain command is a short imperative thing - "try on opus 5",
        # "switch to fable 5.1", "ask for opus 6" - not a sentence that
        # happens to mention a model on its way past.
        imperative = has_command or len(tokens) <= 4 or index == 0

        # "zen <model>", "nvidia <model>", "vercel <model>" name one
        # provider's copy of a model, so the whole rest of the phrase is
        # the name and nothing else may be read.
        if token in ROUTE_PREFIXES:
            prefix = ROUTE_PREFIXES[token]
            rest = " ".join(tokens[index + 1:]).strip()
            if not rest:
                if not imperative:
                    continue
                available = [i for i, s in MODELS.items()
                             if normalise_phrase(s.get("spoken") or "").startswith(prefix + " ")]
                return {"action": "error", "error": "ambiguous",
                        "wanted": prefix.title(), "available": available}
            route = route_by_spoken(prefix, rest)
            if route is not None:
                if not imperative:
                    continue
                return {"action": "swap", "id": route,
                        "wanted": model_label(route).title()}
            if prefix == "zen":
                if not imperative:
                    continue
                return {"action": "error", "error": "unknown_model",
                        "wanted": "Zen " + rest.title()}
            # Not a full spoken name. Fall through to the family logic,
            # so "nvidia 3" still finds the version.

        version = None
        candidate = None
        first = tokens[index + 1] if index + 1 < len(tokens) else ""
        # "v4" is "4" with a prefix on it.
        if first.startswith("v") and first[1:].isdigit():
            first = first[1:]
        if re.fullmatch(r"\d+(\.\d+)?", first):
            # A version may be two words - "5.3 flash" - so the longer reading
            # is tried first.
            readings = []
            if index + 2 < len(tokens) and re.fullmatch(r"[a-z0-9]+", tokens[index + 2]):
                readings.append("%s %s" % (first, tokens[index + 2]))
            readings.append(first)
            for reading in readings:
                found = build_candidate_id(token, reading)
                if found:
                    candidate = found
                    version = reading
                    break
            if candidate is None:
                version = first

        if not known_family:
            # A family we have never heard of. Only refuse it if the phrase
            # reads like a brain command; otherwise it is just a question.
            if imperative:
                wanted = token.title() + (" " + version if version else "")
                return {"action": "error", "error": "unknown_model", "wanted": wanted}
            continue

        if version is None:
            if not imperative:
                continue          # a passing mention, not a brain command
            candidates = families[token]
            if len(candidates) == 1:
                return {"action": "swap", "id": route_for_model(candidates[0]),
                        "wanted": model_label(candidates[0]).title()}
            return {"action": "error", "error": "ambiguous", "wanted": token.title(),
                    "available": candidates}

        if candidate is None or candidate not in KNOWN_MODEL_IDS:
            # Not a near miss. Refuse, and say what we do have.
            return {"action": "error", "error": "unknown_model",
                    "wanted": token.title() + " " + version, "candidate": candidate}
        if not imperative:
            continue              # a passing mention, not a brain command
        # The route that can actually answer, which may be another
        # provider's copy of the same model.
        return {"action": "swap", "id": route_for_model(candidate),
                "wanted": model_label(candidate).title()}

    return {"action": "none"}


def apply_model_request(text):
    """Act on a spoken request to change brain. Returns None if it was not one."""
    global CURRENT_MODEL_ID
    result = resolve_model_request(text)
    if result["action"] == "none":
        return None

    if result["action"] == "reset":
        CURRENT_MODEL_ID = CONFIG_MODEL_ID
        return {"ok": True, "swapped": True, "model": CURRENT_MODEL_ID,
                "label": model_label(CURRENT_MODEL_ID),
                "message": "Back to your usual, sir."}

    if result["action"] == "swap":
        model_id = result["id"]
        spec = MODELS[model_id]
        provider = spec.get("provider", "anthropic")

        # Refuse a swap onto a brain that cannot answer. Swapping to Opus
        # with no Anthropic key would leave you with a brain that only
        # ever says "give me a key", so it is better to say so now.
        if not provider_key(provider):
            if provider == "anthropic":
                message = ("%s needs an Anthropic API key in config.json, sir. I have "
                           "not got one, so I shall not pretend."
                           % model_label(model_id).title())
            else:
                message = ("%s needs a %s key in config.json, sir. I have not got one, "
                           "so I shall not pretend."
                           % (model_label(model_id).title(), provider))
            return {"ok": False, "error": "no_%s_key" % provider,
                    "message": message,
                    "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID)}

        # A route that the provider itself refuses is refused here, with
        # its reason, rather than failing later in the middle of a
        # conversation.
        blocked = provider_blocked(provider)
        if blocked:
            message = ("%s cannot answer at the moment, sir: %s."
                       % (model_label(model_id).title(), blocked))
            return {"ok": False, "error": "provider_blocked",
                    "message": message,
                    "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID)}

        # One model can be down while the rest of its provider is up.
        # That is refused too, with its own reason.
        model_blocked = spec.get("blocked")
        if model_blocked:
            message = ("%s cannot answer at the moment, sir: %s."
                       % (model_label(model_id).title(), model_blocked))
            return {"ok": False, "error": "model_blocked",
                    "message": message,
                    "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID)}

        CURRENT_MODEL_ID = model_id
        return {"ok": True, "swapped": True, "model": model_id,
                "label": model_label(model_id),
                "free": bool(spec.get("free")),
                "message": "Very good, sir. %s it is." % model_label(model_id).title()}

    if result["error"] == "ambiguous":
        names = [model_label(i).title() for i in result["available"]]
        if len(names) > 8:
            shown = ", ".join(names[:8]) + " and %d more" % (len(names) - 8)
        else:
            shown = " or ".join(names)
        message = ("%s comes in %d sizes, sir: %s. Which would you like?"
                   % (result["wanted"], len(names), shown))
    else:
        message = ("I don't have %s yet, sir. I have %s - and none of them is a substitute."
                   % (result["wanted"], available_models_line()))
    return {"ok": False, "error": result["error"], "message": message,
            "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID)}


def build_context(note_ids):
    parts = []
    for note_id in note_ids:
        note = NOTES[note_id]
        parts.append(f"--- NOTE {note_id}: {note.title} ---\n{note.content[:3000]}")
    return "\n\n".join(parts)


def extract_text(response):
    """Pull the answer text out of a Messages response.

    Thinking is always on for this model, so the response can contain
    thinking blocks as well as text blocks; only the text counts.
    """
    chunks = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = (getattr(block, "text", "") or "").strip()
            if text:
                chunks.append(text)
    return "\n\n".join(chunks).strip()


def call_anthropic(model_id, system_prompt, messages, effort, max_tokens):
    """One Anthropic Messages call, Opus 5.5 rules applied."""
    client = anthropic.Anthropic(api_key=API_KEY)
    kwargs = {
        "model": model_id,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system_prompt}],
        "messages": messages,
    }
    spec = MODELS.get(model_id)
    if spec is None or spec.get("effort", True):
        # Effort is a per-route setting and lives in output_config. The
        # installed SDK does not expose output_config as a first-class
        # parameter, so it goes through extra_body - the documented way to add
        # request fields. Haiku takes no effort setting, so it gets none.
        kwargs["extra_body"] = {"output_config": {"effort": effort}}

    response = client.messages.create(**kwargs)
    return extract_text(response)


class ProviderError(Exception):
    """A provider call that did not come back with an answer."""

    def __init__(self, message, code="api_error", status=0, provider=""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.provider = provider

    @property
    def retryable(self):
        """Rate limits and provider hiccups are worth trying another route for."""
        return self.status in (0, 400, 402, 429, 500, 502, 503, 504)


def provider_key(provider):
    """The API key a provider needs, or "" when there is none."""
    if provider == "anthropic":
        return "" if KEY_IS_PLACEHOLDER else API_KEY
    spec = PROVIDERS.get(provider) or {}
    return str(CONFIG.get(spec.get("key_field", ""), "") or "").strip()


def provider_base_url(provider):
    """The base URL for a provider, allowing config.json to override it."""
    spec = PROVIDERS.get(provider) or {}
    override = str(CONFIG.get(spec.get("base_url_field", ""), "") or "").strip()
    return (override or spec.get("base_url", "")).rstrip("/")


def provider_headers(provider):
    """The headers a provider wants sent."""
    spec = PROVIDERS.get(provider) or {}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if spec.get("user_agent"):
        headers["User-Agent"] = spec["user_agent"]
    for name, value in (spec.get("headers") or {}).items():
        headers[name] = value
    return headers


def openrouter_reasoning_flags(spec):
    """The reasoning flags this route needs, if any.

    A route that insists on thinking rejects any attempt to switch it off,
    so sending the flag there is itself the bug.
    """
    mode = spec.get("reasoning", REASONING_AUTO)
    if mode == REASONING_OFF:
        return {"reasoning": {"enabled": False, "exclude": True},
                "include_reasoning": False}
    if mode == REASONING_NVIDIA_OFF:
        return {"reasoning": {"enabled": False}}
    return {}


def api_model_id(model_id):
    """The id the provider itself expects, which is not always ours.

    The registry prefixes an id when two providers share it: "opencode/
    claude-opus-5-5" is our name for that route, "claude-opus-5-5" is the
    provider's. Sending ours would be answered with "Model is unavailable".
    """
    spec = MODELS.get(model_id, {})
    if spec.get("api_id"):
        return spec["api_id"]
    provider = spec.get("provider", "")
    prefix = provider + "/"
    if provider and model_id.startswith(prefix):
        return model_id[len(prefix):]
    return model_id


def call_compatible_once(model_id, system_prompt, messages, max_tokens):
    """One call to a provider that speaks the OpenAI-compatible dialect."""
    spec = MODELS.get(model_id, {})
    provider = spec.get("provider", "openrouter")
    payload = {
        "model": api_model_id(model_id),
        "messages": [{"role": "system", "content": system_prompt}] + list(messages),
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    payload.update(openrouter_reasoning_flags(spec))

    request = urllib.request.Request(
        provider_base_url(provider) + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(provider_headers(provider), Authorization="Bearer %s" % provider_key(provider)),
        method="POST",
    )
    # A route may have its own patience: the provider's, unless the
    # model says otherwise.
    timeout = spec.get("timeout") or (PROVIDERS.get(provider) or {}).get("timeout", 120)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            body = {}
        error = body.get("error") or {}
        code = str(error.get("code") or "")
        message = str(error.get("message") or raw or exc.reason or "")
        raise ProviderError(message, code or ("http_%s" % exc.code), exc.code, provider) from None
    except urllib.error.URLError as exc:
        raise ProviderError(str(exc.reason), "network_error", 0, provider) from None
    except TimeoutError as exc:
        # A slow route is a route that failed, not a dead server: let the
        # next one have its turn.
        raise ProviderError("the route took too long: %s" % exc,
                            "timeout", 0, provider) from None

    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    if content:
        return content
    # Some reasoning endpoints answer with no content at all and only a
    # trace. Better a trace than silence.
    return str(message.get("reasoning") or message.get("reasoning_content") or "").strip()


def call_openrouter(model_id, system_prompt, messages, max_tokens):
    """Call the brain, and try another zero-cost route if this one is capped.

    The daily free cap is per ACCOUNT, so a second route on the same
    account is no use. The fallbacks listed against a route cross to a
    different provider, which is the only kind of fallback that is worth
    having.
    """
    spec = MODELS.get(model_id, {})
    order = [model_id]
    for fallback in spec.get("fallbacks", []):
        if fallback in MODELS and fallback not in order:
            order.append(fallback)

    last = None
    for candidate in order:
        try:
            text = call_compatible_once(candidate, system_prompt, messages, max_tokens)
        except ProviderError as exc:
            last = exc
            if not exc.retryable:
                break
            continue
        if text:
            # Report the route that actually answered. When a fallback
            # carries the answer, the brain in the chip is not the one
            # that did the work, and the screen must not pretend it was.
            return text, candidate
        last = ProviderError("empty answer from %s" % candidate, "empty_response", 200)
    raise last or ProviderError("no route answered", "api_error", 0)


def provider_message(exc):
    """Say what the provider said, in the butler's voice."""
    code = (exc.code or "").lower()
    message = (exc.message or "").lower()
    if "free-models-per-day" in code or "free-models-per-minute" in code:
        return ("The free-model quota for today is spent, sir. It resets at midnight "
                "UTC, and until then I can only use the routes that are not capped.")
    if "free usage limit" in message or "free usage limit" in code:
        return ("OpenCode's zero-cost routes need an OpenCode Go subscription on "
                "this key, sir. I shall use another provider for now.")
    if exc.status == 402 and "credit limit" in message:
        return ("The account has no credits, sir. Together refuses even its free "
                "models until there is a balance, so I shall use another provider.")
    if exc.status == 402:
        return ("The provider says there are no credits left, sir. The zero-cost "
                "routes on the other providers are unaffected.")
    if exc.status == 401:
        return "That API key was rejected, sir. Check the key in config.json."
    if exc.status == 429:
        return ("Rate limited, sir. Give it a moment and I shall try again.")
    if exc.status == 403:
        return ("The provider turned me away, sir. %s" % exc.message[:180])
    return "The provider had a problem, sir: %s" % exc.message[:220]


def call_model(system_prompt, messages, effort, max_tokens):
    """Call whichever brain is currently in place.

    Returns (answer, route_that_answered). The route can differ from the
    brain when a fallback carried the answer.
    """
    model_id = CURRENT_MODEL_ID
    spec = MODELS.get(model_id)
    if spec and spec.get("provider") == "anthropic":
        return call_anthropic(model_id, system_prompt, messages, effort, max_tokens), model_id
    return call_openrouter(model_id, system_prompt, messages, max_tokens)


def ask_claude(system_prompt, messages, effort):
    """Call the model; retry once with a bigger budget if the text is empty."""
    text, served_by = call_model(system_prompt, messages, effort, MAX_TOKENS_CHAT)
    if text:
        return text, served_by
    # Thinking + answer share the budget, so an empty answer usually means
    # the budget was too small. Retry once, larger.
    try:
        return call_model(system_prompt, messages, effort, MAX_TOKENS_RETRY)
    except Exception:
        return "", served_by


# ─── Request handler ────────────────────────────────────────────────────
class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        if self.path.endswith((".js", ".css", ".html", ".json", ".png", ".jpg", ".svg", ".ico")):
            self.send_header("Cache-Control", "public, max-age=3600")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        # The boot greeting, so the character lives in one place only.
        requested = self.path.split("?", 1)[0].lstrip("/")
        if requested == "greeting":
            self.send_json(HTTPStatus.OK, {"greeting": BOOT_GREETING})
            return
        # Which brain is in place right now.
        if requested == "model":
            spec = MODELS.get(CURRENT_MODEL_ID, {})
            self.send_json(HTTPStatus.OK, {
                "model": CURRENT_MODEL_ID,
                "label": model_label(CURRENT_MODEL_ID),
                "default_model": CONFIG_MODEL_ID,
                "free": bool(spec.get("free")),
                "provider": spec.get("provider", "anthropic"),
            })
            return
        # The whole registry, for when the refusal message is too short.
        if requested == "models":
            self.send_json(HTTPStatus.OK, {"models": [
                {
                    "id": model_id,
                    "label": model_label(model_id),
                    "spoken": spec.get("spoken"),
                    "provider": spec.get("provider", "anthropic"),
                    "free": bool(spec.get("free")),
                    "usable": (bool(provider_key(spec.get("provider", "anthropic")))
                              and not provider_blocked(spec.get("provider", "anthropic"))
                              and not spec.get("blocked")),
                    "note": spec.get("blocked"),
                }
                for model_id, spec in MODELS.items()
            ]})
            return
        # The API key lives in the project root; never serve it.
        if requested == "config.json" or ".." in Path(requested).parts:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/chat":
            self.handle_chat()
        elif self.path == "/model":
            self.handle_model()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_chat(self):
        body = self.read_json()
        if body is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body."})
            return

        question = str(body.get("question", "") or "").strip()
        if not question:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No question provided."})
            return

        session_id = str(body.get("session_id", "") or "") or str(uuid.uuid4())
        session = get_session(session_id)

        # A request to change brain is answered before anything else, and it
        # never reaches the notes.
        brain = apply_model_request(question)
        if brain is not None:
            payload = {
                "answer": brain["message"],
                "nodes": [],
                "intent": "model",
                "model": brain["model"],
                "label": brain["label"],
                "swapped": bool(brain.get("swapped")),
                "session_id": session_id,
            }
            if brain.get("error"):
                payload["error"] = brain["error"]
            self.send_json(HTTPStatus.OK, payload)
            return

        # Decide first whether this is a question about the notes at all. The
        # route, the effort and whether the galaxy is allowed to move all hang
        # off this single decision - it is made before anything else.
        small_talk = is_small_talk(question)
        ranked = [] if small_talk else score_notes(question)

        # Only notes that genuinely matched count as sources. A note has to
        # earn its place with a title match or real word overlap, and it has
        # to be comparable with the best match - and those are the notes the
        # answer is built from, and the only ones the galaxy may point at.
        node_ids = select_source_notes(ranked)
        intent = "casual" if small_talk else "notes"

        # A missing key is a configuration problem, not a crash - and which key
        # is needed depends on which brain is in place.
        brain_spec = MODELS.get(CURRENT_MODEL_ID, {})
        brain_provider = brain_spec.get("provider", "anthropic")
        if not provider_key(brain_provider):
            if brain_provider == "anthropic":
                answer = ("I need an Anthropic API key before I can think. Paste your "
                          "key into config.json in the project root (never in "
                          "viewer/), then reload.")
                error = "missing_api_key"
            else:
                answer = ("I need a %s key before I can think, sir. Paste it into "
                          "config.json in the project root (never in viewer/), then "
                          "reload." % brain_provider)
                error = "missing_%s_key" % brain_provider
            self.send_json(HTTPStatus.OK, {
                "answer": answer,
                "nodes": [],
                "intent": intent,
                "session_id": session_id,
                "error": error,
            })
            return

        casual = intent == "casual"

        if casual:
            system_prompt = SYSTEM_CASUAL
            messages = []
            for turn in session["history"][-HISTORY_TURNS:]:
                messages.append({"role": turn["role"], "content": turn["content"]})
            messages.append({"role": "user", "content": question})
            effort = EFFORT_CASUAL
        else:
            system_prompt = SYSTEM_NOTES
            context = build_context(node_ids)
            messages = []
            for turn in session["history"][-HISTORY_TURNS:]:
                messages.append({"role": turn["role"], "content": turn["content"]})
            if context:
                messages.append({
                    "role": "user",
                    "content": f"Notes:\n{context}\n\nQuestion: {question}",
                })
            else:
                messages.append({
                    "role": "user",
                    "content": ("No note in the collection matches this question.\n\n"
                                f"Question: {question}"),
                })
            effort = EFFORT_NOTES

        try:
            answer, served_by = ask_claude(system_prompt, messages, effort)
        except ProviderError as exc:
            self.send_json(HTTPStatus.OK, {
                "answer": provider_message(exc),
                "nodes": [],
                "intent": intent,
                "session_id": session_id,
                "error": exc.code,
            })
            return
        except anthropic.AuthenticationError:
            self.send_json(HTTPStatus.OK, {
                "answer": "That Anthropic API key was rejected. Check the key in config.json.",
                "nodes": [],
                "session_id": session_id,
                "error": "invalid_api_key",
            })
            return
        except anthropic.APIConnectionError:
            self.send_json(HTTPStatus.OK, {
                "answer": "I could not reach the Anthropic API. Check your connection and try again.",
                "nodes": [],
                "session_id": session_id,
                "error": "connection_error",
            })
            return
        except Exception as exc:
            self.send_json(HTTPStatus.OK, {
                "answer": f"The model call failed: {type(exc).__name__}: {exc}",
                "nodes": [],
                "session_id": session_id,
                "error": "api_error",
            })
            return

        if not answer:
            self.send_json(HTTPStatus.OK, {
                "answer": "The model came back empty. Try again.",
                "nodes": [],
                "session_id": session_id,
                "error": "empty_response",
            })
            return

        session["history"].append({"role": "user", "content": question})
        session["history"].append({"role": "assistant", "content": answer})

        self.send_json(HTTPStatus.OK, {
            "answer": answer,
            "nodes": node_ids,
            "intent": intent,
            "model": CURRENT_MODEL_ID,
            "label": model_label(CURRENT_MODEL_ID),
            "free": bool(MODELS.get(CURRENT_MODEL_ID, {}).get("free")),
            "served_by": served_by,
            "served_by_label": model_label(served_by) if served_by else "",
            "session_id": session_id,
        })

    def handle_model(self):
        """Swap the brain at runtime. Runtime only: a restart returns to the
        model in config.json."""
        body = self.read_json()
        if body is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {
                "ok": False, "error": "invalid_json",
                "message": "Give me a phrase, sir.",
                "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID),
            })
            return

        phrase = str(body.get("phrase", body.get("question", "")) or "").strip()
        if not phrase:
            self.send_json(HTTPStatus.BAD_REQUEST, {
                "ok": False, "error": "no_phrase",
                "message": "Give me a phrase, sir.",
                "model": CURRENT_MODEL_ID, "label": model_label(CURRENT_MODEL_ID),
            })
            return

        result = apply_model_request(phrase)
        if result is None:
            result = {
                "ok": False,
                "error": "not_a_brain_request",
                "message": ("I did not catch a brain in that, sir. I have %s."
                            % available_models_line()),
                "model": CURRENT_MODEL_ID,
                "label": model_label(CURRENT_MODEL_ID),
            }

        payload = {
            "ok": result["ok"],
            "model": result["model"],
            "label": result["label"],
            "message": result["message"],
            "free": bool(MODELS.get(result["model"], {}).get("free")),
        }
        if result.get("error"):
            payload["error"] = result["error"]
        if result.get("swapped"):
            payload["swapped"] = True
        self.send_json(HTTPStatus.OK, payload)


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
        print(f"Viewer folder not found: {VIEWER_DIR}", file=sys.stderr)
        sys.exit(1)
    for required in ("index.html", "graph-data.js"):
        if not (VIEWER_DIR / required).exists():
            print(f"Missing {required}. Run: python build.py", file=sys.stderr)
            sys.exit(1)

    os.chdir(VIEWER_DIR)

    print(f"Knowledge Galaxy server on http://127.0.0.1:{PORT}")
    print(f"Serving: {VIEWER_DIR}")
    print(f"Config:  {CONFIG_FILE}")
    print(f"Model:   {MODEL}")
    print(f"Notes:   {len(NOTES)} loaded")
    if KEY_IS_PLACEHOLDER:
        print("API key: PLACEHOLDER - /chat will report a configuration error until you paste a key")
    print("Press Ctrl+C to stop")

    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), ViewerHandler) as httpd:
        httpd.daemon_threads = True
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            httpd.shutdown()


if __name__ == "__main__":
    main()
