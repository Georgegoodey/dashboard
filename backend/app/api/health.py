"""GET /health: is the API up, is the database reachable, is a chat model available."""
import json
import urllib.request
from typing import Any

from fastapi import APIRouter

from app.api.deps import Rt
from app.core.config import Settings

router = APIRouter()


def llm_status(settings: Settings) -> tuple[bool, str]:
    """(configured, reason). Never raises: a missing LLM must not take the API down."""
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return (True, "") if settings.anthropic_api_key else (False, "ANTHROPIC_API_KEY is not set")
    if provider == "ollama":
        url = f"{settings.llm_base_url.rstrip('/')}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310  (operator-configured http URL)
                names = {m.get("name") for m in json.load(r).get("models", [])}
        except Exception as e:
            # the address is only useful to the developer; in production /health is public to everyone on the network
            where = "" if settings.environment == "production" else f" at {settings.llm_base_url}"
            return False, f"Ollama not reachable{where} ({type(e).__name__})"
        wanted = settings.llm_model
        if wanted in names or (":" not in wanted and f"{wanted}:latest" in names):
            return True, ""
        return False, f"model '{wanted}' is not pulled (run: ollama pull {wanted})"
    return False, f"unknown LLM_PROVIDER '{settings.llm_provider}'"


@router.get("/health")
def health(rt: Rt) -> Any:
    configured, reason = llm_status(rt.settings)
    return {
        "status": "ok",
        "llm_configured": configured,
        "llm_provider": rt.settings.llm_provider,
        "llm_model": rt.settings.llm_model,
        "llm_reason": reason,
        "tfl_key_configured": bool(rt.settings.tfl_app_key),
        "database_ok": rt.db_ok,
        "database_error": rt.db_error,
    }
