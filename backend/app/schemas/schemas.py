from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------- Proposal structured output (provider → DB) ----------
class ProposalUnit(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    blurb: str = Field(default="", max_length=400)
    lessonTitles: list[str] = Field(min_length=1, max_length=12)


class ProposalPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=600)
    units: list[ProposalUnit] = Field(min_length=2, max_length=6)
    outcomes: list[str] = Field(min_length=2, max_length=8)


# ---------- Lesson blocks structured output ----------
class TeachBlock(BaseModel):
    type: Literal["teach"]
    title: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(min_length=1, max_length=30)


class MCBlock(BaseModel):
    type: Literal["mc"]
    question: str = Field(min_length=1, max_length=400)
    options: list[str] = Field(min_length=2, max_length=6)
    answerIndex: int = Field(ge=0)


class BlankBlock(BaseModel):
    type: Literal["blank"]
    sentence: str = Field(min_length=1, max_length=400)
    answer: str = Field(min_length=1, max_length=120)


class OrderBlock(BaseModel):
    type: Literal["order"]
    prompt: str = Field(min_length=1, max_length=300)
    items: list[str] = Field(min_length=2, max_length=8)


class MatchBlock(BaseModel):
    type: Literal["match"]
    prompt: str = Field(min_length=1, max_length=300)
    pairs: list[tuple[str, str]] = Field(min_length=2, max_length=8)


class ShortBlock(BaseModel):
    type: Literal["short"]
    question: str = Field(min_length=1, max_length=400)
    acceptedAnswers: list[str] = Field(min_length=1, max_length=10)


AnyBlock = MCBlock | BlankBlock | OrderBlock | MatchBlock | ShortBlock | TeachBlock


class LessonContent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    blocks: list[Annotated[AnyBlock, Field(discriminator="type")]] = Field(
        min_length=1, max_length=40
    )

    model_config = {"extra": "forbid"}


# ---------- API request/response ----------
class CourseCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    clientCourseId: str = Field(min_length=8, max_length=64)


class CourseOut(BaseModel):
    id: str
    topic: str
    status: str
    clientCourseId: str


class InterviewOut(BaseModel):
    questions: list[str]
    completedCount: int


class InterviewAnswerRequest(BaseModel):
    position: int = Field(ge=0, le=4)
    answer: str = Field(min_length=1, max_length=2000)


class ProposalOut(BaseModel):
    version: int
    approved: bool
    payload: dict


class GenerationOut(BaseModel):
    jobId: str
    status: str
    stage: str | None
    lessonsDone: int
    lessonsTotal: int | None
    error: dict | None


class UnitOut(BaseModel):
    id: str
    orderIndex: int
    title: str
    blurb: str
    lessons: list["LessonSummaryOut"]


class LessonSummaryOut(BaseModel):
    id: str
    orderIndex: int
    title: str
    status: str
    contentVersion: int


class CourseDetailOut(BaseModel):
    id: str
    topic: str
    status: str
    units: list[UnitOut]
    progress: dict


class LessonOut(BaseModel):
    id: str
    title: str
    orderIndex: int
    contentVersion: int
    status: str
    blocks: list[dict]


class AttemptResultOut(BaseModel):
    index: int
    type: str
    correct: bool


class AttemptRequest(BaseModel):
    clientAttemptId: str = Field(min_length=8, max_length=64)
    contentVersion: int
    durationMs: int | None = Field(default=None, ge=0)
    answers: list["AttemptAnswer"] = Field(min_length=1)


class AttemptAnswer(BaseModel):
    index: int = Field(ge=0)
    answer: str | int | list | dict | None = None


class AttemptOut(BaseModel):
    attemptId: str
    duplicate: bool
    score: dict
    rewards: dict
    results: list[AttemptResultOut]
