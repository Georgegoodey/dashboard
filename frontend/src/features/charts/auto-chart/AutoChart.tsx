import { useMemo } from "react";
import type { VisualizationSpec } from "vega-embed";
import { DataTable, Empty } from "@/components";
import { useChartTokens } from "../hooks/useChartTokens";
import type { ChartTokens } from "../hooks/useChartTokens";
import { prepare } from "../lib";
import type { ChartData, ChartSpec, Fmt, SeriesSpec } from "../lib";
import { asSpec, base } from "../vega/theme";
import { VegaView } from "../vega/VegaView";

/** The single generic renderer. It turns any ChartSpec (bar/line/area/combo with dual axes and stacking,
 *  donut, scatter/bubble, table) into a Vega-Lite spec, so adapting to new back-end data means changing the
 *  ChartSpec, never this code. */
export default function AutoChart({
  data,
  spec,
  formats,
}: {
  data: ChartData;
  spec: ChartSpec;
  formats: Record<string, Fmt>;
}) {
  const t = useChartTokens();
  const isTable = spec.type === "table" || !spec.x || spec.series.length === 0;
  const empty = !data.rows.length;
  const vl = useMemo(
    () => (isTable || empty ? null : build(t, data, spec, formats)),
    [t, data, spec, formats, isTable, empty],
  );

  if (isTable) {
    return (
      <div className="chart-table">
        <DataTable columns={data.columns} rows={data.rows.map((r) => data.columns.map((c) => r[c]))} />
      </div>
    );
  }
  if (!vl) return <Empty>The query returned no rows.</Empty>;
  return <VegaView spec={vl} />;
}

/* ── formats: d3-format strings for Vega axes and tooltips ───────────────────────────────────────── */

const AXIS_FMT: Record<Fmt, string> = { money: "$.2~s", number: ",.2~f", percent: ".0%", percent_pt: ".1f" };
const TIP_FMT: Record<Fmt, string> = { money: "$,.0f", number: ",.2~f", percent: ".1%", percent_pt: ".1f" };

