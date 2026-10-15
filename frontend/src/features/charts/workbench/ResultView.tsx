import { useState } from "react";
import { Badge, DataTable, Empty, I, ICON_SIZE, Note, Segmented } from "@/components";
import { ChartCard } from "../ChartCard";
import { useChartResult } from "../hooks/useChartResult";
import ChartWorkbench from "./ChartWorkbench";

type View = "chart" | "table";

/** A SQL result shown in chat. It goes through the same /api/chart pipeline as the gallery, so the chart is
 *  inferred from the result and can be customised; the switch flips between that chart and the raw table. */
export default function ResultView({ sql }: { sql: string }) {
  const { data: result, error, isPending } = useChartResult(sql);
  const [chosen, setChosen] = useState<View | null>(null);

  const subtitle = sql.replace(/\s+/g, " ").slice(0, 110);
  if (!result) {
    return (
      <ChartCard title="Query result" subtitle={subtitle} badge={<Badge neutral>…</Badge>} height={96}>
        {isPending && <Empty>Running query…</Empty>}
        {error && <Note kind="error">{error.message}</Note>}
      </ChartCard>
    );
  }

  const { data, spec } = result;
  // a single row or an uncharted shape reads better as a table; anything the back-end could chart opens as a chart
  const view: View = chosen ?? (spec.type === "table" || data.rows.length < 2 ? "table" : "chart");
  const switcher = (
    <Segmented<View>
      value={view}
      onChange={setChosen}
      options={[
        { value: "chart", label: <><I.chart size={ICON_SIZE} /> Chart</> },
        { value: "table", label: <><I.table size={ICON_SIZE} /> Table</> },
      ]}
    />
  );
  const meta = `${data.rows.length} row${data.rows.length === 1 ? "" : "s"} · ${subtitle}`;

  if (view === "chart") {
    return <ChartWorkbench result={result} title="Query result" subtitle={meta} height={260} extraActions={switcher} />;
  }
  return (
    <ChartCard
      title="Query result"
      subtitle={meta}
      actions={switcher}
      badge={<Badge>table</Badge>}
      height={Math.min(300, 56 + data.rows.length * 40)}
    >
      <div className="chart-table">
        <DataTable columns={data.columns} rows={data.rows.map((r) => data.columns.map((c) => r[c]))} />
      </div>
    </ChartCard>
  );
}
