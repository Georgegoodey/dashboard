"""Production switches that need no database: the app is built but its lifespan (database, scheduler) is never started."""
from fastapi.testclient import TestClient

from app.api.health import llm_status
from app.core.config import Settings
from app.main import create_app

PROD_DB = "postgresql://app:not-the-dev-password@127.0.0.1:5432/lettings"
PROD_RO = "postgresql://app_ro:not-the-dev-password@127.0.0.1:5432/lettings"


def _settings(environment: str) -> Settings:
    return Settings(environment=environment, database_url=PROD_DB, readonly_database_url=PROD_RO, scheduler_enabled=False,
                    llm_provider="ollama", llm_base_url="http://127.0.0.1:9")  # port 9 refuses at once


def test_interactive_docs_and_schema_are_off_in_production() -> None:
    client = TestClient(create_app(_settings("production")))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_interactive_docs_stay_on_in_development() -> None:
    client = TestClient(create_app(_settings("development")))
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_health_hides_the_model_address_in_production_only() -> None:
    prod = llm_status(_settings("production"))
    dev = llm_status(_settings("development"))
    assert prod[0] is False and "127.0.0.1" not in prod[1] and "not reachable" in prod[1]
    assert dev[0] is False and "http://127.0.0.1:9" in dev[1]
