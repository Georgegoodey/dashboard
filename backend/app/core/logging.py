"""Logging, configured once at startup.

Every record carries the id of the job run or request that produced it (`run_id`), so one run's lines can be found
in the output. Set LOG_FORMAT=json for structured output.
"""
import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

run_id_var: ContextVar[str] = ContextVar("run_id", default="-")

_TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(run_id)s] %(message)s"
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "run_id"}


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", "-"),
            "message": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED and not k.startswith("_")})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Idempotent: replaces only the handler this function installed, so reloads and tests do not stack handlers."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_lettings", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(_TEXT_FORMAT))
    handler.addFilter(RunIdFilter())
    handler._lettings = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
