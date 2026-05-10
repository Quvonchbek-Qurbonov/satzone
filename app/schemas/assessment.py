from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.models.enums import AssessmentStatus, QuestionType
from app.schemas.base import ORMModel


# ---- Options ----


class OptionWrite(ORMModel):
    text: str = Field(min_length=1)
    is_correct: bool = False
    order: int | None = Field(default=None, ge=0)
    image_url: str | None = None


class OptionRead(ORMModel):
    id: uuid.UUID
    text: str
    order: int = 0
    image_url: str | None = None
    # is_correct is omitted for student-facing reads; included for instructors.


class OptionInstructorRead(OptionRead):
    is_correct: bool = False


# ---- Questions ----


class QuestionCreate(ORMModel):
    type: QuestionType
    prompt: str = Field(min_length=1)
    explanation: str | None = None
    points: int = Field(default=1, ge=0)
    order: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    options: list[OptionWrite] | None = None
    expected_answers: list[str] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "QuestionCreate":
        if self.type in (QuestionType.SINGLE_CHOICE, QuestionType.MULTI_CHOICE, QuestionType.TRUE_FALSE):
            if not self.options or len(self.options) < 2:
                raise ValueError("choice questions need at least 2 options")
            correct = [o for o in self.options if o.is_correct]
            if not correct:
                raise ValueError("at least one option must be marked correct")
            if self.type == QuestionType.SINGLE_CHOICE and len(correct) != 1:
                raise ValueError("single_choice must have exactly one correct option")
        elif self.type == QuestionType.SHORT_ANSWER:
            if not self.expected_answers:
                raise ValueError("short_answer requires expected_answers")
        return self


class QuestionUpdate(ORMModel):
    prompt: str | None = Field(default=None, min_length=1)
    explanation: str | None = None
    points: int | None = Field(default=None, ge=0)
    order: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    options: list[OptionWrite] | None = None
    expected_answers: list[str] | None = None


class QuestionInstructorRead(ORMModel):
    id: uuid.UUID
    type: QuestionType
    prompt: str
    explanation: str | None = None
    points: int
    order: int
    image_url: str | None = None
    expected_answers: list[str] | None = None
    options: list[OptionInstructorRead] = Field(default_factory=list)


class QuestionStudentRead(ORMModel):
    id: uuid.UUID
    type: QuestionType
    prompt: str
    points: int
    order: int
    image_url: str | None = None
    options: list[OptionRead] = Field(default_factory=list)


# ---- Assessments ----


class AssessmentCreate(ORMModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    instructions: str | None = None
    section_id: uuid.UUID | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1)
    pass_percent: int = Field(default=70, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)
    shuffle_questions: bool = False
    show_correct_answers: bool = True
    is_section_quiz: bool = False


class AssessmentUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    instructions: str | None = None
    section_id: uuid.UUID | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1)
    pass_percent: int | None = Field(default=None, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)
    shuffle_questions: bool | None = None
    show_correct_answers: bool | None = None
    is_section_quiz: bool | None = None
    status: AssessmentStatus | None = None


class AssessmentSummary(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    section_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    pass_percent: int
    time_limit_minutes: int | None = None
    max_attempts: int | None = None
    status: AssessmentStatus
    is_section_quiz: bool = False
    questions_count: int = 0
    created_at: datetime


class AssessmentInstructorRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    section_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    instructions: str | None = None
    time_limit_minutes: int | None = None
    pass_percent: int
    max_attempts: int | None = None
    shuffle_questions: bool
    show_correct_answers: bool
    is_section_quiz: bool
    status: AssessmentStatus
    questions: list[QuestionInstructorRead] = Field(default_factory=list)


class SectionQuizStatus(ORMModel):
    """Snapshot of a learner's progress against a section quiz.

    ``passed`` is the gating signal — until it flips to ``True`` the streaming
    layer and progress endpoints will refuse lessons in later sections.
    """

    section_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    required: bool = False
    passed: bool = False
    attempts: int = 0
    last_score_percent: int | None = None
    best_score_percent: int | None = None
    pass_percent: int | None = None
    max_attempts: int | None = None


# ---- Submissions ----


class SubmissionAnswerWrite(ORMModel):
    question_id: uuid.UUID
    selected_option_ids: list[uuid.UUID] | None = None
    text: str | None = None


class AssessmentSubmissionCreate(ORMModel):
    answers: list[SubmissionAnswerWrite] = Field(min_length=1)


class SubmissionAnswerRead(ORMModel):
    question_id: uuid.UUID
    is_correct: bool
    awarded_points: int
    response: dict | list | None = None


class AssessmentSubmissionRead(ORMModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    user_id: uuid.UUID
    attempt_number: int
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    score_percent: int
    passed: bool
    answers: list[SubmissionAnswerRead] = Field(default_factory=list)