const axisOf = (f: Fmt) => ({ format: AXIS_FMT[f], ...(f === "percent_pt" ? { labelExpr: "datum.label + '%'" } : {}) });
const label = (field: string) => {
  const s = field.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

function build(t: ChartTokens, data: ChartData, spec: ChartSpec, formats: Record<string, Fmt>): VisualizationSpec {
  const prepared = prepare(data, spec);
  const fmtOf = (field: string): Fmt => formats[field] ?? "number";
  const detail = (field: string) => ({ field, type: "quantitative", title: label(field), format: TIP_FMT[fmtOf(field)] });
  const details = spec.details.map(detail);
  const common = { ...base(t, prepared.rows), config: { ...base(t, prepared.rows).config } };

  if (spec.type === "pie") return donut(t, common, prepared.xKey, prepared.series[0], fmtOf, details);
  if (spec.type === "scatter") return scatter(t, common, spec, prepared.xKey, prepared.series[0], fmtOf, details);
  return cartesian(t, common, spec, prepared.xKey, prepared.series, fmtOf);
}

type Common = ReturnType<typeof base>;

function donut(
  t: ChartTokens, common: Common, xKey: string, s: SeriesSpec, fmtOf: (f: string) => Fmt, details: object[],
): VisualizationSpec {
  return asSpec({
    ...common,
    mark: { type: "arc", innerRadius: 52, stroke: t.surface, strokeWidth: 2 },
    encoding: {
      theta: { field: s.field, type: "quantitative", stack: true },
      color: { field: xKey, type: "nominal", sort: null, scale: { range: t.palette }, legend: { title: null, orient: "right" } },
      tooltip: [
        { field: xKey, type: "nominal", title: label(xKey) },
        { field: s.field, type: "quantitative", title: s.name, format: TIP_FMT[fmtOf(s.field)] },
        ...details.filter((d) => (d as { field: string }).field !== s.field),
      ],
    },
  });
}

const MAX_LABELLED = 25;

function scatter(
  t: ChartTokens, common: Common, spec: ChartSpec, xKey: string, s: SeriesSpec, fmtOf: (f: string) => Fmt, details: object[],
): VisualizationSpec {
  const tooltip = [
    ...(spec.label ? [{ field: spec.label, type: "nominal", title: label(spec.label) }] : []),
    { field: xKey, type: "quantitative", title: label(xKey), format: TIP_FMT[fmtOf(xKey)] },
    { field: s.field, type: "quantitative", title: s.name, format: TIP_FMT[fmtOf(s.field)] },
    ...details.filter((d) => ![xKey, s.field].includes((d as { field: string }).field)),
  ];
  const encoding = {
    x: { field: xKey, type: "quantitative", scale: { zero: false, nice: true }, axis: { ...axisOf(fmtOf(xKey)), title: label(xKey), grid: true } },
    y: { field: s.field, type: "quantitative", scale: { zero: false, nice: true }, axis: { ...axisOf(fmtOf(s.field)), title: s.name } },
  };
  // text labels only help when there is room for them; with many points they pile up, so leave those to the tooltip
  const labelled = !!spec.label && (common.data as { values: unknown[] }).values.length <= MAX_LABELLED;
  return asSpec({
    ...common,
    encoding,
    layer: [
      {
        mark: { type: "point", shape: "square", filled: true, opacity: spec.size ? 0.55 : 0.8, color: t.accent },
        encoding: {
          ...(spec.size ? { size: { field: spec.size, type: "quantitative", scale: { range: [40, 600] }, legend: null } } : {}),
          tooltip,
        },
      },
      ...(labelled
        ? [{ mark: { type: "text", dy: -10, fontSize: 10, color: t.muted }, encoding: { text: { field: spec.label, type: "nominal" } } }]
        : []),
    ],
  });
}

function cartesian(
  t: ChartTokens, common: Common, spec: ChartSpec, xKey: string, series: SeriesSpec[], fmtOf: (f: string) => Fmt,
): VisualizationSpec {
  const names = series.map((s) => s.name);
  // column names can be anything (grouped values like "Home & Garden"), so fold over safe aliases
  const alias = series.map((_, i) => `_s${i}`);
  const rows = (common.data as { values: Record<string, unknown>[] }).values.map((r) => {
    const o = { ...r };
    series.forEach((s, i) => (o[alias[i]] = r[s.field]));
    return o;
  });
  const nameExpr = series.reduceRight(
    (acc, s, i) => `datum._k === ${JSON.stringify(alias[i])} ? ${JSON.stringify(s.name)} : ${acc}`,
    "''",
  );

  const x =
    spec.xKind === "number"
      ? { field: xKey, type: "quantitative", axis: { ...axisOf(fmtOf(xKey)), title: null } }
      : { field: xKey, type: "ordinal", sort: null, axis: { labelAngle: series.length && rows.length > 14 ? -40 : 0 } };

  // one layer per (kind, axis): series of the same kind share a fold so they can stack or sit side by side
  const groups = new Map<string, number[]>();
  series.forEach((s, i) => {
    const key = `${s.kind === "scatter" ? "line" : s.kind}|${s.axis}`;
    groups.set(key, [...(groups.get(key) ?? []), i]);
  });

  const color = {
    field: "_s", type: "nominal", sort: names,
    scale: { domain: names, range: t.palette },
    legend: names.length > 1 ? { title: null, orient: "top", direction: "horizontal" } : null,
  };

  const layer = [...groups].map(([key, idx]) => {
    const [kind, axis] = key.split("|");
    const f = series[idx[0]].format;
    const mark =
      kind === "bar" ? { type: "bar" }
      : kind === "area" ? { type: "area", opacity: 0.75, line: { strokeWidth: 2 } }
      : { type: "line", strokeWidth: 2.5, point: { shape: "square", filled: true, size: 36 } };
    const stacked = kind !== "line" && spec.stack;
    return {
      transform: [
        { fold: idx.map((i) => alias[i]), as: ["_k", "_v"] },
        { calculate: nameExpr, as: "_s" },
      ],
      mark,
      encoding: {
        y: {
          field: "_v", type: "quantitative", stack: stacked ? "zero" : null,
          axis: { ...axisOf(f), title: null, orient: axis === "right" ? "right" : "left", grid: axis !== "right" },
        },
        color,
        ...(kind === "bar" && !stacked && idx.length > 1 ? { xOffset: { field: "_s", sort: names } } : {}),
        tooltip: [
          { field: xKey, type: spec.xKind === "number" ? "quantitative" : "ordinal", title: label(xKey) },
          { field: "_s", type: "nominal", title: "Series" },
          { field: "_v", type: "quantitative", title: "Value", format: TIP_FMT[f] },
        ],
      },
    };
  });

  return asSpec({
    ...common,
    data: { values: rows },
    encoding: { x },
    layer,
    ...(series.some((s) => s.axis === "right") ? { resolve: { scale: { y: "independent" } } } : {}),
  });
}
