import type { ReactNode } from "react";
import { Badge, Empty, Note } from "@/components";
import { ChartCard } from "../ChartCard";
import { QUERIES, QueryKey, Row, useChartQuery } from "./queries";

/** Runs a chart's SQL query and hands the rows to a library-specific renderer inside a shared card. */
export default function SampleChart({
  query,
  height,
  children,
}: {
  query: QueryKey;
  height?: number;
  children: (rows: Row[]) => ReactNode;
}) {
  const { data, error, isPending } = useChartQuery(query);
  const meta = QUERIES[query];
  return (
    <ChartCard title={meta.title} subtitle={meta.subtitle} badge={<Badge>{meta.kind}</Badge>} height={height}>
      {isPending && <Empty>Running query…</Empty>}
      {error && <Note kind="error">{error.message}. Has a search job run? See the Jobs panel.</Note>}
      {data && children(data)}
    </ChartCard>
  );
}
