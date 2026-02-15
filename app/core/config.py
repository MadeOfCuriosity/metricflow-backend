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
        return errors

    # Google Sheets OAuth
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/google_sheets/callback"

    # Zoho OAuth (shared credentials for CRM + Books)
    ZOHO_OAUTH_CLIENT_ID: Optional[str] = None
    ZOHO_OAUTH_CLIENT_SECRET: Optional[str] = None
    ZOHO_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_crm/callback"
    ZOHO_BOOKS_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_books/callback"
    ZOHO_SHEET_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/oauth/zoho_sheet/callback"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
