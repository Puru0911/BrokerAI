from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    model_config = SettingsConfigDict(env_file=str(_ENV_PATH), env_file_encoding="utf-8")

    APP_NAME: str = "BrokerAI"
    ENV: str = "local"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/brokerai"

    LLM_PROVIDER: str = "openrouter"
    LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "deepseek/deepseek-chat-v3-0324"
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_API_KEY: str | None = None
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_LLM_MODEL: str = "gemini-2.5-flash"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_REQUEST_COLLECTION: str = "broker_requests"
    MATCH_EXPORT_DIR: str = "./data/match_exports"
    MATCH_EXPORT_AUTO_LIMIT: int = 10
    MEDIATION_INITIAL_TIMEOUT_HOURS: int = 48
    MEDIATION_NEGOTIATION_TIMEOUT_HOURS: int = 72
    MEDIATION_MAX_ACTIVE_PER_REQUEST: int = 1

    SUPABASE_URL: str | None = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    SUPABASE_JWT_ISSUER: str | None = None


settings = Settings()
