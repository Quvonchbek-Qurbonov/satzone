"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Enum types — created explicitly so each is owned by a single migration step.
USER_ROLE = postgresql.ENUM("user", "instructor", "admin", name="user_role")
SKILL_LEVEL = postgresql.ENUM("beginner", "intermediate", "advanced", name="skill_level")
COURSE_LEVEL = postgresql.ENUM(
    "beginner", "intermediate", "advanced", "all_levels", name="course_level"
)
PUBLISH_STATUS = postgresql.ENUM("draft", "published", "archived", name="publish_status")
LESSON_TYPE = postgresql.ENUM("video", "article", "quiz", "resource", name="lesson_type")
NOTIFICATION_TYPE = postgresql.ENUM(
    "system", "course_update", "review", "announcement", "reminder", name="notification_type"
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (USER_ROLE, SKILL_LEVEL, COURSE_LEVEL, PUBLISH_STATUS, LESSON_TYPE, NOTIFICATION_TYPE):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
            server_default="user",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("icon_url", sa.String(500)),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
        ),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"], unique=True)
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])

    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("headline", sa.String(255)),
        sa.Column("bio", sa.Text()),
        sa.Column("skill_level", postgresql.ENUM(name="skill_level", create_type=False)),
        sa.Column("weekly_goal_minutes", sa.Integer),
        sa.Column("learning_goal", sa.Text()),
        sa.Column("locale", sa.String(10), server_default="en"),
        sa.Column("timezone", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("email_marketing", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("email_announcements", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("email_course_updates", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("push_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "user_interests",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "instructors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(150), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("title", sa.String(150)),
        sa.Column("bio", sa.Text()),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column("expertise", postgresql.ARRAY(sa.String(80))),
        sa.Column("rating_avg", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("students_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("courses_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("linkedin_url", sa.String(500)),
        sa.Column("twitter_url", sa.String(500)),
        sa.Column("website_url", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_instructors_slug", "instructors", ["slug"], unique=True)

    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.String(280)),
        sa.Column("description", sa.Text()),
        sa.Column("thumbnail_url", sa.String(500)),
        sa.Column("preview_video_url", sa.String(500)),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instructor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instructors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "level",
            postgresql.ENUM(name="course_level", create_type=False),
            nullable=False,
            server_default="all_levels",
        ),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lectures_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discount_price_cents", sa.Integer),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("rating_avg", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("ratings_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enrollments_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("learning_outcomes", postgresql.ARRAY(sa.String(280))),
        sa.Column("requirements", postgresql.ARRAY(sa.String(280))),
        sa.Column("target_audience", postgresql.ARRAY(sa.String(280))),
        sa.Column("tags", postgresql.ARRAY(sa.String(80))),
        sa.Column(
            "status",
            postgresql.ENUM(name="publish_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("price_cents >= 0", name="ck_courses_price_non_negative"),
        sa.CheckConstraint(
            "discount_price_cents IS NULL OR discount_price_cents >= 0",
            name="ck_courses_discount_non_negative",
        ),
        sa.CheckConstraint(
            "discount_price_cents IS NULL OR discount_price_cents <= price_cents",
            name="ck_courses_discount_le_price",
        ),
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_index("ix_courses_category_id", "courses", ["category_id"])
    op.create_index("ix_courses_instructor_id", "courses", ["instructor_id"])
    op.create_index("ix_courses_status", "courses", ["status"])
    op.create_index("ix_courses_tags", "courses", ["tags"], postgresql_using="gin")
    op.create_index(
        "ix_courses_title_trgm",
        "courses",
        [sa.text("lower(title)")],
    )

    op.create_table(
        "course_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("course_id", "order", name="uq_course_section_order"),
    )
    op.create_index("ix_course_sections_course_id", "course_sections", ["course_id"])

    op.create_table(
        "lessons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("video_url", sa.String(500)),
        sa.Column("article_content", sa.Text()),
        sa.Column("resource_url", sa.String(500)),
        sa.Column("duration_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "type",
            postgresql.ENUM(name="lesson_type", create_type=False),
            nullable=False,
            server_default="video",
        ),
        sa.Column("is_free_preview", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("section_id", "order", name="uq_lesson_section_order"),
    )
    op.create_index("ix_lessons_section_id", "lessons", ["section_id"])

    op.create_table(
        "enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "last_lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="SET NULL"),
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),
        sa.CheckConstraint("progress_percent BETWEEN 0 AND 100", name="ck_enrollments_progress_pct_range"),
    )
    op.create_index("ix_enrollments_user_id", "enrollments", ["user_id"])
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"])

    op.create_table(
        "lesson_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("watched_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_position_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress_enroll_lesson"),
    )
    op.create_index("ix_lesson_progress_enrollment_id", "lesson_progress", ["enrollment_id"])
    op.create_index("ix_lesson_progress_lesson_id", "lesson_progress", ["lesson_id"])

    op.create_table(
        "wishlists",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("course_id", "user_id", name="uq_review_course_user"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
    )
    op.create_index("ix_reviews_course_id", "reviews", ["course_id"])
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"])

    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.String(280)),
        sa.Column("description", sa.Text()),
        sa.Column("thumbnail_url", sa.String(500)),
        sa.Column(
            "level",
            postgresql.ENUM(name="course_level", create_type=False),
            nullable=False,
            server_default="all_levels",
        ),
        sa.Column("duration_weeks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column(
            "status",
            postgresql.ENUM(name="publish_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("price_cents >= 0", name="ck_programs_price_non_negative"),
    )
    op.create_index("ix_programs_slug", "programs", ["slug"], unique=True)
    op.create_index("ix_programs_status", "programs", ["status"])

    op.create_table(
        "program_courses",
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("milestone_title", sa.String(200)),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("program_id", "order", name="uq_program_course_order"),
    )

    op.create_table(
        "program_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "program_id", name="uq_program_enrollment_user_program"),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name="ck_program_enrollments_progress_pct_range"
        ),
    )
    op.create_index("ix_program_enrollments_user_id", "program_enrollments", ["user_id"])
    op.create_index("ix_program_enrollments_program_id", "program_enrollments", ["program_id"])

    op.create_table(
        "certificates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="SET NULL"),
        ),
        sa.Column("serial_no", sa.String(64), nullable=False),
        sa.Column("url", sa.String(500)),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(course_id IS NOT NULL) OR (program_id IS NOT NULL)",
            name="ck_certificates_certificate_target_present",
        ),
    )
    op.create_index("ix_certificates_user_id", "certificates", ["user_id"])
    op.create_index("ix_certificates_course_id", "certificates", ["course_id"])
    op.create_index("ix_certificates_program_id", "certificates", ["program_id"])
    op.create_index("ix_certificates_serial_no", "certificates", ["serial_no"], unique=True)

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(name="notification_type", create_type=False),
            nullable=False,
            server_default="system",
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        ),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
    )
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    for tbl in (
        "password_reset_tokens",
        "email_verification_tokens",
        "refresh_tokens",
        "notifications",
        "certificates",
        "program_enrollments",
        "program_courses",
        "programs",
        "reviews",
        "wishlists",
        "lesson_progress",
        "enrollments",
        "lessons",
        "course_sections",
        "courses",
        "instructors",
        "user_interests",
        "notification_preferences",
        "user_profiles",
        "categories",
        "users",
    ):
        op.drop_table(tbl)

    bind = op.get_bind()
    for enum in (
        NOTIFICATION_TYPE,
        LESSON_TYPE,
        PUBLISH_STATUS,
        COURSE_LEVEL,
        SKILL_LEVEL,
        USER_ROLE,
    ):
        enum.drop(bind, checkfirst=True)