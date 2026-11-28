"""FastAPI internal endpoints matching `contracts/internal-ai.yaml`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import re

from app.agents.pedagogy import extract_learner_profile
from app.agents.planner_agent import PlannerMaxTurnsError, generate_proposal_with_tools
from app.agents.providers import ProviderConfigError, get_llm_provider
from app.agents.reel_compiler import compile_lesson_reel
from app.agents.short_grader import grade_short_answer
from app.agents.source_research_agent import SourceResearchMaxTurnsError, research_sources_with_agent
from app.agents.tts_provider import TtsConfigError, get_tts_provider
from app.agents.tutor_agent import stream_tutor_turn
from app.core.sse import SSE_HEADERS
from app.db.session import get_db
from app.rag.embedding import EmbeddingConfigError
from app.rag.repository import RagRepository
from app.rag.storage import SourceStorageError, get_source_storage
from app.schemas.internal import (
    GradeShortRequest,
    GradeShortResponse,
    InterviewEvaluateRequest,
    InterviewEvaluateResponse,
    InterviewQuestionsRequest,
    InterviewQuestionsResponse,
    ProposalGenerateRequest,
    ProposalGenerateResponse,
    RagDeleteResponse,
    RagSearchRequest,
    RagSearchResponse,
    ReelAudioDeleteResponse,
    ReelCompileRequest,
    ReelCompileResponse,
    ResearchedSourceOut,
    SourceResearchRequest,
    SourceResearchResponse,
    TutorStreamInternalRequest,
)

router = APIRouter(prefix="/internal", tags=["internal"])


def _get_provider_or_503():
    try:
        return get_llm_provider()
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc


def _get_rag_repo_or_503() -> RagRepository:
    try:
        return RagRepository()
    except EmbeddingConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "EMBEDDING_NOT_CONFIGURED", "message": str(exc)},
        ) from exc


@router.post("/sources/research", response_model=SourceResearchResponse)
async def sources_research(body: SourceResearchRequest) -> SourceResearchResponse:
    provider = _get_provider_or_503()
    try:
        res = await research_sources_with_agent(
            topic=body.topic,
            language=body.language,
            provider=provider,
            max_turns=body.maxTurns,
        )
    except SourceResearchMaxTurnsError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "max_turns", "message": str(exc)},
        ) from exc
    return SourceResearchResponse(
        sources=[ResearchedSourceOut(**s.to_dict()) for s in res.sources],
        toolsCalled=res.tools_called,
        rejectedUrls=res.rejected_urls,
        turnsUsed=res.turns_used,
        usage=res.usage,
    )


@router.post("/interview/questions", response_model=InterviewQuestionsResponse)
async def interview_questions(body: InterviewQuestionsRequest) -> InterviewQuestionsResponse:
    provider = _get_provider_or_503()
    questions, usage = await provider.generate_interview_questions(body.topic, body.language)
    return InterviewQuestionsResponse(questions=questions, usage=usage)


@router.post("/interview/evaluate", response_model=InterviewEvaluateResponse)
async def interview_evaluate(body: InterviewEvaluateRequest) -> InterviewEvaluateResponse:
    profile = extract_learner_profile(body.answers, onboarding_profile=body.onboardingProfile)
    return InterviewEvaluateResponse(learnerProfile=profile)


@router.post("/proposal/generate", response_model=ProposalGenerateResponse)
async def proposal_generate(body: ProposalGenerateRequest) -> ProposalGenerateResponse:
    provider = _get_provider_or_503()
    try:
        res = await generate_proposal_with_tools(
            topic=body.topic,
            language=body.language,
            learner_profile=body.learnerProfile or {"currentLevel": "beginner", "depth": "practical"},
            provider=provider,
            source_brief=body.sourceBrief,
        )
    except PlannerMaxTurnsError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "max_turns", "message": str(exc)},
        ) from exc
    return ProposalGenerateResponse(
        proposal=res.proposal,
        toolsCalled=res.tools_called,
        turnsUsed=res.turns_used,
        usage=res.usage,
    )


@router.post("/lessons/grade-short", response_model=GradeShortResponse)
async def lessons_grade_short(body: GradeShortRequest) -> GradeShortResponse:
    provider = _get_provider_or_503()
    return await grade_short_answer(body, provider)


@router.post("/tutor/stream")
async def tutor_stream(
    body: TutorStreamInternalRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    provider = _get_provider_or_503()
    rag_repo = _get_rag_repo_or_503()
    stream = stream_tutor_turn(body, provider=provider, rag_repo=rag_repo, db=db)
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/rag/search", response_model=RagSearchResponse)
async def rag_search(
    body: RagSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> RagSearchResponse:
    rag_repo = _get_rag_repo_or_503()
    mode, hits = await rag_repo.search(
        db,
        owner_id=body.ownerId,
        course_id=body.courseId,
        query=body.query,
        source_ids=body.sourceIds,
        top_k=body.topK,
    )
    return RagSearchResponse(retrievalMode=mode, chunks=hits)


@router.delete("/rag/users/{user_id}", response_model=RagDeleteResponse)
async def rag_delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> RagDeleteResponse:
    rag_repo = _get_rag_repo_or_503()
    deleted = await rag_repo.delete_by_user(db, user_id)
    return RagDeleteResponse(deletedChunks=deleted)


@router.delete("/rag/courses/{course_id}", response_model=RagDeleteResponse)
async def rag_delete_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
) -> RagDeleteResponse:
    rag_repo = _get_rag_repo_or_503()
    deleted = await rag_repo.delete_by_course(db, course_id)
    return RagDeleteResponse(deletedChunks=deleted)


@router.delete("/rag/sources/{source_id}", response_model=RagDeleteResponse)
async def rag_delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> RagDeleteResponse:
    rag_repo = _get_rag_repo_or_503()
    deleted = await rag_repo.delete_by_source(db, source_id)
    return RagDeleteResponse(deletedChunks=deleted)


_SAFE_FIGURE_CONTENT_TYPES = frozenset(
    {"image/webp", "image/png", "image/jpeg", "image/gif", "image/svg+xml"}
)


@router.get("/library/figures/{source_id}/{figure_id}")
async def get_library_figure_bytes(
    source_id: str,
    figure_id: str,
    ownerId: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve verified figure bytes from MinIO/S3 strictly after `core-api` enforces source authorization."""
    rag_repo = _get_rag_repo_or_503()
    fig = await rag_repo.get_figure(db, source_id=source_id, figure_id=figure_id, owner_id=ownerId)
    if fig is None:
        raise HTTPException(status_code=404, detail={"code": "FIGURE_NOT_FOUND", "message": "Figure not found."})

    ctype = str(fig.get("content_type") or "image/webp").lower()
    if ctype not in _SAFE_FIGURE_CONTENT_TYPES:
        ctype = "application/octet-stream"

    storage = get_source_storage()
    try:
        data = await storage.get_bytes(str(fig["minio_key"]))
    except SourceStorageError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "FIGURE_OBJECT_MISSING", "message": str(exc)}
        ) from exc

    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


