import { Badge, Button, Code, Disclosure, Empty, I, ICON_SIZE, Panel, Scroll, Spacer, Toolbar } from "@/components";
import { useChatStore } from "@/features/chat";

function pretty(input: unknown) {
  if (input && typeof input === "object" && "sql" in input) return String((input as { sql: string }).sql);
  return JSON.stringify(input, null, 2);
}

export default function TracePanel() {
  const trace = useChatStore((s) => s.trace);
  return (
    <Panel>
      <Toolbar>
        <Badge neutral>{trace.length} tool calls</Badge>
        <Spacer />
        <Button variant="ghost" size="sm" disabled={!trace.length} onClick={() => useChatStore.setState({ trace: [] })}>
          <I.clear size={ICON_SIZE} /> Clear
        </Button>
      </Toolbar>
      <Scroll>
        {trace.length === 0 && <Empty>Tool calls made by the agent appear here.</Empty>}
        {trace.map((t) => (
          <Disclosure
            key={t.id}
            title={<><I.tool size={ICON_SIZE} /> {t.name}</>}
            open={!t.output}
            meta={<Badge neutral>{t.endedAt ? `${t.endedAt - t.startedAt} ms` : "running…"}</Badge>}
          >
            <Code>{pretty(t.input)}</Code>
            {t.output && <Code out>{t.output}</Code>}
          </Disclosure>
        ))}
      </Scroll>
    </Panel>
  );
}
