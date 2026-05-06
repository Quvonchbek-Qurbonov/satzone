from __future__ import annotations

from app.schemas.base import ORMModel
from app.schemas.category import CategoryRead
from app.schemas.course import CourseSummary
from app.schemas.enrollment import EnrollmentRead
from app.schemas.program import ProgramSummary


class HomeFeed(ORMModel):
    continue_learning: list[EnrollmentRead] = []
    recommended: list[CourseSummary] = []
    featured: list[CourseSummary] = []
    popular: list[CourseSummary] = []
    new_courses: list[CourseSummary] = []
    categories: list[CategoryRead] = []
    programs: list[ProgramSummary] = []
