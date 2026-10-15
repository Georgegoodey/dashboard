"""Settings safety rules and logging."""
import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import DEV_DATABASE_URL, DEV_READONLY_DATABASE_URL, Settings
from app.core.logging import run_id_var, setup_logging

PROD_URL = "postgresql://app:s3cret@db.internal:5432/lettings"
PROD_RO_URL = "postgresql://lettings_ro:other@db.internal:5432/lettings"


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_development_falls_back_to_the_compose_database() -> None:
    s = make()
    assert s.database_url == DEV_DATABASE_URL and s.readonly_database_url == DEV_READONLY_DATABASE_URL
    assert s.sqlalchemy_url.startswith("postgresql+psycopg://")


def test_production_requires_explicit_urls() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL, READONLY_DATABASE_URL must be set"):
        make(environment="production")
    with pytest.raises(ValidationError, match="READONLY_DATABASE_URL must be set"):
        make(environment="production", database_url=PROD_URL)


def test_production_refuses_the_development_credentials() -> None:
    with pytest.raises(ValidationError, match="development database credentials"):
        make(environment="production", database_url=DEV_DATABASE_URL, readonly_database_url=PROD_RO_URL)
    ok = make(environment="production", database_url=PROD_URL, readonly_database_url=PROD_RO_URL)
    assert ok.database_url == PROD_URL


def test_cors_origins_are_split() -> None:
    assert make(cors_origins="http://a.test, http://b.test ,").cors_origin_list == ["http://a.test", "http://b.test"]


def test_log_lines_carry_the_run_id(capfd: pytest.CaptureFixture[str]) -> None:
    setup_logging("INFO", "text")
    token = run_id_var.set("scrape_rightmove#42")
    try:
        logging.getLogger("jobs").info("hello")
    finally:
        run_id_var.reset(token)
    logging.getLogger("jobs").info("outside")
    err = capfd.readouterr().err
    assert "[scrape_rightmove#42] hello" in err and "[-] outside" in err


def test_json_logs_and_idempotent_setup(capfd: pytest.CaptureFixture[str]) -> None:
    setup_logging("INFO", "json")
    setup_logging("INFO", "json")                                   # a reload must not stack handlers
    logging.getLogger("x").info("one line", extra={"rows": 3})
    lines = [line for line in capfd.readouterr().err.splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "one line" and record["rows"] == 3 and record["level"] == "INFO" and record["run_id"] == "-"
    setup_logging("INFO", "text")
