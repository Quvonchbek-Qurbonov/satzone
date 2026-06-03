"""Pydantic shapes for the practice (Duolingo-style) quiz feature.

The wire shape mirrors the JSONB ``data`` column on ``practice_items``: each
item type has its own discriminated payload. Student reads strip correctness
flags so the answer key never leaves the server.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import PracticeItemType
from app.schemas.base import ORMModel


MAX_ITEMS_PER_QUIZ = 50


# ---------- Item payloads (matches the JSONB on PracticeItem.data) ----------


class MCQOptionWrite(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    image_url: str | None = None
    is_correct: bool = False


class MCQOptionRead(BaseModel):
    """Student-facing view — ``is_correct`` deliberately omitted."""

    id: str
    text: str
    image_url: str | None = None


class MatchingPairWrite(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)


class MatchingPairRead(BaseModel):
    """Student-facing — only the side labels are returned, with the pair id
    as the join key for the answer submission."""

    id: str
    left: str
    right: str


class MCQDataWrite(BaseModel):
    type: Literal[PracticeItemType.MCQ] = PracticeItemType.MCQ
    prompt: str = Field(min_length=1)
    image_url: str | None = None
    options: list[MCQOptionWrite] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _check_unique_and_correct(self) -> "MCQDataWrite":
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("MCQ option ids must be unique within an item")
        correct = [o for o in self.options if o.is_correct]
        if len(correct) != 1:
            raise ValueError("MCQ items must have exactly one correct option")
        return self


class MatchingDataWrite(BaseModel):
    type: Literal[PracticeItemType.MATCHING] = PracticeItemType.MATCHING
    prompt: str = Field(min_length=1)
    pairs: list[MatchingPairWrite] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "MatchingDataWrite":
        ids = [p.id for p in self.pairs]
        if len(set(ids)) != len(ids):
            raise ValueError("matching pair ids must be unique within an item")
        return self


# ---------- Item read shapes ----------


class MCQDataStudent(BaseModel):
    type: Literal[PracticeItemType.MCQ]
    prompt: str
    image_url: str | None = None
    options: list[MCQOptionRead]


class MatchingDataStudent(BaseModel):
    """Student-facing matching payload.

    Sides are shuffled server-side and emitted as separate ``lefts`` and
    ``rights`` lists keyed on the same pair id; the player drags between them
    and we re-derive correctness from the pair ids on submit.
    """

    type: Literal[PracticeItemType.MATCHING]
    prompt: str
    lefts: list[dict]
    rights: list[dict]


# ---------- Items ----------


class PracticeItemWrite(BaseModel):
    type: PracticeItemType
    points: int = Field(default=1, ge=0)
    order: int | None = Field(default=None, ge=0)
    data: MCQDataWrite | MatchingDataWrite

    @model_validator(mode="after")
    def _type_matches_payload(self) -> "PracticeItemWrite":
        if self.data.type != self.type:
            raise ValueError("item.type must match data.type")
        return self


class PracticeItemInstructorRead(ORMModel):
    id: uuid.UUID
    type: PracticeItemType
    order: int
    points: int
    data: dict


class PracticeItemStudentRead(BaseModel):
    id: uuid.UUID
    type: PracticeItemType
    order: int
    points: int
    data: MCQDataStudent | MatchingDataStudent


# ---------- Quizzes ----------


class PracticeQuizCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    order: int | None = Field(default=None, ge=0)
    is_published: bool = False


class PracticeQuizUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    order: int | None = Field(default=None, ge=0)
    is_published: bool | None = None


class PracticeQuizSummary(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    order: int
    is_published: bool
    item_count: int = 0


class PracticeQuizInstructorRead(PracticeQuizSummary):
    items: list[PracticeItemInstructorRead] = []


class PracticeQuizStudentProgress(BaseModel):
    completed: bool = False
    best_score_percent: int = 0
    attempts_count: int = 0
    last_attempted_at: datetime | None = None


class PracticeQuizStudentSummary(PracticeQuizSummary):
    progress: PracticeQuizStudentProgress = PracticeQuizStudentProgress()


class PracticeQuizStudentRead(PracticeQuizStudentSummary):
    items: list[PracticeItemStudentRead] = []


# ---------- Packs ----------


class PracticePackUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class PracticePackRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str | None = None
    description: str | None = None


class PracticePackStudentRead(PracticePackRead):
    quizzes: list[PracticeQuizStudentSummary] = []


class PracticePackInstructorRead(PracticePackRead):
    quizzes: list[PracticeQuizSummary] = []


# ---------- Attempts ----------


class MCQAnswer(BaseModel):
    item_id: uuid.UUID
    option_id: str


class MatchingPairAnswer(BaseModel):
    left_id: str
    right_id: str


class MatchingAnswer(BaseModel):
    item_id: uuid.UUID
    pairs: list[MatchingPairAnswer] = Field(min_length=1, max_length=10)


class PracticeAttemptCreate(BaseModel):
    started_at: datetime | None = None
    answers: list[MCQAnswer | MatchingAnswer] = Field(min_length=1)


class PracticeItemResult(BaseModel):
    item_id: uuid.UUID
    is_correct: bool
    awarded_points: int


class PracticeAttemptResult(ORMModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    score_percent: int
    correct_count: int
    total_count: int
    completed_at: datetime
    results: list[PracticeItemResult]
