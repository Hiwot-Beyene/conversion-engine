import sys
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent


class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LLMSettings(BaseModel):
    """Configuration for Large Language Model providers."""
    openrouter_api_key: str
    anthropic_api_key: str
    default_model: str = "openai/gpt-4o-mini"
    eval_model: str = "openai/gpt-4o"


class EmailSettings(BaseModel):
    """Configuration for email services (Resend)."""
    api_key: str
    from_email: str
    webhook_secret: str


class SMSSettings(BaseModel):
    """Configuration for SMS services (Africa's Talking)."""
    api_key: str
    username: str
    short_code: str
    sender_id: Optional[str] = None


class CRMSettings(BaseModel):
    """Configuration for CRM integrations (HubSpot)."""
    access_token: str
    portal_id: str


class DBSettings(BaseModel):
    """Configuration for database and caching (PostgreSQL, Redis)."""
    url: str
    redis_url: str
    password: str


class ObservabilitySettings(BaseModel):
    """Configuration for monitoring and tracing (Langfuse)."""
    public_key: str
    secret_key: str
    base_url: str = "https://cloud.langfuse.com"


class CalendarSettings(BaseModel):
    """Configuration for calendar and scheduling (Cal.com)."""
    api_key: str
    event_type_id: str
    webhook_secret: str


