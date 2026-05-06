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