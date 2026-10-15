"""The Runtime: everything the app shares (settings, database, portal clients, job runner, scheduler, chat agent).

It is created once per app (`create_app`) and stored on `app.state`; request handlers receive it through the
`get_rt` dependency, and jobs receive it as an argument. The only global is the single reference below, and it exists
for one reason: APScheduler stores jobs as importable string paths (`app.jobs.runner:scheduled_run`), so the function it
calls must find the live Runtime without being passed one.
"""
import asyncio
import logging

from app.agents.agent import ChatService
from app.core.config import Settings
from app.db import migrate
from app.db.database import Database
from app.jobs.runner import JobRunner
from app.jobs.tasks import JOBS
from app.scheduler import SchedulerService
from app.sources.rightmove import Rightmove

log = logging.getLogger("app")
RETRY_SECONDS = 15


class Runtime:
    def __init__(self, settings: Settings, db: Database | None = None) -> None:
        self.settings = settings
        self.db = db or Database(settings.database_url, settings.readonly_database_url)
        self.rightmove = Rightmove()          # one instance, so one shared throttle for search and detail pages
        self.runner = JobRunner(self, JOBS)
        self.scheduler = SchedulerService(self)
        self.chat = ChatService(settings, self.db)
        self.db_ok = False
        self.db_error = "not started"
        self.migrations_applied: list[str] = []

    async def _connect(self) -> None:
        await asyncio.to_thread(self.db.open)
        self.migrations_applied = await asyncio.to_thread(migrate.upgrade, self.db, self.settings.sqlalchemy_url)
        await asyncio.to_thread(migrate.provision_readonly_role, self.db, self.settings.readonly_database_url)
        self.db_ok, self.db_error = True, ""
        if self.settings.scheduler_enabled:
            await self.scheduler.start()

    async def start(self) -> None:
        """Connect, migrate and start the scheduler. A missing database does not stop the API: /health says why,
        and the connection is retried in the background until Postgres is back."""
        try:
            await self._connect()
        except Exception as e:
            log.warning("Postgres unavailable (%s: %s); retrying every %ss", type(e).__name__, e, RETRY_SECONDS)
            self.db_ok, self.db_error = False, f"{type(e).__name__}: {e}"
            self.scheduler.spawn_task(self._reconnect())

    async def _reconnect(self) -> None:
        while not self.db_ok:
            await asyncio.sleep(RETRY_SECONDS)
            try:
                await self._connect()
                log.info("Postgres is back; migrations applied: %s", self.migrations_applied or "none")
            except Exception as e:
                self.db_error = f"{type(e).__name__}: {e}"

    async def stop(self) -> None:
        await self.scheduler.stop()
        await asyncio.to_thread(self.db.close)


_current: Runtime | None = None


def set_runtime(rt: Runtime | None) -> None:
    global _current
    _current = rt


def get_runtime() -> Runtime:
    if _current is None:
        raise RuntimeError("the app is not running")
    return _current
