import { Badge, Empty, Note } from "@/components";
import { ChartCard } from "../ChartCard";
import { useChartResult } from "../hooks/useChartResult";
import type { ChartSpec } from "../lib";
import ChartWorkbench from "./ChartWorkbench";

export type ChartDef = {
  id: string;
  title: string;
  /** What the SQL returns; the chart type itself is inferred, not declared. */
  subtitle: string;
  sql: string;
  height?: number;
  override?: Partial<ChartSpec>;
};

/** SQL in, chart out: runs the query through the back-end pipeline and hands the result to the workbench. */
export default function DataChart({ def }: { def: ChartDef }) {
  const { data: result, error, isPending } = useChartResult(def.sql);

  if (result) {
    return <ChartWorkbench result={result} title={def.title} subtitle={def.subtitle} height={def.height} override={def.override} />;
  }
  return (
    <ChartCard title={def.title} subtitle={def.subtitle} badge={<Badge neutral>…</Badge>} height={def.height}>
      {isPending && <Empty>Running query…</Empty>}
      {error && <Note kind="error">{error.message}. Has the Rightmove search job run? See the Jobs panel.</Note>}
    </ChartCard>
  );
}
