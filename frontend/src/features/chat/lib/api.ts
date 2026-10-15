import { useChatStore } from "./store";

/** POST /api/chat and consume the SSE stream, dispatching into the store. */
export async function sendChat(message: string) {
  const s = useChatStore.getState();
  s.addMessage({ role: "user", content: message });
  s.setStreaming(true);
  s.setError(undefined);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: s.sessionId, message }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split(/\r?\n\r?\n/);
      buf = frames.pop() ?? "";
      for (const f of frames) handleFrame(f);
    }
  } catch (e) {
    useChatStore.getState().setError(String(e));
  } finally {
    useChatStore.getState().setStreaming(false);
  }
}

function handleFrame(frame: string) {
  let event = "message";
  let data = "";
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  const d = JSON.parse(data);
  const st = useChatStore.getState();
  if (event === "token") st.appendToken(d.text);
  else if (event === "tool_start") {
    st.startTool({ id: d.id, name: d.name, input: d.input, startedAt: Date.now() });
    if (d.name === "query_sql" && typeof d.input?.sql === "string") st.addResult(d.id, d.input.sql);
  } else if (event === "tool_end") {
    st.endTool(d.id, d.output);
    if (d.name === "query_sql") st.endResult(d.id, !/^SQL (error|failed)/.test(String(d.output)));
  }
  else if (event === "error") st.setError(d.message);
}
