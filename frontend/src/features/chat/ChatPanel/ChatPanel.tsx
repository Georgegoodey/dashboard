import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge, Button, Empty, Footer, I, ICON_SIZE, Note, Panel, Scroll, Spacer, Toolbar } from "@/components";
import { ResultView } from "@/features/charts";
import { runDemo, sendChat, useChatStore } from "../lib";
import "./chat-panel.css";

export default function ChatPanel() {
  const { messages, streaming, error, demo, reset } = useChatStore();
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const submit = () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    useChatStore.getState().setDemo(false);
    void sendChat(text);
  };

  return (
    <Panel>
      <Toolbar>
        <Badge neutral>{demo ? "Sample conversation" : "Live agent"}</Badge>
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => void runDemo()} disabled={streaming}>
          <I.run size={ICON_SIZE} /> Run sample
        </Button>
        <Button variant="ghost" size="sm" onClick={reset} disabled={streaming}>
          <I.clear size={ICON_SIZE} /> Clear
        </Button>
      </Toolbar>
      <Scroll>
        {messages.length === 0 && (
          <Empty>
            Ask about your datasets, e.g. “Does discounting hurt ratings?”
            <br />
            No API key yet? Click <b>Run sample</b> to see how answers and tool calls look.
          </Empty>
        )}
        {messages.map((m, i) => {
          // failed queries stay visible in the Agent Trace panel; chat only shows results that worked
          const results = (m.results ?? []).filter((r) => r.ok !== false);
          return (
            <div key={i} className={`msg ${m.role}${results.length ? " has-results" : ""}`}>
              {results.map((r) => (
                <ResultView key={r.id} sql={r.sql} />
              ))}
              {m.content && (
                <div className="md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              )}
            </div>
          );
        })}
        <div ref={endRef} />
      </Scroll>
      {error && (
        <Note kind="error">
          <div>{error}</div>
          <Button variant="soft" size="sm" onClick={() => void runDemo()} disabled={streaming}>
            Show a sample conversation instead
          </Button>
        </Note>
      )}
      <Footer className="composer">
        <textarea
          className="input"
          value={input}
          placeholder="Message the agent (Enter to send, Shift+Enter for newline)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <Button onClick={submit} disabled={streaming || !input.trim()}>
          <I.send size={ICON_SIZE} weight="fill" />
          {streaming ? "…" : "Send"}
        </Button>
      </Footer>
    </Panel>
  );
}
