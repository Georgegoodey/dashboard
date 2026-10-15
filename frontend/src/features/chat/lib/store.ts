import { create } from "zustand";

/** A SQL result attached to an assistant message; rendered as a chart or table by ResultView. */
export type ChatResult = { id: string; sql: string; ok?: boolean };
export type ChatMsg = { role: "user" | "assistant"; content: string; results?: ChatResult[] };
export type ToolCall = {
  id: string;
  name: string;
  input: unknown;
  output?: string;
  startedAt: number;
  endedAt?: number;
};

type State = {
  sessionId: string;
  messages: ChatMsg[];
  streaming: boolean;
  trace: ToolCall[];
  error?: string;
  demo: boolean;
  setDemo: (v: boolean) => void;
  setStreaming: (v: boolean) => void;
  addMessage: (m: ChatMsg) => void;
  appendToken: (t: string) => void;
  startTool: (t: ToolCall) => void;
  endTool: (id: string, output: string) => void;
  addResult: (id: string, sql: string) => void;
  endResult: (id: string, ok: boolean) => void;
  setError: (e?: string) => void;
  reset: () => void;
};

export const useChatStore = create<State>((set) => ({
  sessionId: crypto.randomUUID(),
  messages: [],
  streaming: false,
  demo: false,
  setDemo: (demo) => set({ demo }),
  trace: [],
  setStreaming: (streaming) => set({ streaming }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  appendToken: (t) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last?.role === "assistant") msgs[msgs.length - 1] = { ...last, content: last.content + t };
      else msgs.push({ role: "assistant", content: t });
      return { messages: msgs };
    }),
  startTool: (t) => set((s) => ({ trace: [...s.trace, t] })),
  endTool: (id, output) =>
    set((s) => ({
      trace: s.trace.map((t) => (t.id === id ? { ...t, output, endedAt: Date.now() } : t)),
    })),
  addResult: (id, sql) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      const result: ChatResult = { id, sql };
      if (last?.role === "assistant") msgs[msgs.length - 1] = { ...last, results: [...(last.results ?? []), result] };
      else msgs.push({ role: "assistant", content: "", results: [result] });
      return { messages: msgs };
    }),
  endResult: (id, ok) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.results?.some((r) => r.id === id) ? { ...m, results: m.results.map((r) => (r.id === id ? { ...r, ok } : r)) } : m,
      ),
    })),
  setError: (error) => set({ error }),
  reset: () => set({ sessionId: crypto.randomUUID(), messages: [], trace: [], error: undefined, demo: false }),
}));
