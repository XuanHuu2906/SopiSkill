"""Embedding providers for `ai-engine` (offline `hashing` baseline default + opt-in `openai_compatible`)."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings

_STOPWORDS = frozenset(
    """
    và hoặc nhưng của cho với từ trong trên dưới ngoài khi nếu thì là các những
    một hai ba có không được bị đã đang sẽ này đó kia ấy để về theo tại vì do nên
    the a an of for to in on at and or but with from by is are was were be been
    this that these those as it its if then than so such can could should would
    """.split()
)
_TOKEN_RE = re.compile(r"[0-9a-zA-ZÀ-ỹ]+", re.UNICODE)


class EmbeddingConfigError(RuntimeError):
    """Fail-fast error when semantic embedding provider is selected without valid config."""


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimension: int
    version: str


class EmbeddingProvider(Protocol):
    spec: EmbeddingSpec

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def fold_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def tokenize(text: str) -> list[str]:
    return [tok.casefold() for tok in _TOKEN_RE.findall(text or "") if tok]


def _hash_index(token: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dimension, (1.0 if (value >> 63) & 1 else -1.0)


def hashing_embed(text: str, *, dimension: int = 256) -> list[float]:
    if dimension <= 0:
        raise EmbeddingConfigError("Embedding dimension must be > 0.")
    vec = [0.0] * dimension
    tokens = tokenize(fold_diacritics(text))
    if not tokens:
        return vec

    features: list[tuple[str, float]] = []
    for tok in tokens:
        if tok in _STOPWORDS or len(tok) < 2:
            continue
        features.append((f"w:{tok}", 1.0))
        padded = f"^{tok}$"
        for n in (2, 3):
            if len(padded) >= n:
                for start in range(len(padded) - n + 1):
                    features.append((f"c:{padded[start:start + n]}", 0.5))

    for i in range(len(tokens) - 1):
        left, right = tokens[i], tokens[i + 1]
        if left not in _STOPWORDS and right not in _STOPWORDS:
            features.append((f"b:{left}_{right}", 0.8))

    if not features:
        features = [(f"w:{t}", 1.0) for t in tokens]

    for feat, weight in features:
        idx, sign = _hash_index(feat, dimension)
        vec[idx] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


class HashingEmbeddingProvider:
    """Zero-cost deterministic offline baseline (never misrepresented as neural semantic)."""

    def __init__(self, spec: EmbeddingSpec) -> None:
        self.spec = spec

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [hashing_embed(t, dimension=self.spec.dimension) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return hashing_embed(text, dimension=self.spec.dimension)


class OpenAICompatibleEmbeddingProvider:
    """Semantic embedding adapter (fail-fast, never silently falls back to hashing)."""

    def __init__(self, settings: Settings, spec: EmbeddingSpec) -> None:
        self.spec = spec
        self._base_url = (settings.embedding_base_url or "").rstrip("/")
        self._api_key = (settings.embedding_api_key or "").strip()
        self._timeout = float(settings.embedding_timeout_seconds)
        if not self._base_url or not self._api_key or not spec.model:
            raise EmbeddingConfigError(
                "EMBEDDING_PROVIDER=openai_compatible requires EMBEDDING_BASE_URL, "
                "EMBEDDING_API_KEY, and EMBEDDING_MODEL."
            )

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {"model": self.spec.model, "input": inputs}
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        rows = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [list(map(float, row["embedding"])) for row in rows]
        for vec in vectors:
            if len(vec) != self.spec.dimension:
                raise EmbeddingConfigError(
                    f"Embedding dimension mismatch: expected {self.spec.dimension}, got {len(vec)}."
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts) if texts else []

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text])
        return vectors[0] if vectors else [0.0] * self.spec.dimension


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    cfg = settings or get_settings()
    kind = (cfg.embedding_provider or "hashing").strip().lower()
    spec = EmbeddingSpec(
        provider=kind,
        model=cfg.embedding_model,
        dimension=int(cfg.embedding_dimension),
        version=cfg.embedding_version,
    )
    if kind == "hashing":
        return HashingEmbeddingProvider(spec)
    if kind == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(cfg, spec)
    raise EmbeddingConfigError(f"Unsupported EMBEDDING_PROVIDER: {kind!r}")