class Settings(BaseSettings):
    """
    Production-grade configuration system using Pydantic Settings.
    
    This class loads environment variables from a .env file or the system environment
    and provides grouped, validated access to all configuration parameters.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True
    )

    # --- LLM Settings ---
    OPENROUTER_API_KEY: str
    ANTHROPIC_API_KEY: str
    OPENROUTER_DEFAULT_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_EVAL_MODEL: str = "openai/gpt-4o"

    # --- Email Settings ---
    RESEND_API_KEY: str
    RESEND_FROM_EMAIL: str
    RESEND_WEBHOOK_SECRET: str

    # --- SMS Settings ---
    AT_API_KEY: str
    AT_USERNAME: str
    AT_SHORT_CODE: str
    AT_SENDER_ID: Optional[str] = None

    # --- CRM Settings ---
    HUBSPOT_ACCESS_TOKEN: str
    HUBSPOT_PORTAL_ID: str
    # When true, PATCH includes Tenacious custom contact properties (create them in HubSpot first).
    # When false (default), only built-in HubSpot fields + jobtitle summary; briefs sync via Notes API.
    HUBSPOT_SYNC_CUSTOM_PROPERTIES: bool = False

    # --- Calendar Settings ---
    CALCOM_API_KEY: str
    CALCOM_EVENT_TYPE_ID: str
    CALCOM_WEBHOOK_SECRET: str
    CALCOM_PUBLIC_USERNAME: Optional[str] = None
    CALCOM_PUBLIC_EVENT_SLUG: Optional[str] = None
    # If your Cal event type has a booking question with this slug, we pre-fill it with the company name (calendar title).
    # Set to empty in .env to omit bookingFieldsResponses for title.
    CALCOM_BOOKING_TITLE_SLUG: str = "title"

    # --- Observability Settings ---
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"

    # --- Database Settings ---
    DATABASE_URL: str
    REDIS_URL: str
    DB_PASSWORD: str

    # --- Deployment Settings ---
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    KILL_SWITCH: bool = True
    # Development only: send real email/SMS even when KILL_SWITCH=true (local E2E). Never enable in production.
    LIVE_OUTREACH: bool = False
    # When true, dashboard/orchestrator require explicit POST /api/outreach/approve before first email send.
    REQUIRE_HUMAN_APPROVAL: bool = False
    # Comma-separated origins for CORS (no spaces). Empty = allow localhost dev only.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    # Process must run with a single worker when using in-memory `_workspace` (set WEB_CONCURRENCY=1).
    WEB_CONCURRENCY: str = "1"
    RENDER_WEBHOOK_URL: Optional[str] = None
    # Public HTTPS base (e.g. ngrok) for inbound webhooks — no trailing slash.
    WEBHOOK_PUBLIC_BASE: Optional[str] = None
    # One-time data-handling acknowledgement (path to marker file after user confirms policy).
    DATA_HANDLING_ACK_FILE: str = str(_REPO_ROOT / ".data_handling_acknowledged")
    # Cold sequence delays (days) after E1 / E2 / before re-engagement
    SEQUENCE_E2_DELAY_DAYS: int = 5
    SEQUENCE_E3_DELAY_DAYS: int = 7
    SEQUENCE_REENGAGE_DELAY_DAYS: int = 14
    # When true, block outbound send if JSON Schema validation fails for brief projections.
    ENFORCE_JSON_SCHEMA: bool = False

    # --- Data Sources (defaults anchored to repo root so CWD does not matter) ---
    CRUNCHBASE_CSV_PATH: str = str(_REPO_ROOT / "data" / "crunchbase-companies-information.csv")
    LAYOFFS_CSV_PATH: str = str(_REPO_ROOT / "data" / "layoffs.csv")
    JOB_POSTS_SNAPSHOT_DIR: str = str(_REPO_ROOT / "data" / "job_posts_snapshot_apr2026")

    # --- Grouped Accessors ---
    
    @property
    def llm(self) -> LLMSettings:
        return LLMSettings(
            openrouter_api_key=self.OPENROUTER_API_KEY,
            anthropic_api_key=self.ANTHROPIC_API_KEY,
            default_model=self.OPENROUTER_DEFAULT_MODEL,
            eval_model=self.OPENROUTER_EVAL_MODEL,
        )

    @property
    def email(self) -> EmailSettings:
        return EmailSettings(
            api_key=self.RESEND_API_KEY,
            from_email=self.RESEND_FROM_EMAIL,
            webhook_secret=self.RESEND_WEBHOOK_SECRET
        )

    @property
    def sms(self) -> SMSSettings:
        return SMSSettings(
            api_key=self.AT_API_KEY,
            username=self.AT_USERNAME,
            short_code=self.AT_SHORT_CODE,
            sender_id=self.AT_SENDER_ID
        )

    @property
    def crm(self) -> CRMSettings:
        return CRMSettings(
            access_token=self.HUBSPOT_ACCESS_TOKEN,
            portal_id=self.HUBSPOT_PORTAL_ID
        )

    @property
    def db(self) -> DBSettings:
        return DBSettings(
            url=self.DATABASE_URL,
            redis_url=self.REDIS_URL,
            password=self.DB_PASSWORD
        )

    @property
    def observability(self) -> ObservabilitySettings:
        return ObservabilitySettings(
            public_key=self.LANGFUSE_PUBLIC_KEY,
            secret_key=self.LANGFUSE_SECRET_KEY,
            base_url=self.LANGFUSE_BASE_URL
        )

    @property
    def calendar(self) -> CalendarSettings:
        return CalendarSettings(
            api_key=self.CALCOM_API_KEY,
            event_type_id=self.CALCOM_EVENT_TYPE_ID,
            webhook_secret=self.CALCOM_WEBHOOK_SECRET,
        )

    @property
    def public_webhook_urls(self) -> Dict[str, Any]:
        """
        Full URLs to paste into Resend, Cal.com, and Africa's Talking dashboards.
        HubSpot is not included — this app calls HubSpot via API, not inbound webhooks.
        """
        base = (self.WEBHOOK_PUBLIC_BASE or "").strip().rstrip("/")
        if not base:
            return {}
        return {
            "resend_email_inbound": f"{base}/webhooks/email",
            "cal_com_booking_events": f"{base}/webhooks/cal",
            "africas_talking_inbound_sms": f"{base}/webhooks/sms",
        }

    def outbound_is_suppressed(self) -> bool:
        """True when outbound email/SMS must not be sent (kill switch), unless dev LIVE_OUTREACH override."""
        if not self.KILL_SWITCH:
            return False
        if self.ENVIRONMENT == Environment.DEVELOPMENT and self.LIVE_OUTREACH:
            return False
        return True


@lru_cache()
def get_settings() -> Settings:
    """
    Factory function to provide a singleton Settings instance with explicit error handling.
    
    Raises:
        SystemExit: If configuration validation fails, providing a clear error message.
    """
    try:
        return Settings()
    except ValidationError as e:
        print("\n❌ \033[91mConfiguration Validation Failed\033[0m")
        print("-" * 60)
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            msg = error["msg"]
            print(f"Variable: \033[93m{loc}\033[0m")
            print(f"Error:    {msg}")
            print("-" * 60)
        print("\nPlease check your .env file and ensure all required variables are set correctly.")
        print(f"Environment detected: {Environment.DEVELOPMENT.value}\n")
        sys.exit(1)


# Singleton settings object for project-wide use
settings = get_settings()
