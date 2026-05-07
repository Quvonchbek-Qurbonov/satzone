"""Aggregate import for SQLAlchemy model registration.

Importing every model module here ensures all tables are attached to
``Base.metadata`` before Alembic autogeneration or test fixture creation runs.
"""

from app.db.base import Base
from app.models.assessment import (
    Assessment,
    AssessmentSubmission,
    Question,
    QuestionOption,
    SubmissionAnswer,
)
from app.models.auth import PasswordResetToken, PendingRegistration, RefreshToken
from app.models.catalog import Category, Instructor
from app.models.certificate import Certificate
from app.models.course import Course, CourseSection, Lesson
from app.models.enrollment import Enrollment, LessonProgress, Wishlist
from app.models.enums import (
    AssessmentStatus,
    CourseLevel,
    HlsStatus,
    LessonType,
    NotificationType,
    PublishStatus,
    QuestionType,
    SkillLevel,
    UserRole,
)
from app.models.media import MediaKey
from app.models.notification import Notification
from app.models.program import Program, ProgramCourse, ProgramEnrollment
from app.models.review import Review
from app.models.user import NotificationPreference, User, UserInterest, UserProfile

__all__ = [
    "Assessment",
    "AssessmentStatus",
    "AssessmentSubmission",
    "Base",
    "Category",
    "Certificate",
    "Course",
    "CourseLevel",
    "CourseSection",
    "Enrollment",
    "HlsStatus",
    "Instructor",
    "Lesson",
    "MediaKey",
    "LessonProgress",
    "LessonType",
    "Notification",
    "NotificationPreference",
    "NotificationType",
    "PasswordResetToken",
    "PendingRegistration",
    "Program",
    "ProgramCourse",
    "ProgramEnrollment",
    "PublishStatus",
    "Question",
    "QuestionOption",
    "QuestionType",
    "RefreshToken",
    "Review",
    "SkillLevel",
    "SubmissionAnswer",
    "User",
    "UserInterest",
    "UserProfile",
    "UserRole",
    "Wishlist",
]
