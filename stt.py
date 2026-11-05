"""Local speech-to-text for the Jarvis mic.

The browser records compressed audio (Chrome gives us webm/opus) and posts it
to /transcribe. ffmpeg decodes that to 16 kHz mono PCM, and a locally cached
Whisper model transcribes it. Nothing leaves the machine.

Whisper's weights are fetched once by _fetch_whisper.py and then live in the
Hugging Face cache, so this works offline afterwards.
"""

import io
import os
import subprocess
import tempfile
import threading
import wave

MODEL_NAME = os.environ.get("JARVIS_WHISPER_MODEL", "openai/whisper-base")
FFMPEG_BIN = os.environ.get("JARVIS_FFMPEG", "ffmpeg")

_model = None
_processor = None
_load_lock = threading.Lock()


class STTUnavailable(RuntimeError):
    """Raised when the local model or ffmpeg is not usable."""


def _ensure_model():
    """Load Whisper once, lazily. Returns (model, processor)."""
    global _model, _processor
    if _model is not None:
        return _model, _processor
    with _load_lock:
        if _model is None:
            try:
                import torch
                from transformers import WhisperForConditionalGeneration, WhisperProcessor
            except ImportError as e:
                raise STTUnavailable(
                    f"Whisper dependencies missing ({e}). "
                    "Install torch + transformers to enable local speech input."
                ) from e
            try:
                _processor = WhisperProcessor.from_pretrained(MODEL_NAME)
                _model = WhisperForConditionalGeneration.from_pretrained(MODEL_NAME)
                _model.eval()
                # Keep CPU thread usage sane on a low-power laptop CPU.
                torch.set_num_threads(max(1, (os.cpu_count() or 4)))
            except Exception as e:
                raise STTUnavailable(
                    f"Could not load {MODEL_NAME} ({e}). "
                    "Run python _fetch_whisper.py to download the weights."
                ) from e
    return _model, _processor


def decode_to_wav(audio_bytes: bytes, suffix: str = ".webm") -> bytes:
    """Decode browser audio (any format ffmpeg understands) to 16 kHz mono WAV."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in" + (suffix or ".webm"))
        dst = os.path.join(td, "out.wav")
        with open(src, "wb") as f:
            f.write(audio_bytes)
        try:
            proc = subprocess.run(
                [FFMPEG_BIN, "-y", "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", dst],
                capture_output=True, timeout=60,
            )
        except FileNotFoundError as e:
            raise STTUnavailable(
                f"ffmpeg not found at '{FFMPEG_BIN}'. Install ffmpeg or set JARVIS_FFMPEG."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise STTUnavailable("ffmpeg timed out decoding the audio.") from e
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace")[-400:]
            raise STTUnavailable(f"ffmpeg could not decode the audio: {tail}")
        with open(dst, "rb") as f:
            return f.read()


def transcribe(audio_bytes: bytes, suffix: str = ".webm", language: str = "en") -> str:
    """Transcribe browser audio bytes to text."""
    if not audio_bytes:
        return ""
    model, processor = _ensure_model()
    wav = decode_to_wav(audio_bytes, suffix)

    import numpy as np
    import torch

    with wave.open(io.BytesIO(wav), "rb") as w:
        frames = w.readframes(w.getnframes())
        sample_rate = w.getframerate()

    pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if pcm.size == 0:
        return ""

    inputs = processor.feature_extractor(
        pcm, sampling_rate=sample_rate, return_tensors="pt", return_attention_mask=True
    )

    # Canonical Whisper generation call: build the decoder prompt ids from the
    # processor instead of passing language/task, which makes transformers
    # warn about a conflict with the model's own forced_decoder_ids.
    decoder_prompt = processor.get_decoder_prompt_ids(language=language, task="transcribe")
    with torch.no_grad():
        ids = model.generate(
            inputs.input_features,
            attention_mask=inputs.attention_mask,
            forced_decoder_ids=decoder_prompt,
        )
    return processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def status() -> dict:
    """Lightweight health check for the UI."""
    info = {"model": MODEL_NAME, "loaded": _model is not None, "available": True, "error": None}
    try:
        _ensure_model()
    except STTUnavailable as e:
        info["available"] = False
        info["error"] = str(e)
    return info
