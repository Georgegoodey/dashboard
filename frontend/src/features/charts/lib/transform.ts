import type { ChartData, ChartSpec, Row, SeriesSpec } from "./spec";

export type Prepared = { rows: Row[]; series: SeriesSpec[]; xKey: string };

const num = (v: unknown) => (v === null || v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** Shapes raw SQL rows into what the renderer needs: numeric coercion and, for long-form results
 *  (x, group, value), a pivot into one column per group value. This is the only place data is reshaped. */
export function prepare(data: ChartData, spec: ChartSpec): Prepared {
  const xKey = spec.x ?? data.columns[0];

  if (spec.group && spec.series[0]) {
    const base = spec.series[0];
    const byX = new Map<string, Row>();
    const groups: string[] = [];
    for (const r of data.rows) {
      const xv = String(r[xKey]);
      const g = String(r[spec.group]);
      if (!byX.has(xv)) byX.set(xv, { [xKey]: r[xKey] });
      if (!groups.includes(g)) groups.push(g);
      byX.get(xv)![g] = num(r[base.field]);
    }
    return { rows: [...byX.values()], series: groups.map((g) => ({ ...base, field: g, name: g })), xKey };
  }

  const numeric = new Set<string>([
    ...spec.series.map((s) => s.field),
    ...(spec.type === "scatter" && spec.x ? [spec.x] : []),
    ...(spec.size ? [spec.size] : []),
    ...spec.details,
  ]);
  const rows = data.rows.map((r) => {
    const o: Row = { ...r };
    for (const f of numeric) if (f in o) o[f] = num(r[f]);
    return o;
  });
  return { rows, series: spec.series, xKey };
}
