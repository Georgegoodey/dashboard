"""Schema migrations (Alembic) and read-only role provisioning.

Databases created before Alembic was adopted were migrated by a hand-rolled runner that recorded versions in
`schema_migrations`. `upgrade` stamps such a database at the matching Alembic revision first, so nothing is re-applied.
"""
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from app.db.database import Database

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
READONLY_ROLE = "lettings_ro"
MIGRATION_LOCK = 7_302_165_921      # an arbitrary number naming the advisory lock that serialises migrations
# legacy schema_migrations version -> Alembic revision
LEGACY = {"001_schema": "0001", "002_views_roles": "0002", "003_text_view": "0003", "004_search_filters": "0004"}


def alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url.replace("%", "%%"))
    return cfg


def head_revision(sqlalchemy_url: str) -> str:
    return ScriptDirectory.from_config(alembic_config(sqlalchemy_url)).get_current_head() or ""


def current_revision(db: Database) -> str | None:
    row = db.fetch_one("SELECT to_regclass('public.alembic_version') AS t")
    if not row or row["t"] is None:
        return None
    version = db.fetch_one("SELECT version_num FROM alembic_version")
    return version["version_num"] if version else None


def _stamp_legacy(db: Database, cfg: Config) -> str | None:
    """If the database predates Alembic, stamp the newest revision it already has. Returns that revision."""
    if current_revision(db) is not None:
        return None
    legacy = _legacy_revision(db)
    if legacy:
        command.stamp(cfg, legacy)
        log.info("stamped legacy database at Alembic revision %s", legacy)
    return legacy


@contextmanager
def _one_at_a_time(db: Database) -> Iterator[None]:
    """Hold a Postgres advisory lock while migrating. A second process starting at the same moment waits here, then finds
    nothing left to apply, instead of racing the first one through the same DDL."""
    with db.conn() as c:
        c.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            yield
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def upgrade(db: Database, sqlalchemy_url: str, revision: str = "head") -> list[str]:
    """Bring the schema to `revision`. Returns the revisions applied (oldest first)."""
    cfg = alembic_config(sqlalchemy_url)
    with _one_at_a_time(db):
        _stamp_legacy(db, cfg)
        before = current_revision(db)
        command.upgrade(cfg, revision)
        after = current_revision(db)
    if before == after:
        return []
    scripts = ScriptDirectory.from_config(cfg)
    walked = [s.revision for s in scripts.walk_revisions(base=before or "base", head=after or "base")]
    return [rev for rev in reversed(walked) if rev != before]


def status(db: Database, sqlalchemy_url: str) -> dict[str, list[str]]:
    """Migration files split into applied and pending, oldest first (names are the revision file names)."""
    scripts = ScriptDirectory.from_config(alembic_config(sqlalchemy_url))
    ordered = list(reversed(list(scripts.walk_revisions())))
    current = current_revision(db) or _legacy_revision(db)
    names = [Path(s.path).stem for s in ordered]
    if current is None:
        return {"applied": [], "pending": names}
    idx = next((i for i, s in enumerate(ordered) if s.revision == current), -1)
    return {"applied": names[: idx + 1], "pending": names[idx + 1:]}


def _legacy_revision(db: Database) -> str | None:
    if (db.fetch_one("SELECT to_regclass('public.schema_migrations') AS t") or {}).get("t") is None:
        return None
    done = {r["version"] for r in db.fetch_all("SELECT version FROM schema_migrations")}
    applied = [rev for legacy, rev in LEGACY.items() if legacy in done]
    return max(applied) if applied else None


def provision_readonly_role(db: Database, readonly_url: str) -> bool:
    """Set the read-only role's password from READONLY_DATABASE_URL, so no password lives in a migration.

    Returns False (and does nothing) if the URL names a different role than the one the migrations create.
    """
    info = conninfo_to_dict(readonly_url)
    if info.get("user") != READONLY_ROLE:
        log.warning("READONLY_DATABASE_URL user is %r, not %r: the role password was not managed", info.get("user"), READONLY_ROLE)
        return False
    password = info.get("password")
    with db.conn() as c:
        value = sql.Literal(password) if password else sql.SQL("NULL")
        stmt = sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(READONLY_ROLE), value)
        c.execute(stmt)
    return True
