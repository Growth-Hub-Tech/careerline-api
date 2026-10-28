"""Every sample router. app/main.py mounts this under /api/v1 when the sample API is on.

When a feature is built for real: move its route to app/api/routes (same path, same response
model), delete the sample route here, and regenerate openapi.json. tests/sample checks that no
sample route ever has the same method and path as a real one.
"""

from fastapi import APIRouter

from app.sample.routes import (
    assessments,
    beginner_path,
    helpers,
    invitations,
    organisations,
    payments,
    privacy,
    profile,
    programmes,
    recruiter,
    results,
    subscriptions,
)

sample_router = APIRouter()

# Day 2: first half of the API (real since then: contact on Day 5, accounts on
# Day 6, roles on Day 8; see app/api/routes)
sample_router.include_router(assessments.router)
sample_router.include_router(results.router)
sample_router.include_router(profile.router)
sample_router.include_router(beginner_path.router)
sample_router.include_router(programmes.router)

# Day 3: second half of the API, with flows that work end to end on sample state
sample_router.include_router(privacy.router)
sample_router.include_router(payments.router)
sample_router.include_router(subscriptions.router)
sample_router.include_router(recruiter.router)
sample_router.include_router(invitations.router)
sample_router.include_router(organisations.audit_router)
sample_router.include_router(organisations.heatmap_router)
sample_router.include_router(organisations.targets_router)
sample_router.include_router(helpers.router)
