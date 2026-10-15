import json
from functools import lru_cache
from typing import AsyncIterator

from app.agents.llm import get_llm
from app.agents.tools import TOOLS, reset_sql_errors
from app.core.config import settings
from app.db import schema_context
from app.db.database import db

SYSTEM_PROMPT = """You are a lettings assistant. Answer questions about rental properties by writing PostgreSQL SQL against the views below, then explaining what you found.

How to work:
1. Use the views and columns exactly as listed. Start with v_properties; join v_property_text (property_id = v_properties.id) only for advert wording.
2. Write ONE SELECT and run it with query_sql. If it errors, read the message, fix the query and retry.
3. The user sees every successful result automatically as a chart or table above your reply, so do not repeat rows or paste a table: state the key finding in a sentence or two with specific numbers.
4. Give computed columns clear aliases. When listing properties include id, address and url. Limit lists to 20 rows unless asked for more.
5. Never invent data. Commute columns are NULL until computed: say so instead of treating NULL as zero. If the views cannot answer, say so.

Conventions:
- Money is GBP per calendar month (rent_pcm); work_fare_pence is in pence.
- *_min columns are door-to-door public transport minutes: work_am = morning journey to work, work_pm = evening journey from work, home_min = journey to the home place.
- PostgreSQL dialect: date_trunc, extract, interval, ILIKE, percentile_cont(0.5) WITHIN GROUP (ORDER BY x), FILTER (WHERE ...), casts with ::numeric.
- Advert wording lives in v_property_text: description ILIKE '%garden%'.

Examples:
Q: cheapest 2 bed homes under 40 minutes to work
SELECT id, address, rent_pcm, work_am_min, url FROM v_properties WHERE bedrooms = 2 AND work_am_min <= 40 ORDER BY rent_pcm LIMIT 20
Q: average rent by borough for 2 beds
SELECT borough, round(avg(rent_pcm)) AS avg_rent, count(*) AS homes FROM v_properties WHERE bedrooms = 2 GROUP BY borough ORDER BY avg_rent
Q: price drops this week
SELECT address, prev_rent_pcm, new_rent_pcm, change_pct, observed_at FROM v_price_changes WHERE change_pct < 0 AND observed_at > now() - interval '7 days' ORDER BY change_pct
Q: places with a garden
SELECT p.id, p.address, p.rent_pcm, p.url FROM v_properties p JOIN v_property_text t ON t.property_id = p.id WHERE t.description ILIKE '%garden%' ORDER BY p.rent_pcm LIMIT 20
Q: when was the data last refreshed
SELECT job_id, max(finished_at) AS last_ok FROM v_job_runs WHERE status = 'ok' GROUP BY job_id

VIEWS
{schema}"""


def build_agent():
    from langgraph.prebuilt import create_react_agent

    # rebuilt per request so the prompt always reflects the currently loaded tables
    prompt = SYSTEM_PROMPT.format(schema=schema_context.schema_context())
    return create_react_agent(get_llm(), TOOLS, prompt=prompt, checkpointer=_memory())


class ThinkFilter:
    """Drops <think>...</think> spans from a token stream, even when a tag is split across chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, text: str) -> str:
        self.buf += text
        out: list[str] = []
        while True:
            tag = self.CLOSE if self.inside else self.OPEN
            i = self.buf.find(tag)
            if i >= 0:
                if not self.inside:
                    out.append(self.buf[:i])
                self.buf = self.buf[i + len(tag):]
                self.inside = not self.inside
                continue
            keep = max((k for k in range(1, len(tag)) if self.buf.endswith(tag[:k])), default=0)
            if not self.inside:
                out.append(self.buf[: len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            return "".join(out)

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf = ""
        return rest


@lru_cache(maxsize=1)
def _memory():
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _save(session_id: str, role: str, content: str) -> None:
    with db() as con:
        con.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                    [session_id, role, content])


def _evt(kind: str, **data) -> dict:
    return {"event": kind, "data": json.dumps(data, default=str)}


async def stream_chat(session_id: str, message: str) -> AsyncIterator[dict]:
    """Yield SSE events: token | tool_start | tool_end | done | error."""
    if settings.llm_provider == "anthropic" and not settings.anthropic_api_key:
        yield _evt("error", message="ANTHROPIC_API_KEY is not set. Add it to .env and restart the backend.")
        return
    _save(session_id, "user", message)
    answer: list[str] = []
    think = ThinkFilter()
    reset_sql_errors()
    try:
        agent = build_agent()
        # recursion_limit bounds the tool loop so a confused local model cannot spin forever
        cfg = {"configurable": {"thread_id": session_id}, "recursion_limit": 12}
        async for ev in agent.astream_events(
            {"messages": [("user", message)]}, config=cfg, version="v2"
        ):
            kind = ev["event"]
            if kind == "on_chat_model_stream":
                t = think.feed(_text(ev["data"]["chunk"].content))
                if t:
                    answer.append(t)
                    yield _evt("token", text=t)
            elif kind == "on_tool_start":
                yield _evt("tool_start", id=ev["run_id"], name=ev["name"], input=ev["data"].get("input"))
            elif kind == "on_tool_end":
                out = ev["data"].get("output")
                out = getattr(out, "content", out)
                yield _evt("tool_end", id=ev["run_id"], name=ev["name"], output=str(out)[:4000])
        if tail := think.flush():
            answer.append(tail)
            yield _evt("token", text=tail)
        _save(session_id, "assistant", "".join(answer))
        yield _evt("done")
    except Exception as e:
        yield _evt("error", message=f"{type(e).__name__}: {e}")
