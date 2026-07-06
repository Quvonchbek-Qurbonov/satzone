"""Aggregate import for SQLAlchemy model registration.

Importing every model module here ensures all tables are attached to
``Base.metadata`` before Alembic autogeneration or test fixture creation runs.
"""

from app.db.base import Base
from app.models.activity import DailyActivity
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
from app.models.download import LessonAttachment, UserResourceDownload
from app.models.enrollment import Enrollment, LessonProgress, Wishlist
from app.models.enums import (
    AssessmentStatus,
    CardBrand,
    CourseLevel,
    HlsStatus,
    LessonType,
    NotificationType,
    OrderItemKind,
    OrderStatus,
    PaymentProvider,
    PracticeItemType,
    PromocodeDiscountKind,
    PublishStatus,
    QuestionType,
    SkillLevel,
    TransactionState,
    UserRole,
)
from app.models.media import MediaKey
from app.models.note import LessonNote
from app.models.notification import Notification
from app.models.payment import Order, PaymentMethod, Transaction
from app.models.practice import PracticeAttempt, PracticeItem, PracticePack, PracticeQuiz
from app.models.program import Program, ProgramCourse, ProgramEnrollment
from app.models.promocode import Promocode, SavedPromocode
from app.models.review import Review
from app.models.user import NotificationPreference, User, UserInterest, UserProfile

__all__ = [
    "Assessment",
    "AssessmentStatus",
    "AssessmentSubmission",
    "Base",
    "CardBrand",
    "Category",
    "Certificate",
    "Course",
    "CourseLevel",
    "CourseSection",
    "DailyActivity",
    "Enrollment",
    "HlsStatus",
    "Instructor",
    "Lesson",
    "LessonAttachment",
    "LessonNote",
    "MediaKey",
    "LessonProgress",
    "LessonType",
    "Notification",
    "NotificationPreference",
    "NotificationType",
    "Order",
    "OrderItemKind",
    "OrderStatus",
    "PasswordResetToken",
    "PaymentMethod",
    "PaymentProvider",
    "PendingRegistration",
    "PracticeAttempt",
    "PracticeItem",
    "PracticeItemType",
    "PracticePack",
    "PracticeQuiz",
    "Program",
    "ProgramCourse",
    "ProgramEnrollment",
    "Promocode",
    "PromocodeDiscountKind",
    "PublishStatus",
    "Question",
    "QuestionOption",
    "QuestionType",
    "RefreshToken",
    "Review",
    "SavedPromocode",
    "SkillLevel",
    "SubmissionAnswer",
    "Transaction",
    "TransactionState",
    "User",
    "UserInterest",
    "UserProfile",
    "UserResourceDownload",
    "UserRole",
    "Wishlist",
]
