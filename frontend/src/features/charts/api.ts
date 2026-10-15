import { jsonInit, request } from "@/lib";
import type { ChartResult, ChartSpec, Fmt, Role, Row } from "./lib";

export type SqlResult = { columns: string[]; rows: unknown[][] };

type ChartResponse = {
  columns: string[]; types: string[]; rows: unknown[][]; truncated: boolean;
  spec: ChartSpec; roles: Record<string, Role>; formats: Record<string, Fmt>;
};

export const chartApi = {
  /** Run SQL and get back the rows plus the back-end's inferred chart spec: the one pipeline every chart uses. */
  chart: (sql: string): Promise<ChartResult> =>
    request<ChartResponse>("/api/chart", jsonInit("POST", { sql })).then((r) => ({
      data: {
        columns: r.columns,
        types: r.types,
        truncated: r.truncated,
        rows: r.rows.map((row) => Object.fromEntries(r.columns.map((c, i) => [c, row[i]])) as Row),
      },
      spec: r.spec,
      roles: r.roles,
      formats: r.formats,
    })),
  sql: (sql: string) => request<SqlResult>("/api/sql", jsonInit("POST", { sql })),
};
