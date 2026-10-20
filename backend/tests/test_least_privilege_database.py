"""The Raspberry Pi database set-up (deploy/pi/bootstrap.sh) gives the app a normal, non-superuser role.

This test repeats that set-up on a fresh PostGIS server and checks the app still migrates and provisions its read-only
role. It has its own container because roles belong to the whole server, and the shared test container already has
`lettings_ro` (created by a superuser), which would hide the "the app creates it itself" path.
"""
import socket

import pytest

from app.db import migrate
from app.db.database import Database
from tests.conftest import IMAGE, _docker_available

pytestmark = pytest.mark.integration

APP_PASSWORD = "app-test-password"
RO_PASSWORD = "ro-test-password"


def test_the_app_runs_without_superuser_rights() -> None:
    if not _docker_available():
        pytest.skip("Docker is not available")
    import psycopg
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(IMAGE, username="postgres", password="admin-test-password", dbname="postgres") as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        host = "127.0.0.1" if host in ("localhost", "::1") else host
        socket.create_connection((host, int(port)), timeout=30).close()

        # what bootstrap.sh does, as the superuser: the app role (CREATEROLE only), its database, and the extensions
        with psycopg.connect(f"postgresql://postgres:admin-test-password@{host}:{port}/postgres", autocommit=True) as admin:
            admin.execute(f"CREATE ROLE lettings LOGIN CREATEROLE PASSWORD '{APP_PASSWORD}'")
            admin.execute("CREATE DATABASE lettings OWNER lettings")
        with psycopg.connect(f"postgresql://postgres:admin-test-password@{host}:{port}/lettings", autocommit=True) as admin:
            admin.execute("CREATE EXTENSION postgis")
            admin.execute("CREATE EXTENSION pg_trgm")

        app_url = f"postgresql://lettings:{APP_PASSWORD}@{host}:{port}/lettings"
        ro_url = f"postgresql://lettings_ro:{RO_PASSWORD}@{host}:{port}/lettings"
        db = Database(app_url, ro_url)
        db.open()
        try:
            me = db.fetch_one("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            assert me and me["rolsuper"] is False

            assert migrate.upgrade(db, app_url.replace("postgresql://", "postgresql+psycopg://", 1))
            assert migrate.provision_readonly_role(db, ro_url) is True
            assert migrate.upgrade(db, app_url.replace("postgresql://", "postgresql+psycopg://", 1)) == []

            # the read-only role works with the password the app set, and cannot write
            with psycopg.connect(ro_url) as ro:
                assert ro.execute("SELECT count(*) FROM v_properties").fetchone() == (0,)
                with pytest.raises(psycopg.errors.Error):
                    ro.execute("CREATE TABLE should_not_exist (id int)")
        finally:
            db.close()
