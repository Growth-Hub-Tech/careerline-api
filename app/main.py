import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import api_router, health, test_mailbox
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.launch_checks import production_problems
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.permissions import authorize
from app.db.migration_check import assert_database_at_head
from app.db.session import engine
from app.jobs.runner import JobRunner

logger = get_logger(__name__)

# Render stops a service 30 seconds after SIGTERM
SHUTDOWN_GRACE_SECONDS = 25.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Day 29: production never starts with an unsafe or test setting (app/core/launch_checks.py)
    problems = production_problems(settings)
    if problems:
        logger.error("startup_refused", problems=problems)
        raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
    # Never serve requests against an old schema: scripts/start.sh migrates first,
    # and this stops anyone who starts uvicorn directly on a database that is behind.
    if settings.CHECK_MIGRATIONS_ON_STARTUP:
        try:
            await assert_database_at_head(engine)
        except Exception:
            logger.exception("startup_aborted")
            raise
    logger.info(
        "startup", app=settings.APP_NAME, env=settings.APP_ENV, api_prefix=settings.API_PREFIX
    )

    # The free test server has no worker service: RUN_JOBS_IN_WEB=true runs the jobs in here
    stop_jobs = asyncio.Event()
    jobs_task = None
    if settings.RUN_JOBS_IN_WEB:
        jobs_task = asyncio.create_task(JobRunner().run_forever(stop_jobs))
        logger.info("jobs_running_in_web_process")
    try:
        yield
    finally:
        if jobs_task is not None:
            stop_jobs.set()
            try:
                # Let the job in progress finish; a job cut off here is retried when its lease ends
                await asyncio.wait_for(jobs_task, timeout=SHUTDOWN_GRACE_SECONDS)
            except TimeoutError:
                jobs_task.cancel()
    await engine.dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()

    # The interactive docs and the API description are for the team: production does not serve
    # them (scripts/export_openapi.py builds openapi.json without them)
    docs = not settings.is_production
    app = FastAPI(
        title=settings.APP_NAME,
        description="CareerLine AI API: skill tests, scoring, proficiency levels and personalised learning pathways",
        version="2.0.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
        # Every route passes its access rule first (app/core/permissions.py: the one place)
        dependencies=[Depends(authorize)],
    )

    # Middleware runs outermost-last: CORS -> security headers -> request id / access log / 500s
    # -> body size limit (413) -> gzip
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # The frontend may read the request id (for bug reports)
        expose_headers=["X-Request-ID"],
    )

    register_error_handlers(app)

    # Global API prefix: every API route lives under /api/v1 without a v1 folder
    app.include_router(api_router, prefix=settings.API_PREFIX)
    # The test server's mailbox (never in production; see app/api/routes/test_mailbox.py)
    if not settings.is_production:
        app.include_router(test_mailbox.router, prefix=settings.API_PREFIX)
    # Outside the prefix: health checks
    app.include_router(health.router)

    return app


app = create_app()
