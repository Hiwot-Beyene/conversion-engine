import time
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from .config import settings
from .integrations.langfuse_client import langfuse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to PostgreSQL
    logger.info("Connecting to PostgreSQL...")
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            # Just a simple check/connection test
            await conn.execute("SELECT 1")
        logger.info("Database connection successful.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        # We continue to let the app start, or you could re-raise
    
    yield
    
    # Shutdown: Clean up resources
    try:
        await engine.dispose()
        logger.info("Database connection closed.")
    except Exception:
        pass

app = FastAPI(
    title="Conversion Engine API",
    lifespan=lifespan
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = "{0:.2f}ms".format(process_time)
    logger.info(f"Method: {request.method} Path: {request.url.path} Response Time: {formatted_process_time}")
    return response

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log to Langfuse as an error trace
    error_traceback = traceback.format_exc()
    logger.error(f"Unhandled exception: {exc}\n{error_traceback}")
    
    try:
        langfuse.trace(
            name="unhandled_exception",
            input={
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
            },
            output={"error": str(exc), "traceback": error_traceback},
            metadata={"environment": settings.ENVIRONMENT},
            tags=["error", "api"]
        )
        langfuse.flush()
    except Exception as lf_exc:
        logger.error(f"Failed to log to Langfuse: {lf_exc}")

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )

# Health Endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "kill_switch": settings.KILL_SWITCH,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Docs Redirect Note
@app.get("/docs-info")
async def docs_info():
    return {"message": "FastAPI documentation is available at /docs or /redoc"}

# Router Includes with try/except
try:
    from .webhooks import email_webhook, sms_webhook, cal_webhook
    app.include_router(email_webhook.router, prefix="/webhooks/email", tags=["webhooks"])
    app.include_router(sms_webhook.router, prefix="/webhooks/sms", tags=["webhooks"])
    app.include_router(cal_webhook.router, prefix="/webhooks/cal", tags=["webhooks"])
except (ImportError, AttributeError) as e:
    logger.warning(f"Feature routers not fully loaded (expected if files don't exist yet): {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
