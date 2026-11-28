"""Dedicated torch-free CPU VieNeu-TTS HTTP microservice for SopiSkill Narrated Reels."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import logging
import os
import threading
import urllib.parse
import wave
from typing import Any

import numpy as np
import soxr
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logger = logging.getLogger("sopiskill.tts_vieneu")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_ENGINE_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()
_ENGINE: Any = None
_VOICES: list[tuple[str, str]] = []


def _target_sample_rate() -> int:
    raw = int(os.getenv("VIENEU_SAMPLE_RATE", "24000") or "24000")
    return raw if raw in (8000, 16000, 24000, 48000) else 24000


def _get_engine() -> Any:
    global _ENGINE, _VOICES
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        from vieneu import Vieneu  # type: ignore[import-not-found]

        backend = (os.getenv("VIENEU_BACKEND", "onnx") or "onnx").strip()
        precision = (os.getenv("VIENEU_PRECISION", "int8") or "int8").strip()
        mode = (os.getenv("VIENEU_MODE", "") or "").strip()
        kwargs: dict[str, Any] = {}
        if mode:
            kwargs["mode"] = mode
        else:
            kwargs["backend"] = backend
            kwargs["precision"] = precision
        logger.info("loading_vieneu_engine kwargs=%s", kwargs)
        eng = Vieneu(**kwargs)
        try:
            raw_voices = eng.list_preset_voices() or []
            _VOICES = [(str(item[0]), str(item[1])) for item in raw_voices if len(item) >= 2]
        except Exception as exc:  # noqa: BLE001
            logger.warning("vieneu_list_voices_failed err=%s", exc)
            _VOICES = []
        _ENGINE = eng
        logger.info("vieneu_engine_ready preset_voices=%d", len(_VOICES))
        return _ENGINE


def _resolve_voice(eng: Any, requested: str | None) -> str | None:
    req = (requested or "").strip()
    if req and _VOICES:
        for label, vid in _VOICES:
            if req.casefold() in (label.casefold(), vid.casefold()):
                return vid
    default_voice = (os.getenv("VIENEU_DEFAULT_VOICE", "") or "").strip()
    if default_voice and _VOICES:
        for label, vid in _VOICES:
            if default_voice.casefold() in (label.casefold(), vid.casefold()):
                return vid
    return _VOICES[0][1] if _VOICES else None


def _synthesize_wav_sync(text: str, voice: str | None, requested_rate: int | None) -> tuple[bytes, int, str]:
    eng = _get_engine()
    resolved_voice = _resolve_voice(eng, voice)
    native_sr = int(getattr(eng, "sample_rate", 48000) or 48000)
    target_sr = requested_rate if requested_rate in (8000, 16000, 24000, 48000) else _target_sample_rate()

    with _INFER_LOCK:
        if resolved_voice:
            audio = eng.infer(text=text, voice=resolved_voice)
        else:
            audio = eng.infer(text=text)

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        raise RuntimeError("VieNeu returned empty waveform")

    if target_sr != native_sr:
        samples = soxr.resample(samples, native_sr, target_sr, quality="HQ").astype(np.float32)

    pcm16 = (samples * 32767.0).clip(-32768, 32767).astype("<i2")
    frame_count = int(pcm16.shape[0])
    duration_ms = max(400, int(round((frame_count / float(target_sr)) * 1000.0)))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_sr)
        wf.writeframes(pcm16.tobytes())

    return buf.getvalue(), duration_ms, (resolved_voice or "default")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await asyncio.to_thread(_get_engine)
    yield


app = FastAPI(title="SopiSkill VieNeu-TTS Service", version="1.0.0", lifespan=_lifespan)


class SpeechRequest(BaseModel):
    model: str = "vieneu-v3-turbo"
    input: str = Field(..., min_length=1, max_length=4000)
    voice: str | None = None
    language: str | None = "vi"
    response_format: str = "wav"
    sample_rate: int | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "loaded": _ENGINE is not None, "voices": len(_VOICES)}


@app.get("/v1/voices")
def list_voices() -> dict[str, Any]:
    return {"voices": [{"label": lbl, "id": vid} for lbl, vid in _VOICES]}


@app.post("/v1/audio/speech")
async def create_speech(req: SpeechRequest) -> Response:
    try:
        wav_bytes, duration_ms, used_voice = await asyncio.to_thread(
            _synthesize_wav_sync,
            req.input.strip(),
            req.voice,
            req.sample_rate,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("vieneu_synthesis_failed")
        raise HTTPException(status_code=500, detail=f"VieNeu synthesis failed: {exc}") from exc

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Audio-Duration-Ms": str(duration_ms),
            "X-VieNeu-Voice": urllib.parse.quote(used_voice, safe="-_."),
        },
    )
