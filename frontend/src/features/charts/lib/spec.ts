/** The one contract between back-end and front-end charts. The back-end infers a ChartSpec from a SQL result
 *  (backend/app/charts/infer.py); the generic Vega-Lite renderer draws any ChartSpec; the editor mutates it. */

export type Cell = string | number | null;
export type Row = Record<string, Cell>;

export type Fmt = "money" | "number" | "percent" | "percent_pt";
export type Role = "measure" | "temporal" | "dimension" | "label";
export type Kind = "bar" | "line" | "area" | "scatter";
export type ChartType = "bar" | "line" | "area" | "composed" | "pie" | "scatter" | "table";

export type SeriesSpec = { field: string; name: string; kind: Kind; axis: "left" | "right"; format: Fmt };

export type ChartSpec = {
  type: ChartType;
  x: string | null;
  xKind: "temporal" | "category" | "number";
  xFormat: Fmt | null;
  series: SeriesSpec[];
  group: string | null;
  stack: boolean;
  size: string | null;
  label: string | null;
  details: string[];
};

export type ChartData = { columns: string[]; types: string[]; rows: Row[]; truncated: boolean };

/** Everything the back-end returns for one SQL query. */
export type ChartResult = {
  data: ChartData;
  spec: ChartSpec;
  roles: Record<string, Role>;
  formats: Record<string, Fmt>;
};

export const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Bar" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  { value: "composed", label: "Combo" },
  { value: "pie", label: "Donut" },
  { value: "scatter", label: "Scatter" },
  { value: "table", label: "Table" },
];

/* ── spec edits: each returns a new, consistent spec so the renderer never sees a half-valid one ──── */

type Meta = Pick<ChartResult, "roles" | "formats" | "data">;

const humanize = (n: string) => {
  const s = n.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};
const measuresOf = (m: Meta) => m.data.columns.filter((c) => m.roles[c] === "measure");
export const xKindOf = (role?: Role): ChartSpec["xKind"] =>
  role === "temporal" ? "temporal" : role === "measure" ? "number" : "category";

const maxOf = (m: Meta, field: string) =>
  Math.max(0, ...m.data.rows.map((r) => Math.abs(Number(r[field]) || 0)));

export function seriesFor(field: string, kind: Kind, m: Meta, existing: SeriesSpec[] = []): SeriesSpec {
  // a measure far smaller than the existing series would be flattened on a shared axis, so give it its own
  const top = Math.max(0, ...existing.filter((s) => s.axis === "left").map((s) => maxOf(m, s.field)));
  const axis = existing.length && top && maxOf(m, field) < top * 0.05 ? "right" : "left";
  return { field, name: humanize(field), kind, axis, format: m.formats[field] ?? "number" };
}

const kindFor = (type: ChartType): Kind => (type === "line" || type === "area" ? type : "bar");

export function retype(spec: ChartSpec, type: ChartType, m: Meta): ChartSpec {
  const measures = measuresOf(m);
  const nonMeasures = m.data.columns.filter((c) => m.roles[c] !== "measure");

  if (type === "scatter") {
    const x = spec.x && m.roles[spec.x] === "measure" ? spec.x : measures.find((c) => !spec.series.some((s) => s.field === c)) ?? measures[0] ?? null;
    const y = spec.series.find((s) => s.field !== x)?.field ?? measures.find((c) => c !== x);
    return {
      ...spec, type, x, xKind: "number", xFormat: x ? m.formats[x] ?? "number" : null,
      series: y ? [seriesFor(y, "scatter", m)] : [], group: null, stack: false,
      label: spec.label ?? nonMeasures[0] ?? null,
    };
  }

  const x = spec.x && m.roles[spec.x] !== "measure" ? spec.x : nonMeasures[0] ?? spec.x;
  let series = spec.series.length ? spec.series : measures.slice(0, 1).map((f) => seriesFor(f, kindFor(type), m));
  if (type === "bar" || type === "line" || type === "area") series = series.map((s) => ({ ...s, kind: type }));
  if (type === "composed" && new Set(series.map((s) => s.kind)).size === 1 && series.length > 1) {
    series = series.map((s, i) => ({ ...s, kind: i === 0 ? "bar" : "line" }));
  }
  if (series.some((s) => s.kind === "scatter")) series = series.map((s) => ({ ...s, kind: kindFor(type) }));
  return { ...spec, type, x, xKind: xKindOf(x ? m.roles[x] : undefined), xFormat: null, series, size: null };
}

export function setX(spec: ChartSpec, field: string, m: Meta): ChartSpec {
  return {
    ...spec, x: field, xKind: xKindOf(m.roles[field]),
    xFormat: m.roles[field] === "measure" ? m.formats[field] ?? "number" : null,
    group: spec.group === field ? null : spec.group,
  };
}

export function toggleSeries(spec: ChartSpec, field: string, m: Meta): ChartSpec {
  if (spec.series.some((s) => s.field === field)) {
    const rest = spec.series.filter((s) => s.field !== field);
    return rest.length ? { ...spec, series: rest } : spec; // always keep one series
  }
  const kind: Kind = spec.type === "composed" ? "line" : spec.type === "scatter" ? "scatter" : kindFor(spec.type);
  return { ...spec, series: [...spec.series, seriesFor(field, kind, m, spec.series)] };
}

export function setGroup(spec: ChartSpec, group: string | null): ChartSpec {
  // grouping pivots the first series, so extra series would be ignored
  return { ...spec, group, series: group ? spec.series.slice(0, 1) : spec.series };
}
