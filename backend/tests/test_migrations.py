"""Alembic migrations against a real PostGIS database."""
import pytest
from alembic import command

from app.core.config import Settings
from app.db import migrate
from app.db.database import Database

pytestmark = pytest.mark.integration


@pytest.fixture
def blank_db(postgres_urls: tuple[str, str]) -> Database:
    """A second, empty database inside the same container."""
    import psycopg

    admin = psycopg.connect(postgres_urls[0], autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS migtest WITH (FORCE)")
    admin.execute("CREATE DATABASE migtest")
    admin.close()
    url = postgres_urls[0].rsplit("/", 1)[0] + "/migtest"
    db = Database(url, postgres_urls[1].rsplit("/", 1)[0] + "/migtest")
    db.open()
    return db


def _url(db: Database) -> str:
    return db._url.replace("postgresql://", "postgresql+psycopg://", 1)


def test_upgrade_creates_schema_views_and_role(blank_db: Database) -> None:
    applied = migrate.upgrade(blank_db, _url(blank_db))
    assert applied == ["0001", "0002", "0003", "0004", "0005"]
    assert migrate.current_revision(blank_db) == "0005"
    views = {r["table_name"] for r in blank_db.fetch_all("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")}
    assert {"v_properties", "v_price_changes", "v_property_text", "v_job_runs"} <= views
    role = blank_db.fetch_one("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'lettings_ro'")
    assert role and role["rolcanlogin"]
    assert migrate.upgrade(blank_db, _url(blank_db)) == []          # idempotent
    blank_db.close()


def test_no_password_is_stored_in_any_migration() -> None:
    """The read-only role's password comes from READONLY_DATABASE_URL at startup, never from source control."""
    from pathlib import Path

    for path in (Path(migrate.BACKEND_DIR) / "migrations" / "versions").glob("*.py"):
        assert "PASSWORD" not in path.read_text(encoding="utf-8").upper(), path.name


def test_downgrade_to_base_and_back(blank_db: Database) -> None:
    url = _url(blank_db)
    migrate.upgrade(blank_db, url)
    command.downgrade(migrate.alembic_config(url), "base")
    tables = blank_db.fetch_all("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'properties'")
    assert tables == []
    assert migrate.upgrade(blank_db, url) == ["0001", "0002", "0003", "0004", "0005"]
    blank_db.close()


def test_legacy_database_is_stamped_not_reapplied(blank_db: Database) -> None:
    """A database made by the old hand-rolled runner (schema_migrations, no alembic_version) upgrades cleanly."""
    url = _url(blank_db)
    migrate.upgrade(blank_db, url, "0004")
    blank_db.execute("DROP TABLE alembic_version")
    blank_db.execute("CREATE TABLE schema_migrations (version text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
    blank_db.execute("INSERT INTO schema_migrations (version) VALUES ('001_schema'), ('002_views_roles'), ('003_text_view'), ('004_search_filters')")
    assert migrate.status(blank_db, url)["pending"] == ["0005_text_search"]
    assert migrate.upgrade(blank_db, url) == ["0005"]                # only the new one runs
    assert migrate.current_revision(blank_db) == "0005"
    blank_db.close()


def test_readonly_password_comes_from_the_url(blank_db: Database, settings: Settings) -> None:
    migrate.upgrade(blank_db, _url(blank_db))
    ro_url = settings.readonly_database_url.rsplit("/", 1)[0] + "/migtest"
    assert migrate.provision_readonly_role(blank_db, ro_url)
    import psycopg

    with psycopg.connect(ro_url) as c:
        assert c.execute("SELECT 1").fetchone() == (1,)
    blank_db.close()
