"""Wave 3 / P6.2 — Controlled feature-flag activation & production readiness guardrails.

Mục tiêu (Decision D7):
  - Mọi cờ tính năng tốn phí/mở rộng (`TUTOR_ENABLED`, `P50_ENABLED`, `RAG_ENABLED`)
    giữ mặc định OFF trong `config.py`.
  - Khi bật qua `.env` / compose override (đặc biệt ở `ENV=production`), kiểm tra
    các điều kiện tiên quyết bắt buộc:
      1. `TUTOR_ENABLED=true` với provider thật ⇒ phải đặt quota ngày cụ thể
         (`TUTOR_MESSAGES_PER_DAY > 0` và `TUTOR_TOKENS_PER_DAY > 0`, khuyến nghị
         30 lượt/ngày và 100.000 tokens/ngày) + Redis distributed rate-limit.
      2. `ENV=production` ⇒ bắt buộc `JWT_SECRET`, `COOKIE_SECURE=true`,
         `ALLOW_DEMO_HEADER=false`, và `REDIS_URL` cho rate-limit phân tán.
      3. `RAG_ENABLED=true` với `EMBEDDING_PROVIDER=hashing` ⇒ cảnh báo rõ rằng
         hashing chỉ là baseline lexical, chưa phải semantic embedding.
      4. `P52_EXPOSURE_ENABLED=true` ⇒ yêu cầu `JWT_SECRET` để ký HMAC exposure token.

Module này KHÔNG bao giờ in hay trả về secret/API key/URL chứa mật khẩu.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings

RECOMMENDED_TUTOR_MESSAGES_PER_DAY = 30
RECOMMENDED_TUTOR_TOKENS_PER_DAY = 100_000


@dataclass
class ActivationReport:
    ok: bool
    env: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    features: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "env": self.env,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "features": dict(self.features),
        }


def check_activation_readiness(settings: Settings | None = None) -> ActivationReport:
    cfg = settings or get_settings()
    env = (cfg.env or "development").strip().lower()
    is_prod = env == "production"
    provider = (cfg.llm_provider or "mock").strip().lower()
    rl_mode = (cfg.rate_limit_backend or "auto").strip().lower()
    has_redis = bool((cfg.redis_url or "").strip())
    distributed_rl = has_redis and rl_mode != "memory"

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Production core security invariants
    if is_prod:
        if not cfg.jwt_secret:
            errors.append("PROD_JWT_SECRET_MISSING")
        elif len(cfg.jwt_secret) < 32:
            warnings.append("PROD_JWT_SECRET_SHORT")
        if cfg.allow_demo_header:
            errors.append("PROD_DEMO_HEADER_ENABLED")
        if not cfg.cookie_secure:
            errors.append("PROD_COOKIE_SECURE_FALSE")
        if not distributed_rl:
            errors.append("PROD_DISTRIBUTED_RATE_LIMIT_REQUIRED")

    # 2. Tutor controlled activation guardrails (Decision D7)
    if cfg.tutor_enabled:
        if provider != "mock":
            missing_quota = (
                int(cfg.tutor_messages_per_day or 0) <= 0
                or int(cfg.tutor_tokens_per_day or 0) <= 0
            )
            if missing_quota:
                code = "TUTOR_DAILY_QUOTAS_REQUIRED"
                if is_prod:
                    errors.append(code)
                else:
                    warnings.append(code)
        if not distributed_rl:
            code = "TUTOR_DISTRIBUTED_RATE_LIMIT_RECOMMENDED"
            if is_prod:
                errors.append(code)
            else:
                warnings.append(code)

    # 3. RAG / Embedding honesty guardrail
    if cfg.rag_enabled:
        emb_provider = (cfg.embedding_provider or "").strip().lower()
        if emb_provider == "hashing":
            warnings.append("RAG_USING_HASHING_EMBEDDING_BASELINE")
        elif not cfg.embedding_configured:
            errors.append("RAG_EMBEDDING_NOT_CONFIGURED")

    # 4. P5.2 exposure token guardrail
    if cfg.p52_exposure_enabled and not cfg.jwt_secret:
        errors.append("P52_EXPOSURE_REQUIRES_JWT_SECRET")

    features = {
        "tutorEnabled": bool(cfg.tutor_enabled),
        "tutorToolsEnabled": bool(cfg.tutor_tools_enabled),
        "p50Enabled": bool(cfg.p50_enabled),
        "p52ExposureEnabled": bool(cfg.p52_exposure_enabled),
        "ragEnabled": bool(cfg.rag_enabled),
        "webIngestActive": bool(cfg.web_ingest_active),
        "ocrConfigured": bool(cfg.ocr_configured),
        "distributedRateLimit": distributed_rl,
    }

    return ActivationReport(
        ok=len(errors) == 0,
        env=env,
        errors=errors,
        warnings=warnings,
        features=features,
    )


def main() -> int:
    report = check_activation_readiness()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
