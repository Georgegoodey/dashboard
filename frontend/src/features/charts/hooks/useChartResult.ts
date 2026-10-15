import { useQuery } from "@tanstack/react-query";
import { chartApi } from "../api";

/** Runs SQL through the back-end chart pipeline (rows + inferred spec). React-query dedupes identical SQL. */
export function useChartResult(sql: string) {
  return useQuery({ queryKey: ["chart", sql], queryFn: () => chartApi.chart(sql) });
}
