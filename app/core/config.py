from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # Google Cloud AI
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_REGION: str = "us-central1"
    AI_RATE_LIMIT_PER_DAY: int = 10

    # Gemini API (alternative to Vertex AI)
    GEMINI_API_KEY: Optional[str] = None

    # Redis (optional, for distributed rate limiting)
    REDIS_URL: Optional[str] = None

    # Google Sign-In setup token expiry
    GOOGLE_SETUP_TOKEN_EXPIRE_MINUTES: int = 15

    # Encryption key for OAuth tokens / API keys (Fernet key)
    ENCRYPTION_KEY: str = ""

    def validate_required_secrets(self) -> list[str]:
        """Validate that critical secrets are set. Returns list of errors."""
        errors = []
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 16:
            errors.append("SECRET_KEY must be set and at least 16 characters")
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL must be set")
        if self.ENVIRONMENT == "production":
            if not self.ENCRYPTION_KEY:
                errors.append("ENCRYPTION_KEY must be set in production")
            # Block startup with placeholder SECRET_KEY shipped in .env.example
            if "change-in-production" in (self.SECRET_KEY or "").lower():
                errors.append(
                    "SECRET_KEY is still set to the .env.example placeholder — "
                    "generate a new one with `openssl rand -hex 32`"
                )
            if not self.RAZORPAY_KEY_ID or not self.RAZORPAY_KEY_SECRET:
                errors.append("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in production")
            if not self.RAZORPAY_WEBHOOK_SECRET:
                errors.append(
                    "RAZORPAY_WEBHOOK_SECRET must be set in production — "
                    "webhook signature verification will fail without it"
                )
            if self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_ID.startswith("rzp_test_"):
                errors.append(
                    "RAZORPAY_KEY_ID is a test key (rzp_test_*) — switch to rzp_live_* in production"
                )
        return errors

    # Google OAuth — shared client for Sheets, Google Ads, and GA4
    # (same Google Cloud project; scopes differ per connector)
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/google_sheets/callback"
    GOOGLE_ADS_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/google_ads/callback"
    GA4_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/ga4/callback"

    # Google Ads developer token (from Google Ads Manager > API Center)
    GOOGLE_ADS_DEVELOPER_TOKEN: Optional[str] = None

    # Meta (Facebook) Ads OAuth
    META_OAUTH_CLIENT_ID: Optional[str] = None
    META_OAUTH_CLIENT_SECRET: Optional[str] = None
    META_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/meta_ads/callback"
    META_API_VERSION: str = "v19.0"

    # Zoho OAuth (shared credentials for CRM + Books)
    ZOHO_OAUTH_CLIENT_ID: Optional[str] = None
    ZOHO_OAUTH_CLIENT_SECRET: Optional[str] = None
    ZOHO_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_crm/callback"
    ZOHO_BOOKS_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_books/callback"
    ZOHO_SHEET_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_sheet/callback"

    # Razorpay
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None
    # Comma-separated mapping of plan_code:razorpay_plan_id, e.g.
    # "starter:plan_ABC,pro:plan_XYZ,enterprise:plan_DEF"
    RAZORPAY_PLAN_IDS: str = ""

    def razorpay_plan_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in (self.RAZORPAY_PLAN_IDS or "").split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            code, plan_id = pair.split(":", 1)
            out[code.strip()] = plan_id.strip()
        return out

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
