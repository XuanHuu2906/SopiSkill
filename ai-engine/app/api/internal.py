"""FastAPI internal endpoints matching `contracts/internal-ai.yaml`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.pedagogy import extract_learner_profile
from app.agents.providers import ProviderConfigError, get_llm_provider
from app.agents.short_grader import grade_short_answer
from app.agents.tutor_agent import stream_tutor_turn
from app.core.sse import SSE_HEADERS
from app.db.session import get_db
from app.rag.embedding import EmbeddingConfigError
from app.rag.repository import RagRepository
from app.schemas.internal import (
    GradeShortRequest,
    GradeShortResponse,
    InterviewEvaluateRequest,
    InterviewEvaluateResponse,
    InterviewQuestionsRequest,
    InterviewQuestionsResponse,
    RagDeleteResponse,
    RagSearchRequest,
    RagSearchResponse,
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


@router.post("/interview/questions", response_model=InterviewQuestionsResponse)
async def interview_questions(body: InterviewQuestionsRequest) -> InterviewQuestionsResponse:
    provider = _get_provider_or_503()
    questions, usage = await provider.generate_interview_questions(body.topic, body.language)
    return InterviewQuestionsResponse(questions=questions, usage=usage)


@router.post("/interview/evaluate", response_model=InterviewEvaluateResponse)
async def interview_evaluate(body: InterviewEvaluateRequest) -> InterviewEvaluateResponse:
    profile = extract_learner_profile(body.answers, onboarding_profile=body.onboardingProfile)
    return InterviewEvaluateResponse(learnerProfile=profile)


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
