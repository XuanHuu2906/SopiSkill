"""Provider-neutral TTS abstraction for Phase 10A Narrated Reel Engine.

Implementations:
  1. `MockTTSProvider` (default, 0 cost, 100% offline): synthesizes a valid minimal PCM WAV clip
     with soft audible envelope (or near-silent tone) and accurate word-level timestamps `words[]`.
  2. `LocalWordBoundaryTTSProvider` (`TTS_PROVIDER=local|edge`): optional zero-key adapter backed
     by `edge-tts` word-boundary events for Vietnamese (`vi-VN`) and English (`en-US`), failing fast
     with `TtsConfigError` if `edge-tts` is not installed.
  3. `OpenAICompatibleTTSProvider` (`TTS_PROVIDER=openai_compatible`): Cloud TTS adapter calling
     `/v1/audio/speech` with `TTS_API_KEY`, failing fast when credentials are missing.
"""

from __future__ import annotations

import io
import math
import re
import struct
import wave
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings

_WORD_SPLIT_RE = re.compile(r"\S+")


class TtsConfigError(RuntimeError):
    """Raised fail-fast when a non-mock TTS provider is enabled without required setup."""


class TtsSynthesisError(RuntimeError):
    """Raised when an upstream TTS provider fails during synthesis."""


@dataclass(frozen=True)
class WordTiming:
    text: str
    startMs: int
    endMs: int

    def to_dict(self) -> dict[str, int | str]:
        return {"text": self.text, "startMs": self.startMs, "endMs": self.endMs}


@dataclass(frozen=True)
class TtsSynthesisResult:
    audio_bytes: bytes
    content_type: str
    file_ext: str
    duration_ms: int
    words: list[WordTiming]
    provider: str
    voice: str


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, *, language: str = "vi", voice: str | None = None) -> TtsSynthesisResult: ...


def estimate_word_timings(text: str, total_duration_ms: int | None = None) -> tuple[list[WordTiming], int]:
    """Compute deterministic monotonic word timings `[startMs, endMs]` for karaoke captions."""
    tokens = _WORD_SPLIT_RE.findall((text or "").strip())
    if not tokens:
        dur = max(600, total_duration_ms or 800)
        return [], dur

    weights = [max(2.0, float(len(re.sub(r"[^\w]", "", tok))) + 1.5) for tok in tokens]
    weight_sum = sum(weights)
    # Natural narration pace ~145 wpm (~410ms/word average), clamped for short/long utterances.
    if total_duration_ms is None or total_duration_ms <= 0:
        inferred_ms = int(round(max(1200.0, min(28_000.0, len(tokens) * 380.0))))
    else:
        inferred_ms = max(600, int(total_duration_ms))

    lead_in_ms = 60
    usable_ms = max(400, inferred_ms - lead_in_ms * 2)
    cursor = float(lead_in_ms)
    out: list[WordTiming] = []
    for idx, (tok, w) in enumerate(zip(tokens, weights, strict=True)):
        span = usable_ms * (w / weight_sum)
        start_ms = int(round(cursor))
        cursor += span
        end_ms = inferred_ms - lead_in_ms if idx == len(tokens) - 1 else max(start_ms + 40, int(round(cursor)))
        out.append(WordTiming(text=tok, startMs=start_ms, endMs=end_ms))

    return out, inferred_ms


def _generate_minimal_wav(duration_ms: int, *, sample_rate: int = 8000) -> bytes:
    """Generate a compact, standards-compliant 16-bit mono RIFF PCM WAV playable in all browsers."""
    clamped_ms = max(400, min(duration_ms, 20_000))
    frame_count = int(sample_rate * (clamped_ms / 1000.0))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Very soft warm low-amplitude pulse at scene onset so <audio> decodes cleanly without harsh noise
        frames = bytearray(frame_count * 2)
        fade_frames = min(frame_count, int(sample_rate * 0.12))
        for i in range(fade_frames):
            env = math.sin(math.pi * (i / max(1, fade_frames)))
            sample = int(round(320 * env * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate))))
            struct.pack_into("<h", frames, i * 2, sample)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


