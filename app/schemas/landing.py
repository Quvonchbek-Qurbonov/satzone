from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class LandingStatsRead(ORMModel):
    """Public landing-page statistics — no auth required to read."""

    students_count: int = Field(
        ..., description="Total number of students on the platform"
    )
    average_score_gain: int = Field(
        ..., description="Average SAT score points gained by students"
    )
    practice_questions: int = Field(
        ..., description="Number of practice questions available"
    )
    top_student_sat_score: int = Field(
        ..., description="Highest SAT score achieved by a student"
    )


class LandingStatsUpdate(BaseModel):
    """Admin-only update. Every field is optional — only the supplied ones change."""

    students_count: int | None = Field(default=None, ge=0)
    average_score_gain: int | None = Field(default=None, ge=0)
    practice_questions: int | None = Field(default=None, ge=0)
    top_student_sat_score: int | None = Field(default=None, ge=0)
