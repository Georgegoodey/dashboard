import { useQuery } from "@tanstack/react-query";
import { chartApi } from "../api";
import type { Row } from "../lib";

export type { Row } from "../lib";

/** Vega-Lite chart queries. (The inferred-chart gallery lives in charts/gallery.ts and is drawn by the generic pipeline.) */
export const QUERIES = {
  vgHeat: {
    kind: "Comparison",
    title: "Rent by borough and bedroom count",
    subtitle: "Mean monthly rent (£). Darker cells are costlier; compare across a row for the premium per extra bedroom",
    sql: `SELECT borough, bedrooms::text AS beds, round(avg(rent_pcm)) AS rent
FROM v_properties
WHERE borough IS NOT NULL AND bedrooms BETWEEN 0 AND 4
GROUP BY borough, bedrooms`,
  },
  vgBox: {
    kind: "Distribution",
    title: "Rent spread by bedroom count",
    subtitle: "Median, interquartile range and 5th to 95th percentile of monthly rent. Wide boxes mean prices vary a lot",
    sql: `SELECT bedrooms::text AS beds,
       round(percentile_cont(0.05) WITHIN GROUP (ORDER BY rent_pcm)::numeric) AS lo,
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY rent_pcm)::numeric) AS q1,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY rent_pcm)::numeric) AS med,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY rent_pcm)::numeric) AS q3,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY rent_pcm)::numeric) AS hi,
       count(*) AS homes
FROM v_properties
WHERE bedrooms BETWEEN 0 AND 4
GROUP BY bedrooms ORDER BY bedrooms`,
  },
  vgScatter: {
    kind: "Correlation",
    title: "Is a shorter commute priced in?",
    subtitle: "Mean rent against morning commute, with a linear trend per bedroom count. A downward slope means shorter commutes cost more",
    sql: `SELECT bedrooms::text AS beds,
       (round(work_am_min / 5.0) * 5)::int AS commute_min,
       round(avg(rent_pcm)) AS avg_rent,
       count(*) AS homes
FROM v_properties
WHERE work_am_min IS NOT NULL AND bedrooms BETWEEN 1 AND 3
GROUP BY 1, 2
HAVING count(*) >= 3
ORDER BY 1, 2`,
  },
  vgLines: {
    kind: "Trend",
    title: "Weekly supply by bedroom count",
    subtitle: "New adverts first seen each week. Click the legend to isolate a size; hover for every value that week",
    sql: `SELECT to_char(date_trunc('week', current_date - days_on_market), 'YYYY-MM-DD') AS week,
       CASE WHEN bedrooms >= 3 THEN '3+' ELSE bedrooms::text END AS beds,
       count(*) AS homes
FROM v_properties
WHERE bedrooms IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2`,
  },
} as const;

export type QueryKey = keyof typeof QUERIES;

/** Runs the query (react-query dedupes by key) and returns rows as objects. */
export function useChartQuery(key: QueryKey) {
  return useQuery({
    queryKey: ["chart-sql", key],
    queryFn: async (): Promise<Row[]> => {
      const { columns, rows } = await chartApi.sql(QUERIES[key].sql);
      return rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i] as string | number | null])));
    },
  });
}

export const col = (rows: Row[], key: string) => rows.map((r) => Number(r[key]) || 0);
