"""Settings, read from the environment and `.env`.

Credentials have development defaults so a fresh clone runs on 127.0.0.1 with the docker-compose database. In
production (`ENVIRONMENT=production`) the database URLs must be supplied explicitly and may not be the development ones.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Development-only defaults. Use 127.0.0.1 rather than localhost: Docker Desktop maps IPv4 only and localhost tries
# IPv6 first, which stalls every new connection for several seconds.
DEV_DATABASE_URL = "postgresql://lettings:lettings@127.0.0.1:5432/lettings"
DEV_READONLY_DATABASE_URL = "postgresql://lettings_ro:lettings_ro@127.0.0.1:5432/lettings"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    environment: Literal["development", "production"] = "development"

    anthropic_api_key: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = "http://localhost:11434"  # Ollama server (ignored for anthropic)
    llm_num_ctx: int = 8192  # Ollama context window; keep within 10 GB VRAM

    database_url: str = ""
    readonly_database_url: str = ""
    tfl_app_key: str = ""  # optional; anonymous TfL access works but is throttled

    timezone: str = "Europe/London"
    scheduler_enabled: bool = True
    cors_origins: str = "http://localhost:5173"

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    @model_validator(mode="after")
    def _database_urls(self) -> "Settings":
        if self.environment == "production":
            missing = [n for n, v in (("DATABASE_URL", self.database_url),
                                      ("READONLY_DATABASE_URL", self.readonly_database_url)) if not v]
            if missing:
                raise ValueError(f"{', '.join(missing)} must be set when ENVIRONMENT=production")
            if self.database_url == DEV_DATABASE_URL or self.readonly_database_url == DEV_READONLY_DATABASE_URL:
                raise ValueError("the development database credentials must not be used in production")
        self.database_url = self.database_url or DEV_DATABASE_URL
        self.readonly_database_url = self.readonly_database_url or DEV_READONLY_DATABASE_URL
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """The read/write URL in the form SQLAlchemy (Alembic, the APScheduler job store) expects for psycopg 3."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
