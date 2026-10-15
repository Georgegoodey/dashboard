import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, DataTable, I, ICON_SIZE, Note, Panel, Scroll, Section, Segmented, Spacer, Toolbar } from "@/components";
import { chartApi, ChartWorkbench } from "@/features/charts";

type View = "table" | "chart";

/** SQL console on the same pipeline as the chart gallery: one query, viewable as a table or an editable chart. */
export default function SqlPanel() {
  const [sql, setSql] = useState("SELECT id, address, rent_pcm, bedrooms, borough, work_am_min FROM v_properties ORDER BY rent_pcm LIMIT 20");
  const [view, setView] = useState<View>("table");
  const run = useMutation({ mutationFn: chartApi.chart });
  const result = run.data;

  return (
    <Panel>
      <Toolbar>
        <Button size="sm" onClick={() => run.mutate(sql)} disabled={run.isPending}>
          <I.run size={ICON_SIZE} weight="fill" /> Run
        </Button>
        <span className="muted">Ctrl+Enter · read-only · max 500 rows</span>
        <Spacer />
        <Segmented<View> value={view} onChange={setView} options={[
            { value: "table", label: <><I.table size={ICON_SIZE} /> Table</> },
            { value: "chart", label: <><I.chart size={ICON_SIZE} /> Chart</> },
          ]} />
      </Toolbar>
      <Section>
        <textarea
          className="input mono"
          rows={3}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run.mutate(sql);
          }}
        />
      </Section>
      {run.error && <Note kind="error">{run.error.message}</Note>}
      <Scroll>
        {result && view === "table" && (
          <DataTable columns={result.data.columns} rows={result.data.rows.map((r) => result.data.columns.map((c) => r[c]))} />
        )}
        {result && view === "chart" && (
          <ChartWorkbench result={result} title="Result" subtitle="Inferred from the query's columns; adjust below" height={300} startOpen />
        )}
      </Scroll>
    </Panel>
  );
}