_SAFE_REEL_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
_SAFE_REEL_CLIP_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}\.(wav|mp3|ogg|webm)$")
_AUDIO_MIME_BY_EXT = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
}


@router.post("/reels/compile", response_model=ReelCompileResponse)
async def reels_compile(body: ReelCompileRequest) -> ReelCompileResponse:
    provider = _get_provider_or_503()
    try:
        tts = get_tts_provider()
    except TtsConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "TTS_NOT_CONFIGURED", "message": str(exc)},
        ) from exc

    res = await compile_lesson_reel(
        course_id=body.courseId,
        lesson_id=body.lessonId,
        content_version=body.contentVersion,
        topic=body.topic,
        lesson_title=body.lessonTitle,
        lesson=body.lesson,
        language=body.language,
        available_figures=body.availableFigures,
        provider=provider,
        tts_provider=tts,
        prebuilt_script=body.prebuiltScript,
    )
    return ReelCompileResponse(
        reelId=res.reel_id,
        manifest=res.manifest,
        mediaCalls=res.media_calls,
        usage=res.usage,
    )


@router.get("/reels/audio/{course_id}/{lesson_id}/{clip_file}")
async def get_reel_audio_bytes(
    course_id: str,
    lesson_id: str,
    clip_file: str,
) -> Response:
    """Serve compiled Reel TTS audio from MinIO prefix `reels-audio/` strictly after `core-api` authz."""
    if (
        not _SAFE_REEL_SEGMENT_RE.match(course_id)
        or not _SAFE_REEL_SEGMENT_RE.match(lesson_id)
        or not _SAFE_REEL_CLIP_RE.match(clip_file)
    ):
        raise HTTPException(status_code=400, detail={"code": "INVALID_REEL_CLIP", "message": "Invalid clip path."})

    ext = clip_file.rsplit(".", 1)[-1].lower()
    ctype = _AUDIO_MIME_BY_EXT.get(ext, "audio/wav")
    key = f"reels-audio/{course_id}/{lesson_id}/{clip_file}"
    storage = get_source_storage()
    try:
        data = await storage.get_bytes(key)
    except SourceStorageError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "REEL_AUDIO_NOT_FOUND", "message": str(exc)},
        ) from exc

    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/reels/audio/{course_id}/{lesson_id}", response_model=ReelAudioDeleteResponse)
async def delete_lesson_reel_audio(course_id: str, lesson_id: str) -> ReelAudioDeleteResponse:
    if not _SAFE_REEL_SEGMENT_RE.match(course_id) or not _SAFE_REEL_SEGMENT_RE.match(lesson_id):
        raise HTTPException(status_code=400, detail={"code": "INVALID_REEL_PATH", "message": "Invalid path."})
    storage = get_source_storage()
    deleted = await storage.delete_prefix(f"reels-audio/{course_id}/{lesson_id}/")
    return ReelAudioDeleteResponse(deletedObjects=deleted)


@router.delete("/reels/audio/{course_id}", response_model=ReelAudioDeleteResponse)
async def delete_course_reel_audio(course_id: str) -> ReelAudioDeleteResponse:
    if not _SAFE_REEL_SEGMENT_RE.match(course_id):
        raise HTTPException(status_code=400, detail={"code": "INVALID_REEL_PATH", "message": "Invalid path."})
    storage = get_source_storage()
    deleted = await storage.delete_prefix(f"reels-audio/{course_id}/")
    return ReelAudioDeleteResponse(deletedObjects=deleted)
