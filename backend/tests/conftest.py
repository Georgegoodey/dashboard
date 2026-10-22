"""Shared fixtures. Integration tests start one throwaway PostGIS container for the whole run (needs Docker) and
give every test a freshly migrated, empty schema by truncating the data tables."""
import os
import socket
from collections.abc import Iterator

import pytest

from app.core.config import Settings
from app.db import migrate
from app.db.database import Database

# The cleanup sidecar (Ryuk) cannot publish its port on Docker Desktop for Windows; the `with` block removes the container.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

IMAGE = "postgis/postgis:16-3.4"
DATA_TABLES = ("listing_price_history", "match_candidates", "commute_routes", "listings", "properties", "job_runs",
               "postcode_geo", "api_usage", "commute_points", "search_areas")


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def postgres_urls() -> Iterator[tuple[str, str]]:
    """(read/write URL, read-only URL) of a throwaway database. The role password is set by `provision_readonly_role`."""
    if not _docker_available():
        pytest.skip("Docker is not available")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(IMAGE, username="lettings", password="lettings", dbname="lettings") as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        host = "127.0.0.1" if host in ("localhost", "::1") else host
        # the container reports ready before it accepts TCP connections from the host
        socket.create_connection((host, int(port)), timeout=30).close()
        yield (f"postgresql://lettings:lettings@{host}:{port}/lettings",
               f"postgresql://lettings_ro:ro-test-password@{host}:{port}/lettings")


@pytest.fixture(scope="session")
def settings(postgres_urls: tuple[str, str]) -> Settings:
    return Settings(database_url=postgres_urls[0], readonly_database_url=postgres_urls[1], scheduler_enabled=False,
                    anthropic_api_key="", tfl_app_key="", llm_provider="ollama")


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> Iterator[Database]:
    db = Database(settings.database_url, settings.readonly_database_url)
    db.open()
    migrate.upgrade(db, settings.sqlalchemy_url)
    migrate.provision_readonly_role(db, settings.readonly_database_url)
    yield db
    db.close()


@pytest.fixture
def db(migrated_db: Database) -> Database:
    """The migrated database with all data tables emptied (reference data such as sources is kept)."""
    migrated_db.execute(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE")
    return migrated_db
