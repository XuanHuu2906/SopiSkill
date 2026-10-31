"""Embedding service (P4.1) — interface ổn định, provider thay được.

Quyết định (người dùng phê duyệt 2026-10-31, phương án A offline-first):

  - Mặc định `hashing`: deterministic, **không network**, **không tải model**.
    Đây KHÔNG phải semantic embedding của Transformer; nó là baseline
    lexical/subword (token + char n-gram + fold dấu tiếng Việt) đủ để chứng minh
    pipeline retrieval/citation chạy đúng và để có số đo baseline trước khi chọn
    model thật. Không được gọi nó là "semantic".
  - `openai_compatible` chỉ dùng khi được cấu hình tường minh. Thiếu
    base_url/api_key/model/dimension ⇒ `EmbeddingNotConfigured` (fail-fast);
    **tuyệt đối không fallback im lặng về hashing** — thà lỗi rõ còn hơn trộn
    vector của hai không gian khác nhau.
  - `EmbeddingSpec(provider, model, dimension, version)` đi kèm mọi vector đã
    lưu. Retrieval chỉ dùng vector khớp spec đang cấu hình, nên đổi model/version
    không bao giờ trộn vector cũ với mới.

Thay bằng multilingual embedding hoặc pgvector sau này chỉ cần thêm provider /
backend mới: `retrieval_service` không phụ thuộc implementation.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings

# Từ dừng tiếng Việt/Anh — giảm nhiễu cho baseline hashing.
_STOPWORDS = frozenset(
    """
    và hoặc nhưng của cho với từ trong trên dưới ngoài khi nếu thì là các những
    một hai ba có không được bị đã đang sẽ này đó kia ấy để về theo tại vì do nên
    the a an of for to in on at and or but with from by is are was were be been
    this that these those as it its if then than so such can could should would
    """.split()
)

_TOKEN_RE = re.compile(r"[0-9a-zA-ZÀ-ỹ]+", re.UNICODE)


class EmbeddingError(Exception):
    """Lỗi embedding có mã ổn định, message an toàn (không lộ key/nội dung)."""

    code = "EMBEDDING_ERROR"
    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class EmbeddingNotConfigured(EmbeddingError):
    code = "EMBEDDING_NOT_CONFIGURED"


class EmbeddingTransientError(EmbeddingError):
    code = "EMBEDDING_TRANSIENT"
    retryable = True


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimension: int
    version: str

    @property
    def tuple(self) -> tuple[str, str, int, str]:
        return (self.provider, self.model, self.dimension, self.version)

    def describe(self) -> str:
        return f"{self.provider}/{self.model}/d{self.dimension}/{self.version}"


class EmbeddingProvider(Protocol):
    spec: EmbeddingSpec

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").split())


def fold_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt để truy vấn không dấu vẫn khớp (chỉ dùng cho hashing)."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def tokenize(text: str) -> list[str]:
    return [tok.casefold() for tok in _TOKEN_RE.findall(text or "") if tok]


def _hash_index(token: str, dimension: int) -> tuple[int, float]:
    """Ánh xạ token → (index, sign) bằng blake2b; sign giảm thiên lệch dương."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dimension, (1.0 if (value >> 63) & 1 else -1.0)


