from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1 import (
    account,
    activity,
    admin,
    assessments,
    auth,
    categories,
    courses,
    downloads,
    drm,
    enrollments,
    health,
    home,
    instructor,
    instructors,
    notes,
    onboarding,
    payments,
    programs,
    streaming,
    wishlist,
)
from app.middleware.rate_limit import rate_limit_default

api_router = APIRouter(dependencies=[Depends(rate_limit_default)])

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(onboarding.router)
api_router.include_router(home.router)
api_router.include_router(categories.router)
api_router.include_router(instructors.router)
api_router.include_router(courses.router)
api_router.include_router(enrollments.router)
api_router.include_router(enrollments.certificate_router)
api_router.include_router(wishlist.router)
api_router.include_router(programs.router)
api_router.include_router(programs.me_router)
api_router.include_router(instructor.router)
api_router.include_router(assessments.router)
api_router.include_router(streaming.router)
api_router.include_router(drm.router)
api_router.include_router(notes.router)
api_router.include_router(downloads.attachments_router)
api_router.include_router(downloads.downloads_router)
api_router.include_router(activity.router)
api_router.include_router(payments.methods_router)
api_router.include_router(payments.orders_router)
api_router.include_router(payments.me_orders_router)
api_router.include_router(payments.payme_router)
api_router.include_router(admin.router)
