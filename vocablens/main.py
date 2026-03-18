import time
import uuid
import secrets
from sqlalchemy import text

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from vocablens.api.routes import create_routes
from vocablens.config.settings import settings
from vocablens.infrastructure.logging.logger import get_logger, setup_logging
from vocablens.infrastructure.observability.metrics import REQUEST_LATENCY, ERROR_COUNT
from vocablens.infrastructure.rate_limit import RateLimiter
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.infrastructure.observability.token_tracker import start_request, get_tokens

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

    uow_factory = UnitOfWorkFactory(AsyncSessionMaker)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        scope_user = request.scope.get("user")
        user_id = getattr(scope_user, "id", None)
        path = request.url.path
        request.state.request_id = request_id
        start_request()
        request.state.tokens_used = 0

        # rate limit selected heavy endpoints
        if any(path.startswith(p) for p in ["/speech", "/conversation", "/translate"]):
            client_host = request.client.host if request.client else "unknown"
            allowed = await limiter.allow(f"{path}:{client_host}")
            if not allowed:
                return Response(status_code=429, content="Too Many Requests")

        start = time.time()
        error = ""
        tokens_used = 0

        # enforce subscription quotas before hitting handlers
        if user_id:
            async with uow_factory() as uow:
                sub = await uow.subscriptions.get_by_user(user_id)
                tier = (sub.tier if sub else "free").lower()
                request_limit = sub.request_limit if sub else 100
                token_limit = sub.token_limit if sub else 50000
                used_requests, used_tokens = await uow.usage_logs.totals_for_user_day(user_id)
                if used_requests >= request_limit:
                    return Response(status_code=429, content="Request limit exceeded for current period")
                if used_tokens >= token_limit:
                    return Response(status_code=429, content="Token quota exceeded for current period")

        try:
            response = await call_next(request)
            tokens_used = get_tokens()
        except Exception as exc:
            error = str(exc)
            ERROR_COUNT.labels(request.method, path, "500").inc()
            response = Response(status_code=500, content="Internal Server Error")
            raise
        finally:
            request.state.tokens_used = get_tokens()
            tokens_used = request.state.tokens_used
            duration = time.time() - start
            status_code = getattr(response, "status_code", 0)
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=path,
                status=status_code,
            ).observe(duration)
            if status_code >= 400:
                ERROR_COUNT.labels(request.method, path, status_code).inc()
            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "endpoint": path,
                    "latency": duration,
                    "error": error,
                    "tokens_used": tokens_used,
                },
            )
            if user_id:
                try:
                    async with uow_factory() as uow:
                        await uow.usage_logs.log(
                            user_id=user_id,
                            endpoint=path,
                            tokens=tokens_used,
                            success=(error == ""),
                        )
                        await uow.commit()
                except Exception:
                    logger.warning("usage_log_failed", exc_info=True)

        response.headers["X-Request-ID"] = request_id
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
            from vocablens.infrastructure.jobs.celery_app import celery_app
            pong = celery_app.control.ping(timeout=0.5)
            checks["celery"] = bool(pong)
        except Exception:
            checks["celery"] = False

        status = all(checks.values())
        return {"status": "ok" if status else "degraded", **checks}

    @app.get("/metrics")
    def metrics(request: Request):
        token = request.headers.get("X-Metrics-Token") or request.query_params.get("token")
        expected = getattr(settings, "METRICS_TOKEN", "")
        if expected and not (token and secrets.compare_digest(token, expected)):
            return Response(status_code=403, content="Forbidden")
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ---------------------------------------------------
    # Routes
    # ---------------------------------------------------

    app.include_router(create_routes())

    return app


app = create_app()
