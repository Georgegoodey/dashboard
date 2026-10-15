from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    anthropic_api_key: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = "http://localhost:11434"  # Ollama server (ignored for anthropic)
    llm_num_ctx: int = 8192  # Ollama context window; keep within 10 GB VRAM

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Postgres (docker compose up -d db). The read-only role can only see the curated views.
    database_url: str = "postgresql://lettings:lettings@127.0.0.1:5432/lettings"
    readonly_database_url: str = "postgresql://lettings_ro:lettings_ro@127.0.0.1:5432/lettings"
    tfl_app_key: str = ""  # optional; anonymous TfL access works but is throttled
    timezone: str = "Europe/London"
    scheduler_enabled: bool = True

    duckdb_path: str = "../data/dashboard.duckdb"
    upload_dir: str = "../data/uploads"
    cors_origins: str = "http://localhost:5173"

    chunk_size: int = 900
    chunk_overlap: int = 150

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


settings = Settings()
