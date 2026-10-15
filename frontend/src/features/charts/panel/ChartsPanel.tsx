import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Button, Code, Disclosure, I, ICON_SIZE, Panel, Scroll, Spacer, Toolbar } from "@/components";
import { GALLERY } from "../gallery";
import { QUERIES } from "../vega/queries";
import { VegaBoxplot, VegaHeatmap, VegaLines, VegaRegression } from "../vega/samples";
import { DataChart } from "../workbench";

/** The chart panel shell: a header, the charts, and the SQL behind them. */
function ChartPanel({
  summary,
  queries,
  children,
}: {
  summary: string;
  queries: { title: string; sql: string }[];
  children: ReactNode;
}) {
  const qc = useQueryClient();
  return (
    <Panel>
      <Toolbar>
        <span className="muted">{summary}</span>
        <Spacer />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            qc.invalidateQueries({ queryKey: ["chart"] });
            qc.invalidateQueries({ queryKey: ["chart-sql"] });
          }}
        >
          <I.rerun size={ICON_SIZE} /> Re-run
        </Button>
      </Toolbar>
      <Scroll>
        {children}
        <Disclosure title="SQL" meta={`${queries.length} queries`}>
          {queries.map((q) => (
            <Code key={q.title}>{`-- ${q.title}\n${q.sql}`}</Code>
          ))}
        </Disclosure>
      </Scroll>
    </Panel>
  );
}

export const ChartsPanel = () => (
  <ChartPanel
    summary={`${4 + GALLERY.length} analyses, recomputed from live listings`}
    queries={[...Object.values(QUERIES), ...GALLERY]}
  >
    <VegaHeatmap />
    <VegaBoxplot />
    <VegaRegression />
    <VegaLines />
    {GALLERY.map((def) => (
      <DataChart key={def.id} def={def} />
    ))}
  </ChartPanel>
);
