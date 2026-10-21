from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.core.logging import get_logger
from app.core.responses import EnvelopeRoute, ok
from app.db.migration_check import MigrationsPendingError, assert_database_at_head
from app.db.session import engine

logger = get_logger(__name__)

#Mounted outside the /api/v1 prefix so Render and load balancers can call it at a fixed path
router = APIRouter(tags=["Health"], route_class=EnvelopeRoute)


#Liveness: the process is up (no database call, so a slow database never restarts the app)
@router.get("/healthz")
async def health_check():
    return ok({"status": "healthy"}, message=f"{settings.APP_NAME} is running")


#Readiness: the database answers and is at the latest migration
@router.get("/readyz", responses={503: {"description": "Database unreachable or behind the latest migration"}})
async def readiness_check():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await assert_database_at_head(engine)
    except MigrationsPendingError as exc:
        logger.warning("readiness_failed", reason="migrations_pending", detail=str(exc))
        raise ServiceUnavailableError("Database migrations are pending") from exc
    except Exception as exc:
        logger.warning("readiness_failed", reason="database_unreachable", error=type(exc).__name__)
        raise ServiceUnavailableError("Database is unreachable") from exc
    return ok({"status": "ready"}, message="Ready to serve traffic")