class MockTTSProvider:
    """Deterministic zero-cost TTS provider generating valid WAV + exact word timings for CI/E2E."""

    name = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self._cfg = settings or get_settings()

    async def synthesize(self, text: str, *, language: str = "vi", voice: str | None = None) -> TtsSynthesisResult:
        selected_voice = voice or (self._cfg.tts_voice_en if language == "en" else self._cfg.tts_voice_vi)
        words, duration_ms = estimate_word_timings(text)
        wav_bytes = _generate_minimal_wav(duration_ms)
        return TtsSynthesisResult(
            audio_bytes=wav_bytes,
            content_type="audio/wav",
            file_ext="wav",
            duration_ms=duration_ms,
            words=words,
            provider=self.name,
            voice=f"mock:{selected_voice}",
        )


class LocalWordBoundaryTTSProvider:
    """Free local/edge neural TTS adapter (`edge-tts`) capturing real `WordBoundary` events for vi/en."""

    name = "local_edge"

    def __init__(self, settings: Settings | None = None) -> None:
        self._cfg = settings or get_settings()

    async def synthesize(self, text: str, *, language: str = "vi", voice: str | None = None) -> TtsSynthesisResult:
        try:
            import edge_tts  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TtsConfigError(
                "TTS_PROVIDER=local/edge requires optional package `edge-tts` to be installed."
            ) from exc

        selected_voice = voice or (self._cfg.tts_voice_en if language == "en" else self._cfg.tts_voice_vi)
        communicator = edge_tts.Communicate(text or " ", selected_voice)
        audio_chunks: list[bytes] = []
        raw_words: list[WordTiming] = []
        try:
            async for chunk in communicator.stream():
                ctype = chunk.get("type")
                if ctype == "audio":
                    audio_chunks.append(chunk["data"])
                elif ctype == "WordBoundary":
                    start_ms = int(chunk.get("offset", 0) // 10_000)
                    dur_ms = max(40, int(chunk.get("duration", 0) // 10_000))
                    raw_words.append(
                        WordTiming(text=str(chunk.get("text") or ""), startMs=start_ms, endMs=start_ms + dur_ms)
                    )
        except Exception as exc:
            raise TtsSynthesisError(f"Edge TTS synthesis failed ({type(exc).__name__}): {exc}") from exc

        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            raise TtsSynthesisError("Edge TTS returned empty audio stream.")
        if raw_words:
            duration_ms = max(800, raw_words[-1].endMs + 150)
            words = raw_words
        else:
            words, duration_ms = estimate_word_timings(text)
        return TtsSynthesisResult(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            file_ext="mp3",
            duration_ms=duration_ms,
            words=words,
            provider=self.name,
            voice=selected_voice,
        )


class OpenAICompatibleTTSProvider:
    """Cloud OpenAI-compatible `/v1/audio/speech` TTS adapter (fail-fast without `TTS_API_KEY`)."""

    name = "openai_compatible"

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        if not cfg.tts_api_key.strip():
            raise TtsConfigError("TTS_API_KEY is required when TTS_PROVIDER=openai_compatible.")
        self._cfg = cfg
        self._base_url = (cfg.tts_base_url or "https://api.openai.com/v1").rstrip("/")

    async def synthesize(self, text: str, *, language: str = "vi", voice: str | None = None) -> TtsSynthesisResult:
        selected_voice = voice or ("alloy" if language == "en" else "nova")
        headers = {
            "Authorization": f"Bearer {self._cfg.tts_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._cfg.tts_model or "tts-1",
            "voice": selected_voice,
            "input": (text or " ")[:4000],
            "response_format": "mp3",
        }
        try:
            async with httpx.AsyncClient(timeout=self._cfg.tts_timeout_seconds) as client:
                resp = await client.post(f"{self._base_url}/audio/speech", headers=headers, json=payload)
                resp.raise_for_status()
                audio_bytes = resp.content
        except Exception as exc:
            raise TtsSynthesisError(f"Cloud TTS request failed ({type(exc).__name__}): {exc}") from exc

        words, duration_ms = estimate_word_timings(text)
        return TtsSynthesisResult(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            file_ext="mp3",
            duration_ms=duration_ms,
            words=words,
            provider=self.name,
            voice=selected_voice,
        )


def get_tts_provider(settings: Settings | None = None) -> TTSProvider:
    cfg = settings or get_settings()
    kind = (cfg.tts_provider or "mock").strip().lower()
    if kind == "mock":
        return MockTTSProvider(cfg)
    if kind in {"local", "edge", "local_edge"}:
        return LocalWordBoundaryTTSProvider(cfg)
    if kind in {"openai_compatible", "cloud"}:
        return OpenAICompatibleTTSProvider(cfg)
    raise TtsConfigError(f"Unsupported TTS_PROVIDER: {kind!r}")
