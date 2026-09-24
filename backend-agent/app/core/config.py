from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _AGENT_ENV = Path(__file__).resolve().parents[2] / ".env"
    _SHARED_ENV = Path(__file__).resolve().parents[3] / "backend" / ".env"
    model_config = SettingsConfigDict(
        env_file=(str(_SHARED_ENV), str(_AGENT_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "BrokerAI"
    ENV: str = "local"
    PUBLIC_APP_URL: str | None = None
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]
    INTERNAL_JOB_SECRET: str | None = None

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/brokerai"
    # Supabase pooler (port 6543) often presents a chain Homebrew Python rejects.
    # Default encrypts without CA verify. Set true to require a trusted cert.
    DATABASE_SSL_VERIFY: bool = False

    LLM_PROVIDER: str = "openrouter"
    LLM_REQUEST_TIMEOUT_SECONDS: float = 60.0
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    OPENROUTER_REASONING_ENABLED: bool = True
    OPENROUTER_REASONING_EFFORT: str = "medium"
    OPENROUTER_REASONING_EXCLUDE: bool = False
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_REASONING_EFFORT: str = "low"
    GROQ_MAX_COMPLETION_TOKENS: int = 2048
    GEMINI_API_KEY: str | None = None
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_LLM_MODEL: str = "gemini-2.5-flash"

    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_REQUEST_COLLECTION: str = "agent_requests"

    AGENT_MAX_TOOL_STEPS: int = 16
    AGENT_MODEL_INVOKE_RETRIES: int = 3
    MATCH_TIMEOUT_HOURS: int = 48
    MAX_OPEN_MATCHES_PER_REQUEST: int = 1

    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "logs/brokerai.log"

    SUPABASE_URL: str | None = None
    SUPABASE_JWT_SECRET: str | None = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    SUPABASE_JWT_ISSUER: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    SUPABASE_STORAGE_BUCKET: str = "broker-attachments"
    ATTACHMENT_MAX_BYTES: int = 10_000_000
    ATTACHMENT_MAX_PER_SESSION: int = 20
    ATTACHMENT_MAX_PER_CONNECTION: int = 100
    ATTACHMENT_SIGNED_URL_TTL_SECONDS: int = 3600

    VAPID_PUBLIC_KEY: str | None = None
    VAPID_PRIVATE_KEY: str | None = None
    VAPID_SUBJECT: str = "mailto:broker@localhost"
    VAPID_KEY_PATH: str = "./data/vapid.json"

    @property
    def vapid_key_file(self) -> Path:
        raw = Path(self.VAPID_KEY_PATH)
        if raw.is_absolute():
            return raw
        return Path(__file__).resolve().parents[2] / raw

    @property
    def is_local(self) -> bool:
        return (self.ENV or "").strip().lower() in {"local", "dev", "development"}

    @property
    def is_production(self) -> bool:
        return (self.ENV or "").strip().lower() in {"production", "prod"}

    @property
    def public_app_url(self) -> str:
        if self.PUBLIC_APP_URL and self.PUBLIC_APP_URL.strip():
            return self.PUBLIC_APP_URL.strip().rstrip("/")
        if self.CORS_ORIGINS:
            return self.CORS_ORIGINS[0].rstrip("/")
        return "http://localhost:3000"

    @property
    def jwt_issuer(self) -> str | None:
        if self.SUPABASE_JWT_ISSUER and self.SUPABASE_JWT_ISSUER.strip():
            return self.SUPABASE_JWT_ISSUER.strip().rstrip("/")
        if self.SUPABASE_URL and self.SUPABASE_URL.strip():
            return self.SUPABASE_URL.strip().rstrip("/") + "/auth/v1"
        return None


settings = Settings()
