"""Seed sample data so the API has something to render.

Run inside the container:
    docker compose exec api python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from slugify import slugify
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.catalog import Category, Instructor
from app.models.course import Course, CourseSection, Lesson
from app.models.enums import (
    CourseLevel,
    LessonType,
    PublishStatus,
    UserRole,
)
from app.models.program import Program, ProgramCourse
from app.models.user import NotificationPreference, User


async def _get_or_create_category(session, slug: str, name: str, **kwargs) -> Category:
    existing = (await session.execute(select(Category).where(Category.slug == slug))).scalar_one_or_none()
    if existing:
        return existing
    cat = Category(slug=slug, name=name, **kwargs)
    session.add(cat)
    await session.flush()
    return cat


async def _get_or_create_instructor(session, slug: str, **kwargs) -> Instructor:
    existing = (
        await session.execute(select(Instructor).where(Instructor.slug == slug))
    ).scalar_one_or_none()
    if existing:
        return existing
    inst = Instructor(slug=slug, **kwargs)
    session.add(inst)
    await session.flush()
    return inst


async def _get_or_create_course(
    session, *, slug: str, instructor: Instructor, category: Category, **kwargs
) -> Course:
    existing = (
        await session.execute(select(Course).where(Course.slug == slug))
    ).scalar_one_or_none()
    if existing:
        return existing
    course = Course(
        slug=slug,
        instructor_id=instructor.id,
        category_id=category.id,
        status=PublishStatus.PUBLISHED,
        published_at=datetime.now(tz=UTC),
        **kwargs,
    )
    session.add(course)
    await session.flush()
    return course


async def seed() -> None:
    async with SessionLocal() as session:
        # Categories
        design = await _get_or_create_category(session, "design", "Design", icon_url=None, sort_order=1)
        dev = await _get_or_create_category(session, "development", "Development", sort_order=2)
        biz = await _get_or_create_category(session, "business", "Business", sort_order=3)
        await _get_or_create_category(session, "data-science", "Data Science", sort_order=4)
        await _get_or_create_category(session, "marketing", "Marketing", sort_order=5)

        # Instructors
        ada = await _get_or_create_instructor(
            session,
            slug="ada-lovelace",
            name="Ada Lovelace",
            title="Lead Engineer",
            bio="Pioneer of programming.",
            avatar_url=None,
            expertise=["python", "math"],
            rating_avg=Decimal("4.8"),
            students_count=4200,
            courses_count=3,
        )
        ed = await _get_or_create_instructor(
            session,
            slug="edsger-dijkstra",
            name="Edsger Dijkstra",
            title="CS Professor",
            bio="Algorithms guru.",
            expertise=["algorithms", "graphs"],
            rating_avg=Decimal("4.9"),
            students_count=8000,
            courses_count=5,
        )

        # Courses with sections + lessons
        course_specs = [
            {
                "title": "Modern Python for Web Developers",
                "subtitle": "FastAPI, async, and production patterns",
                "instructor": ada,
                "category": dev,
                "level": CourseLevel.INTERMEDIATE,
                "duration_minutes": 720,
                "price_cents": 4900,
                "tags": ["python", "fastapi", "async"],
                "learning_outcomes": [
                    "Build production async APIs",
                    "Test and deploy FastAPI services",
                ],
                "requirements": ["Basic Python"],
                "target_audience": ["Backend developers"],
            },
            {
                "title": "Algorithms in Practice",
                "subtitle": "Graphs, DP, and beyond",
                "instructor": ed,
                "category": dev,
                "level": CourseLevel.ADVANCED,
                "duration_minutes": 900,
                "price_cents": 0,
                "tags": ["algorithms", "graphs"],
                "learning_outcomes": ["Master DP", "Solve graph problems"],
            },
            {
                "title": "Brand Design Foundations",
                "subtitle": "Identity, typography, and color theory",
                "instructor": ada,
                "category": design,
                "level": CourseLevel.BEGINNER,
                "duration_minutes": 360,
                "price_cents": 2900,
                "tags": ["design", "branding"],
            },
            {
                "title": "Bootstrapping a SaaS",
                "subtitle": "From idea to first paying customer",
                "instructor": ed,
                "category": biz,
                "level": CourseLevel.ALL_LEVELS,
                "duration_minutes": 480,
                "price_cents": 1900,
                "tags": ["saas", "startup"],
            },
        ]

        created_courses: list[Course] = []
        for spec in course_specs:
            slug = slugify(spec["title"])
            course = await _get_or_create_course(
                session,
                slug=slug,
                title=spec["title"],
                subtitle=spec["subtitle"],
                description=f"In-depth course on {spec['title']}.",
                instructor=spec["instructor"],
                category=spec["category"],
                level=spec["level"],
                duration_minutes=spec["duration_minutes"],
                price_cents=spec["price_cents"],
                currency="USD",
                tags=spec.get("tags") or [],
                learning_outcomes=spec.get("learning_outcomes") or [],
                requirements=spec.get("requirements") or [],
                target_audience=spec.get("target_audience") or [],
                rating_avg=Decimal("4.5"),
                ratings_count=10,
                enrollments_count=100,
                lectures_count=8,
                is_featured=spec is course_specs[0],
            )
            created_courses.append(course)

            existing_sections = (
                await session.execute(
                    select(CourseSection).where(CourseSection.course_id == course.id)
                )
            ).scalars().all()
            if existing_sections:
                continue

            for s_idx, section_title in enumerate(["Getting Started", "Core Concepts", "Real-world Project"]):
                section = CourseSection(
                    course_id=course.id, title=section_title, order=s_idx
                )
                session.add(section)
                await session.flush()
                for l_idx in range(3):
                    session.add(
                        Lesson(
                            section_id=section.id,
                            title=f"{section_title} — Lesson {l_idx + 1}",
                            type=LessonType.VIDEO,
                            duration_seconds=600,
                            order=l_idx,
                            is_free_preview=(s_idx == 0 and l_idx == 0),
                            video_url="https://cdn.example.com/sample.mp4",
                        )
                    )

        # Program (Degree)
        prog_slug = "fullstack-degree"
        prog = (
            await session.execute(select(Program).where(Program.slug == prog_slug))
        ).scalar_one_or_none()
        if prog is None:
            prog = Program(
                slug=prog_slug,
                title="Fullstack Engineering Degree",
                subtitle="Become a versatile fullstack engineer in 16 weeks",
                description="A bundled program covering backend, frontend, and product delivery.",
                level=CourseLevel.INTERMEDIATE,
                duration_weeks=16,
                price_cents=29900,
                currency="USD",
                status=PublishStatus.PUBLISHED,
                published_at=datetime.now(tz=UTC),
            )
            session.add(prog)
            await session.flush()
            for idx, course in enumerate(created_courses[:3]):
                session.add(
                    ProgramCourse(
                        program_id=prog.id,
                        course_id=course.id,
                        order=idx,
                        milestone_title=f"Phase {idx + 1}",
                        is_required=True,
                    )
                )

        # Demo user
        admin_email = "demo@edure.local"
        existing_user = (
            await session.execute(select(User).where(User.email == admin_email))
        ).scalar_one_or_none()
        if existing_user is None:
            user = User(
                email=admin_email,
                password_hash=hash_password("DemoPass123!"),
                full_name="Demo User",
                role=UserRole.USER,
                is_verified=True,
                email_verified_at=datetime.now(tz=UTC),
            )
            session.add(user)
            await session.flush()
            session.add(NotificationPreference(user_id=user.id))

        await session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
