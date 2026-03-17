import time
import uuid
from sqlalchemy import text

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from vocablens.api.routes import create_routes
from vocablens.config.settings import settings
from vocablens.infrastructure.logging.logger import get_logger, setup_logging
from vocablens.infrastructure.observability.metrics import REQUEST_LATENCY
from vocablens.infrastructure.rate_limit import RateLimiter

setup_logging()
logger = get_logger("vocablens")


def create_app() -> FastAPI:

    app = FastAPI(
        title="VocabLens API",
        version="1.0.0",
    )

    # ---------------------------------------------------
    # Middleware
    # ---------------------------------------------------

    limiter = RateLimiter(
        redis_url=settings.REDIS_URL if settings.ENABLE_REDIS_CACHE else None,
        limit=60,
        window_sec=60,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        user_id = getattr(getattr(request, "user", None), "id", None)
        path = request.url.path

        # rate limit selected heavy endpoints
        if any(path.startswith(p) for p in ["/speech", "/conversation", "/translate"]):
            allowed = await limiter.allow(f"{path}:{request.client.host}")
            if not allowed:
                return Response(status_code=429, content="Too Many Requests")

        start = time.time()
        error = ""

        try:
            response = await call_next(request)
        except Exception as exc:
            error = str(exc)
            response = Response(status_code=500, content="Internal Server Error")
            raise
        finally:
            duration = time.time() - start
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=path,
                status=getattr(response, "status_code", 0),
            ).observe(duration)
            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "endpoint": path,
                    "latency": duration,
                    "error": error,
                },
            )

        return response

    # ---------------------------------------------------
    # Health Check
    # ---------------------------------------------------

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        checks = {"db": False, "redis": False, "celery": False}
        try:
            from vocablens.infrastructure.db.session import engine
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            checks["db"] = True
        except Exception:
            checks["db"] = False

        try:
            if settings.ENABLE_REDIS_CACHE:
                import redis.asyncio as redis  # type: ignore
                r = redis.from_url(settings.REDIS_URL)
                await r.ping()
                checks["redis"] = True
        except Exception:
            checks["redis"] = False

        try:
            from vocablens.tasks.celery_app import celery_app
            pong = celery_app.control.ping(timeout=0.5)
            checks["celery"] = bool(pong)
        except Exception:
            checks["celery"] = False

        status = all(checks.values())
        return {"status": "ok" if status else "degraded", **checks}

    @app.get("/metrics")
    def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ---------------------------------------------------
    # Routes
    # ---------------------------------------------------

    app.include_router(create_routes())

    return app


app = create_app()
