"""Download and cache the local Whisper model used by /transcribe.

Run once; afterwards transformers loads it from the Hugging Face cache and
the mic works offline.

    python fetch_whisper_model.py            # default: openai/whisper-base
    python fetch_whisper_model.py openai/whisper-small
"""
import os
import sys
import time

DEFAULT = os.environ.get("JARVIS_WHISPER_MODEL", "openai/whisper-base")
MODEL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT

print(f"downloading {MODEL} ...", flush=True)
t0 = time.time()

from transformers import WhisperForConditionalGeneration, WhisperProcessor  # noqa: E402

proc = WhisperProcessor.from_pretrained(MODEL)
model = WhisperForConditionalGeneration.from_pretrained(MODEL)
print(f"cached {MODEL} in {time.time()-t0:.1f}s", flush=True)
print(f"sample rate: {proc.feature_extractor.sampling_rate}", flush=True)
print(f"params: {sum(p.numel() for p in model.parameters())/1e6:.0f}M", flush=True)
print("\nSet JARVIS_WHISPER_MODEL (or stt.MODEL_NAME) to use a different size.", flush=True)
