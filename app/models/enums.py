from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    USER = "user"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class SkillLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CourseLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    ALL_LEVELS = "all_levels"


class PublishStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class LessonType(str, enum.Enum):
    VIDEO = "video"
    ARTICLE = "article"
    QUIZ = "quiz"
    RESOURCE = "resource"


class QuestionType(str, enum.Enum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"


class PracticeItemType(str, enum.Enum):
    MCQ = "mcq"
    MATCHING = "matching"


class AssessmentStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class NotificationType(str, enum.Enum):
    SYSTEM = "system"
    COURSE_UPDATE = "course_update"
    REVIEW = "review"
    ANNOUNCEMENT = "announcement"
    REMINDER = "reminder"


class HlsStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"          # created, awaiting payment
    PROCESSING = "processing"    # payment provider has accepted, awaiting confirmation
    PAID = "paid"                # confirmed; entitlement granted
    CANCELLED = "cancelled"      # user/system cancelled before payment
    REFUNDED = "refunded"        # post-payment reversal
    FAILED = "failed"            # provider rejected


class OrderItemKind(str, enum.Enum):
    COURSE = "course"
    PROGRAM = "program"


class PaymentProvider(str, enum.Enum):
    PAYME = "payme"
    CARD = "card"  # token-based card-on-file via Payme cards.* under the hood


class TransactionState(str, enum.Enum):
    """Mirrors Payme's transaction state machine."""

    CREATED = "created"      # state=1 in Payme
    PERFORMED = "performed"  # state=2 in Payme (success)
    CANCELLED = "cancelled"  # state=-1 (cancelled before perform)
    REVERSED = "reversed"    # state=-2 (cancelled after perform / refund)


class CardBrand(str, enum.Enum):
    UZCARD = "uzcard"
    HUMO = "humo"
    VISA = "visa"
    MASTERCARD = "mastercard"
    UNKNOWN = "unknown"


class PromocodeDiscountKind(str, enum.Enum):
    """Discount math for an instructor-issued promo code."""

    PERCENT = "percent"          # discount_value is 1..100
    FIXED = "fixed"              # discount_value is amount in minor units (tiyin / cents)