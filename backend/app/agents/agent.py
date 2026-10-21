"""The lettings text-to-SQL chat agent (LangGraph ReAct) and its server-sent-event stream."""
import json
from collections.abc import AsyncIterator
from typing import Any

from app.agents.llm import get_llm
from app.agents.tools import build_tools, reset_sql_errors
from app.core.config import Settings
from app.db.database import Database
from app.rag.schema import SchemaContext

SYSTEM_PROMPT = """You are a lettings assistant. Answer questions about rental properties by writing PostgreSQL SQL against the views below, then explaining what you found.

How to work:
1. Use the views and columns exactly as listed. Start with v_properties; join v_property_text (property_id = v_properties.id) only for advert wording, and v_commutes (property_id = v_properties.id) for journey times.
2. Write ONE SELECT and run it with query_sql. If it errors, read the message, fix the query and retry.
3. The user sees every successful result automatically as a chart or table above your reply, so do not repeat rows or paste a table: state the key finding in a sentence or two with specific numbers.
4. Give computed columns clear aliases. When listing properties include id, address and url. Limit lists to 20 rows unless asked for more.
5. Never invent data. A property with no v_commutes row for a point has not had that journey computed yet: say so instead of treating it as zero minutes. If the views cannot answer, say so.
6. To find properties by what the advert SAYS (garden, balcony, pets, quiet, "off-street parking"), call search_descriptions first, then use the ids it returns in a query_sql query (WHERE id IN (...)) to rank or filter on rent, bedrooms and commute.

Conventions:
- Money is GBP per calendar month (rent_pcm) and fare_pence in v_commutes is in pence.
- The user has any number of commute points (v_commute_points, e.g. Work, Gym). v_commutes has one row per property, point and journey, with duration_min door to door by public transport. A point may have several journeys (morning and evening), so use max(duration_min) per point for 'within N minutes of it'. Match points by label with ILIKE.
- PostgreSQL dialect: date_trunc, extract, interval, ILIKE, percentile_cont(0.5) WITHIN GROUP (ORDER BY x), FILTER (WHERE ...), casts with ::numeric.
- Simple word matches can also be written in SQL: description ILIKE '%garden%'.

Examples:
Q: cheapest 2 bed homes under 40 minutes to work
SELECT p.id, p.address, p.rent_pcm, max(c.duration_min) AS work_min, p.url FROM v_properties p JOIN v_commutes c ON c.property_id = p.id WHERE p.bedrooms = 2 AND c.point_label ILIKE 'work' GROUP BY p.id, p.address, p.rent_pcm, p.url HAVING max(c.duration_min) <= 40 ORDER BY p.rent_pcm LIMIT 20
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


class ThinkFilter:
    """Drops <think>...</think> spans from a token stream, even when a tag is split across chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
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


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _evt(kind: str, **data: Any) -> dict[str, str]:
    return {"event": kind, "data": json.dumps(data, default=str)}


class ChatService:
    """Builds the agent for each request (so its prompt reflects the current schema) and streams its events.

    Conversation memory is kept in-process per session id; it is cleared when the backend restarts.
    """

    def __init__(self, settings: Settings, db: Database) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        self._settings = settings
        self._schema = SchemaContext(db)
        self._tools = build_tools(db, self._schema)
        self._memory = MemorySaver()

    def build_agent(self) -> Any:
        from langgraph.prebuilt import create_react_agent

        prompt = SYSTEM_PROMPT.format(schema=self._schema.text())
        return create_react_agent(get_llm(self._settings), self._tools, prompt=prompt, checkpointer=self._memory)

    async def stream(self, session_id: str, message: str) -> AsyncIterator[dict[str, str]]:
        """Yield SSE events: token | tool_start | tool_end | done | error."""
        if self._settings.llm_provider == "anthropic" and not self._settings.anthropic_api_key:
            yield _evt("error", message="ANTHROPIC_API_KEY is not set. Add it to .env and restart the backend.")
            return
        think = ThinkFilter()
        reset_sql_errors()
        try:
            agent = self.build_agent()
            # recursion_limit bounds the tool loop so a confused local model cannot spin forever
            cfg = {"configurable": {"thread_id": session_id}, "recursion_limit": 12}
            async for ev in agent.astream_events({"messages": [("user", message)]}, config=cfg, version="v2"):
                kind = ev["event"]
                if kind == "on_chat_model_stream":
                    t = think.feed(_text(ev["data"]["chunk"].content))
                    if t:
                        yield _evt("token", text=t)
                elif kind == "on_tool_start":
                    yield _evt("tool_start", id=ev["run_id"], name=ev["name"], input=ev["data"].get("input"))
                elif kind == "on_tool_end":
                    out = ev["data"].get("output")
                    out = getattr(out, "content", out)
                    yield _evt("tool_end", id=ev["run_id"], name=ev["name"], output=str(out)[:4000])
            if tail := think.flush():
                yield _evt("token", text=tail)
            yield _evt("done")
        except Exception as e:
            yield _evt("error", message=f"{type(e).__name__}: {e}")
