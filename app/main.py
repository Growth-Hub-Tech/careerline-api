from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import api_router, health, legacy
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.migration_check import assert_database_at_head
from app.db.session import engine
from app.sample.core import SampleDataHeaderMiddleware
from app.sample.router import sample_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    yield
    await engine.dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        description="CareerLine AI API: skill tests, scoring, proficiency levels and personalised learning pathways",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Middleware runs outermost-last: CORS -> security headers -> request id / access log / 500s
    # -> sample marker -> gzip
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    if settings.sample_api_enabled:
        app.add_middleware(SampleDataHeaderMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # The frontend may read these: the request id (for bug reports) and the sample marker
        expose_headers=["X-Request-ID", "X-Sample-Data"],
    )

    register_error_handlers(app)

    # Global API prefix: every API route lives under /api/v1 without a v1 folder
    app.include_router(api_router, prefix=settings.API_PREFIX)
    # Sample answers for endpoints not built yet (app/sample). After the real routes, so a real
    # route always wins; off in production unless SAMPLE_API_ENABLED=true.
    if settings.sample_api_enabled:
        app.include_router(sample_router, prefix=settings.API_PREFIX)
    # Outside the prefix: health checks, and the deprecated /api/* routes (removed on Day 4)
    app.include_router(health.router)
    app.include_router(legacy.router)

    return app


app = create_app()
