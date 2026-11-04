"""Every sample router. app/main.py mounts this under /api/v1 when the sample API is on.

When a feature is built for real: move its route to app/api/routes (same path, same response
model), delete the sample route here, and regenerate openapi.json. tests/sample checks that no
sample route ever has the same method and path as a real one.
"""

from fastapi import APIRouter

from app.sample.routes import (
    helpers,
    organisations,
    profile,
    subscriptions,
)

sample_router = APIRouter()

# Day 2: first half of the API (real since then: contact on Day 5, accounts on
# Day 6, roles on Day 8, results and their PDF report on Day 12, the
# beginner path on Day 13, programmes on Day 14,
# payments and credits on Day 16, the test catalogue on Day 17, privacy on Day 18,
# candidates and invitations on Day 19, the candidate report on Day 20;
# see app/api/routes)
sample_router.include_router(profile.router)

# Day 3: second half of the API, with flows that work end to end on sample state
sample_router.include_router(subscriptions.router)
sample_router.include_router(organisations.audit_router)
sample_router.include_router(organisations.heatmap_router)
sample_router.include_router(organisations.targets_router)
sample_router.include_router(helpers.router)