def hashing_embed(text: str, *, dimension: int, ngram_max: int = 2, char_ngram: int = 3) -> list[float]:
    """Embedding hashing deterministic (signed hashing trick).

    Đặc tính đã biết:
      - Cùng text ⇒ cùng vector (ổn định qua process/restart).
      - Bag-of-features: **không** hiểu ngữ nghĩa/đồng nghĩa như model thật.
      - Có collision (dimension hữu hạn); dimension lớn hơn ⇒ ít collision hơn.
    """
    if dimension <= 0:
        raise EmbeddingNotConfigured("Dimension embedding phải > 0.")
    vector = [0.0] * dimension
    tokens = tokenize(fold_diacritics(text))
    if not tokens:
        return vector

    features: list[tuple[str, float]] = []
    for token in tokens:
        if token in _STOPWORDS:
            continue
        if len(token) < 2:
            continue
        # Unigram + bigram token (giữ trật tự cục bộ).
        features.append((f"w:{token}", 1.0))
        padded = f"^{token}$"
        for n in range(2, max(2, char_ngram) + 1):
            if len(padded) < n:
                break
            for start in range(len(padded) - n + 1):
                features.append((f"c:{padded[start:start + n]}", 0.5))

    for i in range(len(tokens) - 1):
        left, right = tokens[i], tokens[i + 1]
        if left in _STOPWORDS or right in _STOPWORDS:
            continue
        features.append((f"b:{left}_{right}", 0.8))

    if not features:
        # Toàn stopword/1 ký tự: vẫn trả vector có tín hiệu để không thành zero.
        features = [(f"w:{tok}", 1.0) for tok in tokens]

    for feature, weight in features:
        index, sign = _hash_index(feature, dimension)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class HashingEmbeddingProvider:
    """Baseline offline. Không network, không model, không chi phí."""

    def __init__(self, spec: EmbeddingSpec, *, ngram_max: int = 2, char_ngram: int = 3) -> None:
        self.spec = spec
        self._ngram_max = ngram_max
        self._char_ngram = char_ngram

    def _embed(self, text: str) -> list[float]:
        return hashing_embed(
            text,
            dimension=self.spec.dimension,
            ngram_max=self._ngram_max,
            char_ngram=self._char_ngram,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OpenAICompatibleEmbeddingProvider:
    """Adapter thật (MẶC ĐỊNH TẮT) cho endpoint `/embeddings` kiểu OpenAI.

    Không tự bật: cần `EMBEDDING_BASE_URL` + `EMBEDDING_API_KEY` +
    `EMBEDDING_MODEL` + `EMBEDDING_DIMENSION`. Key chỉ tồn tại server-side,
    không log, không trả ra response. Dimension trả về của provider **phải khớp**
    cấu hình, nếu không ⇒ lỗi cấu hình (không lưu vector sai spec).
    """

    def __init__(self, spec: EmbeddingSpec, *, base_url: str, api_key: str, timeout: float) -> None:
        self.spec = spec
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = max(1.0, float(timeout))

    async def _request(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        payload = {"model": self.spec.model, "input": inputs}
        url = f"{self._base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise EmbeddingTransientError("Embedding provider hết thời gian chờ.") from exc
        except httpx.HTTPError as exc:  # mạng lỗi — thử lại được
            raise EmbeddingTransientError("Không gọi được embedding provider.") from exc

        if response.status_code == 429:
            raise EmbeddingTransientError("Embedding provider giới hạn tần suất.")
        if response.status_code >= 500:
            raise EmbeddingTransientError("Embedding provider lỗi tạm thời.")
        if response.status_code >= 400:
            # KHÔNG đưa body vào message (có thể chứa input người dùng).
            raise EmbeddingError(
                f"Embedding provider từ chối yêu cầu (HTTP {response.status_code})."
            )

        try:
            body = response.json()
            rows = body["data"]
            ordered = sorted(rows, key=lambda item: int(item.get("index", 0)))
            vectors = [[float(x) for x in row["embedding"]] for row in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding provider trả response sai định dạng.") from exc

        if len(vectors) != len(inputs):
            raise EmbeddingError("Embedding provider trả thiếu vector.")
        for vector in vectors:
            if len(vector) != self.spec.dimension:
                raise EmbeddingError(
                    "Dimension embedding provider trả về không khớp cấu hình."
                )
        return [_l2_normalize(vector) for vector in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        settings = get_settings()
        batch = max(1, int(settings.embedding_batch_size or 32))
        results: list[list[float]] = []
        for start in range(0, len(texts), batch):
            results.extend(await self._request(texts[start : start + batch]))
        return results

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._request([text])
        if not vectors:
            raise EmbeddingError("Embedding provider không trả vector cho truy vấn.")
        return vectors[0]


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def active_spec() -> EmbeddingSpec:
    provider, model, dimension, version = get_settings().embedding_spec
    return EmbeddingSpec(
        provider=provider, model=model, dimension=dimension, version=version
    )


def get_embedding_provider() -> EmbeddingProvider:
    """Điểm thay DUY NHẤT của embedding. Raise nếu cấu hình không hợp lệ.

    Không bao giờ fallback ngầm: provider lạ/thiếu cấu hình ⇒ lỗi rõ ràng.
    """
    settings = get_settings()
    if not settings.embedding_enabled:
        raise EmbeddingNotConfigured("Embedding đang bị tắt trên server.")

    spec = active_spec()
    provider = spec.provider
    if provider == "hashing":
        if spec.dimension <= 0:
            raise EmbeddingNotConfigured("EMBEDDING_DIMENSION phải > 0.")
        return HashingEmbeddingProvider(
            spec,
            ngram_max=int(settings.embedding_ngram_max or 2),
            char_ngram=int(settings.embedding_char_ngram or 3),
        )
    if provider in ("openai_compatible", "openai"):
        if not settings.embedding_configured:
            raise EmbeddingNotConfigured(
                "Embedding provider 'openai_compatible' thiếu base URL/API key/model/dimension."
            )
        return OpenAICompatibleEmbeddingProvider(
            spec,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            timeout=settings.embedding_timeout_seconds,
        )
    raise EmbeddingNotConfigured(
        f"Embedding provider '{provider}' chưa được hỗ trợ. Hợp lệ: hashing, openai_compatible."
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine cho vector đã normalize (fallback tính norm nếu chưa)."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    if abs(norm_left - 1.0) > 1e-9 or abs(norm_right - 1.0) > 1e-9:
        dot = dot / (norm_left * norm_right)
    return max(-1.0, min(1.0, dot))


# ---------------------------------------------------------------------------
# Persistence: embed source chunks theo spec hiện hành (idempotent)
# ---------------------------------------------------------------------------

EMBEDDING_FALLBACK_MESSAGE = (
    "Chưa thể tạo embedding cho tài liệu. Câu trả lời sẽ không có trích dẫn đã "
    "kiểm chứng cho tới khi tài liệu được xử lý xong."
)


async def chunks_missing_embedding(db, *, source_id=None, document_id=None, limit: int = 500):
    """Chunk CHƯA có vector đúng spec hiện hành (hoặc vector stale).

    Trả list `(SourceChunk,)`. Điều kiện:
      - Không có row embedding cùng (provider, model, dimension, version), HOẶC
      - row đó có `text_hash` khác chunk hiện tại ⇒ đã stale, phải embed lại.
    """
    from sqlalchemy import select

    from app.models import SourceChunk, SourceChunkEmbedding

    spec = active_spec()
    current = (
        select(SourceChunkEmbedding.chunk_id)
        .where(
            SourceChunkEmbedding.provider == spec.provider,
            SourceChunkEmbedding.model == spec.model,
            SourceChunkEmbedding.dimension == spec.dimension,
            SourceChunkEmbedding.version == spec.version,
            SourceChunkEmbedding.text_hash == SourceChunk.text_hash,
        )
        .scalar_subquery()
    )

    stmt = select(SourceChunk).where(SourceChunk.id.not_in(current))
    if source_id is not None:
        stmt = stmt.where(SourceChunk.source_id == source_id)
    if document_id is not None:
        stmt = stmt.where(SourceChunk.document_id == document_id)
    stmt = stmt.order_by(SourceChunk.chunk_index).limit(limit)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


async def embed_chunks(db, chunks, *, provider=None) -> int:
    """Embed `chunks` theo spec hiện hành; upsert idempotent. Trả số row ghi.

    Không commit — caller quyết định transaction. Upsert theo
    UNIQUE(chunk_id, provider, model, dimension, version) nên retry/parallel
    không sinh duplicate. Vector stale được **thay** (cùng spec, text_hash mới).
    """
    from sqlalchemy import select

    from app.models import SourceChunkEmbedding

    if not chunks:
        return 0
    provider = provider or get_embedding_provider()
    spec = provider.spec
    texts = [chunk.text for chunk in chunks]
    vectors = await provider.embed_documents(texts)
    if len(vectors) != len(chunks):
        raise EmbeddingError("Số vector trả về không khớp số chunk.")

    written = 0
    for chunk, vector in zip(chunks, vectors):
        if len(vector) != spec.dimension:
            raise EmbeddingError("Dimension vector không khớp spec đang hoạt động.")
        existing = (
            await db.execute(
                select(SourceChunkEmbedding).where(
                    SourceChunkEmbedding.chunk_id == chunk.id,
                    SourceChunkEmbedding.provider == spec.provider,
                    SourceChunkEmbedding.model == spec.model,
                    SourceChunkEmbedding.dimension == spec.dimension,
                    SourceChunkEmbedding.version == spec.version,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                SourceChunkEmbedding(
                    chunk_id=chunk.id,
                    source_id=chunk.source_id,
                    provider=spec.provider,
                    model=spec.model,
                    dimension=spec.dimension,
                    version=spec.version,
                    text_hash=chunk.text_hash,
                    vector=vector,
                )
            )
        else:
            existing.text_hash = chunk.text_hash
            existing.vector = vector
        written += 1
    return written


async def embed_source_chunks(db, source_id, *, limit: int = 500) -> int:
    """Embed mọi chunk còn thiếu/stale của MỘT nguồn. Dùng khi ingest xong."""
    if not get_settings().embedding_enabled:
        return 0
    chunks = await chunks_missing_embedding(db, source_id=source_id, limit=limit)
    return await embed_chunks(db, chunks)


async def embedding_coverage(db, *, source_id=None) -> dict:
    """Số chunk có vector đúng spec hiện hành — phục vụ honesty/UI/eval."""
    from sqlalchemy import func, select

    from app.models import SourceChunk, SourceChunkEmbedding

    total_stmt = select(func.count()).select_from(SourceChunk)
    if source_id is not None:
        total_stmt = total_stmt.where(SourceChunk.source_id == source_id)
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    spec = active_spec()
    covered_stmt = (
        select(func.count())
        .select_from(SourceChunk)
        .join(
            SourceChunkEmbedding,
            (SourceChunkEmbedding.chunk_id == SourceChunk.id)
            & (SourceChunkEmbedding.provider == spec.provider)
            & (SourceChunkEmbedding.model == spec.model)
            & (SourceChunkEmbedding.dimension == spec.dimension)
            & (SourceChunkEmbedding.version == spec.version)
            & (SourceChunkEmbedding.text_hash == SourceChunk.text_hash),
        )
    )
    if source_id is not None:
        covered_stmt = covered_stmt.where(SourceChunk.source_id == source_id)
    covered = int((await db.execute(covered_stmt)).scalar_one() or 0)

    return {
        "total": total,
        "embedded": covered,
        "pending": max(0, total - covered),
        "spec": active_spec().describe(),
        "provider": active_spec().provider,
        "embeddingEnabled": bool(get_settings().embedding_enabled),
    }
