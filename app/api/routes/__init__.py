from fastapi import APIRouter

from app.api.routes import (
    accounts,
    attempts,
    auth,
    contact,
    learners,
    organisation_users,
    profile,
    recommendations,
    results,
    roles,
    skills,
)

# Every API router. app/main.py mounts this under settings.API_PREFIX (/api/v1),
# so no route or folder repeats the prefix.
api_router = APIRouter()

# Include all routers
api_router.include_router(auth.router)
api_router.include_router(auth.token_router)
api_router.include_router(learners.router)
api_router.include_router(skills.router)
api_router.include_router(roles.router)
api_router.include_router(roles.titles_router)
api_router.include_router(attempts.router)
api_router.include_router(profile.router)
api_router.include_router(results.router)
api_router.include_router(results.downloads)
api_router.include_router(recommendations.router)
api_router.include_router(contact.router)
api_router.include_router(accounts.router)
api_router.include_router(organisation_users.router)
