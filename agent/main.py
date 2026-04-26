import logging
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import Environment, settings
from .db.database import engine as db_engine
from .integrations.langfuse_client import langfuse, start_root_trace
from .integrations.structured_logger import log_event, new_correlation_id
from .paths import resolve_repo_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _redact_headers(headers):
    h = dict(headers)
    for k in ("authorization", "cookie", "x-api-key", "X-Api-Key"):
        if k in h:
            h[k] = "[REDACTED]"
        lk = k.lower()
        for key in list(h.keys()):
            if key.lower() == lk:
                h[key] = "[REDACTED]"
    return h


def _startup_checks():
    if (settings.WEB_CONCURRENCY or "1").strip() != "1":
        raise RuntimeError(
            "WEB_CONCURRENCY must be 1 when using in-memory dashboard workspace. "
            "Run: WEB_CONCURRENCY=1 uvicorn agent.main:app --workers 1"
        )
    if settings.ENVIRONMENT == Environment.PRODUCTION:
        if not (settings.RESEND_WEBHOOK_SECRET or "").strip():
            raise RuntimeError("RESEND_WEBHOOK_SECRET is required in production.")
        if not (settings.CALCOM_WEBHOOK_SECRET or "").strip():
            raise RuntimeError("CALCOM_WEBHOOK_SECRET is required in production.")

    ack = settings.DATA_HANDLING_ACK_FILE
    if ack and not os.path.isfile(ack):
        policy = "tenacious_sales_data/policy/acknowledgement.md"
        if sys.stdin and sys.stdin.isatty():
            print(
                "\nData-handling acknowledgement required.\n"
                f"Review {policy}, then type 'yes' to continue: ",
                end="",
                flush=True,
            )
            ans = (input() or "").strip().lower()
            if ans == "yes":
                try:
                    with open(ack, "w", encoding="utf-8") as f:
                        f.write("acknowledged\n")
                    logger.info("Acknowledgement saved: %s", ack)
                except OSError as e:
                    raise RuntimeError(f"Failed to write DATA_HANDLING_ACK_FILE at {ack}: {e}") from e
            else:
                raise RuntimeError("Data-handling acknowledgement not confirmed (expected 'yes').")
        else:
            logger.warning(
                "Data-handling acknowledgement file missing (%s). Non-interactive session; "
                "review %s and create the marker file manually.",
                ack,
                policy,
            )

    for label, path in (
        ("CRUNCHBASE_CSV", settings.CRUNCHBASE_CSV_PATH),
        ("LAYOFFS_CSV", settings.LAYOFFS_CSV_PATH),
    ):
        p = resolve_repo_path(path)
        if not os.path.isfile(p):
            logger.warning("Startup check: %s path not found: %s", label, p)
        else:
            logger.info("Startup check OK: %s", label)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .agent.listeners import setup_event_listeners

    setup_event_listeners()
    logger.info("Event listeners initialized.")

    _startup_checks()

    logger.info("Connecting to PostgreSQL...")
    try:
        async with db_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection successful.")
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
    else:
        from agent.db.models import Base

        # Extension in its own transaction: if it fails, Postgres aborts that txn only.
        # Running create_all in the same txn after a failed CREATE EXTENSION causes
        # InFailedSQLTransactionError on every following statement.
        try:
            async with db_engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as e:
            logger.debug("CREATE EXTENSION vector skipped (permissions or already exists): %s", e)

        try:
            async with db_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLAlchemy metadata create_all finished (missing tables created if permitted).")
        except Exception as e:
            logger.warning("Database schema ensure (create_all) failed — mirror table may be missing: %s", e)

    try:
        from .api.leads_router import rehydrate_workspace_from_db

        await rehydrate_workspace_from_db()
        logger.info("Dashboard workspace rehydrated from Postgres mirror (if any).")
    except Exception as e:
        logger.warning("Workspace rehydrate skipped: %s", e)

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from .agent.sequencer import run_sequence_tick

        sched = AsyncIOScheduler()

        async def _tick():
            try:
                await run_sequence_tick()
            except Exception as ex:
                logger.warning("Sequence tick failed: %s", ex)

        sched.add_job(_tick, "interval", hours=1, id="outreach_sequences", replace_existing=True)
        sched.start()
        app.state.scheduler = sched
        logger.info("APScheduler started (hourly sequence tick).")
    except Exception as e:
        hint = " — run: pip install -r agent/requirements.txt" if isinstance(e, ImportError) else ""
        logger.warning("Scheduler not started: %s%s", e, hint)

    urls = settings.public_webhook_urls
    if urls:
        logger.info("WEBHOOK_PUBLIC_BASE is set — register these URLs on each provider: %s", urls)
    else:
        logger.info(
            "WEBHOOK_PUBLIC_BASE is unset — inbound webhooks need a public URL (e.g. ngrok). "
            "See GET /api/config/webhook-urls"
        )

    yield

    sched = getattr(app.state, "scheduler", None)
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Conversion Engine API", lifespan=lifespan)

_origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
if not _origins:
    _origins = ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or new_correlation_id()
    request.state.correlation_id = cid
    start = time.time()
    response = await call_next(request)
    process_time = (time.time() - start) * 1000
    log_event(
        event="http_request",
        correlation_id=cid,
        step=f"{request.method} {request.url.path}",
        latency_ms=round(process_time, 2),
        extra={"status_code": response.status_code},
    )
    response.headers["X-Correlation-Id"] = cid
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_traceback = traceback.format_exc()
    logger.error("Unhandled exception: %s\n%s", exc, error_traceback)

    try:
        start_root_trace(
            name="unhandled_exception",
            input={
                "method": request.method,
                "url": str(request.url),
                "headers": _redact_headers(request.headers),
            },
            output={"error": str(exc), "traceback": error_traceback},
            metadata={"environment": settings.ENVIRONMENT, "tags": ["error", "api"]},
        )
        langfuse.flush()
    except Exception as lf_exc:
        logger.error("Failed to log to Langfuse: %s", lf_exc)

    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "kill_switch": settings.KILL_SWITCH,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/config/webhook-urls")
async def webhook_urls():
    base = (settings.WEBHOOK_PUBLIC_BASE or "").strip().rstrip("/")
    urls = settings.public_webhook_urls
    if not urls:
        return {
            "configured": False,
            "message": "Set WEBHOOK_PUBLIC_BASE in .env to your public HTTPS base (e.g. ngrok URL, no trailing slash).",
            "example_local_paths_only": {
                "resend": "/webhooks/email",
                "cal_com": "/webhooks/cal",
                "africas_talking": "/webhooks/sms",
            },
        }
    return {
        "configured": True,
        "webhook_public_base": base,
        "register_on_each_platform": urls,
        "hubspot": {
            "inbound_webhook": None,
            "note": "CRM is updated via HUBSPOT_ACCESS_TOKEN (outbound API). No inbound webhook URL in this app.",
        },
    }


@app.get("/docs-info")
async def docs_info():
    return {"message": "FastAPI documentation is available at /docs or /redoc"}


try:
    from .api.leads_router import router as leads_dashboard_router

    app.include_router(leads_dashboard_router)
except (ImportError, AttributeError) as e:
    logger.warning("Dashboard API not loaded: %s", e)

try:
    from .webhooks import email_webhook, sms_webhook, cal_webhook

    app.include_router(email_webhook.router, prefix="/webhooks/email", tags=["webhooks"])
    app.include_router(sms_webhook.router, prefix="/webhooks/sms", tags=["webhooks"])
    app.include_router(cal_webhook.router, prefix="/webhooks/cal", tags=["webhooks"])
except (ImportError, AttributeError) as e:
    logger.warning("Feature routers not fully loaded (expected if files don't exist yet): %s", e)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
