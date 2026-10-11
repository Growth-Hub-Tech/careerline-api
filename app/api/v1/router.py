from fastapi import APIRouter
from app.api.v1 import learners, skills, attempts, recommendations

#Main v1 router that combines all sub-routers
api_router = APIRouter(prefix="/api/v1")

#Include all routers
api_router.include_router(learners.router)
api_router.include_router(skills.router)
api_router.include_router(attempts.router)
api_router.include_router(recommendations.router)