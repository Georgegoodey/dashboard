import { useMemo } from "react";
import type { VisualizationSpec } from "vega-embed";
import { useChartTokens } from "../hooks/useChartTokens";
import type { ChartTokens } from "../hooks/useChartTokens";
import { niceAxis } from "../lib";
import type { Row } from "../lib";
import { col, QueryKey } from "./queries";
import { asSpec, base } from "./theme";
import { VegaView } from "./VegaView";
import SampleChart from "./SampleChart";

/* Vega's d3-format has no pound sign, so GBP text is built with expressions (labelExpr / calculate). */
const gbpShort = (expr: string) => `'£' + format(${expr}, '.2~s')`;
const gbpFull = (field: string) => ({ calculate: `'£' + format(datum.${field}, ',.0f')`, as: `${field}_gbp` });

/** Money y-axis (GBP per month) with nice ticks. */
const rentY = (rows: Row[], field: string, values = col(rows, field)) => {
  const { top, ticks } = niceAxis(values);
  return {
    field, type: "quantitative",
    scale: { domain: [0, top], nice: false },
    axis: { values: ticks, labelExpr: gbpShort("datum.value"), tickCount: 5 },
  };
};
/** Count y-axis from zero with nice ticks. */
const countY = (rows: Row[], field: string) => {
  const { top, ticks } = niceAxis(col(rows, field));
  return { field, type: "quantitative", scale: { domain: [0, top], nice: false }, axis: { values: ticks, format: "d", tickCount: 5 } };
};

/* ── 1. Heatmap: average rent by borough and bedrooms. Rect layer + text layer, label colour flips with the value ── */

function heatSpec(t: ChartTokens, rows: Row[]) {
  const values = col(rows, "rent");
  const mid = (Math.min(...values) + Math.max(...values)) / 2;
  const byRent = { op: "mean", field: "rent", order: "descending" };
  return asSpec({
    ...base(t, rows),
    transform: [{ calculate: `'£' + format(datum.rent, '.2~s')`, as: "rent_label" }, gbpFull("rent")],
    encoding: {
      x: { field: "beds", type: "nominal", sort: { field: "beds", order: "ascending" }, axis: { labelAngle: 0, title: "Bedrooms" } },
      y: { field: "borough", type: "nominal", sort: byRent, axis: { domain: false } },
    },
    layer: [
      {
        mark: { type: "rect", stroke: t.surface, strokeWidth: 2 },
        encoding: {
          color: { field: "rent", type: "quantitative", scale: { range: [t.accentAlpha(0.06), t.accent] }, legend: null },
          tooltip: [
            { field: "borough", type: "nominal", title: "Borough" },
            { field: "beds", type: "nominal", title: "Bedrooms" },
            { field: "rent_gbp", type: "nominal", title: "Average rent" },
          ],
        },
      },
      {
        mark: { type: "text", font: t.font, fontSize: 10 },
        encoding: {
          text: { field: "rent_label", type: "nominal" },
          color: { condition: { test: `datum.rent > ${mid}`, value: "#fff" }, value: t.text },
        },
      },
    ],
  });
}

/* ── 2. Rent distribution by bedrooms, assembled from SQL quantiles: rule (5-95%), bar (IQR), tick (median) ── */

function boxSpec(t: ChartTokens, rows: Row[]) {
  const y = (field: string, extra = {}) => ({ field, type: "quantitative", scale: { zero: false }, ...extra });
  const tip = [
    { field: "beds", type: "nominal", title: "Bedrooms" },
    { field: "hi_gbp", type: "nominal", title: "95th percentile" }, { field: "q3_gbp", type: "nominal", title: "75th percentile" },
    { field: "med_gbp", type: "nominal", title: "Median" }, { field: "q1_gbp", type: "nominal", title: "25th percentile" },
    { field: "lo_gbp", type: "nominal", title: "5th percentile" },
    { field: "homes", type: "quantitative", title: "Homes", format: "," },
  ];
  return asSpec({
    ...base(t, rows),
    transform: ["lo", "q1", "med", "q3", "hi"].map(gbpFull),
    encoding: { x: { field: "beds", type: "nominal", sort: null, axis: { title: "Bedrooms" } } },
    layer: [
      {
        mark: { type: "rule", color: t.muted },
        encoding: { y: y("lo", { axis: { labelExpr: gbpShort("datum.value"), tickCount: 5, grid: true } }), y2: { field: "hi" } },
      },
      {
        mark: { type: "bar", size: 44, color: t.accentAlpha(0.3), stroke: t.accent, strokeWidth: 1.5 },
        encoding: { y: y("q1"), y2: { field: "q3" }, tooltip: tip },
      },
      { mark: { type: "tick", size: 44, thickness: 2.5, color: t.text }, encoding: { y: y("med") } },
    ],
  });
}

/* ── 3. Rent against commute, with a regression per bedroom count computed inside Vega-Lite ───────── */

function scatterSpec(t: ChartTokens, rows: Row[]) {
  const color = (legend: unknown) => ({
    field: "beds", type: "nominal", scale: { range: t.palette.slice(0, 3) }, legend,
  });
  return asSpec({
    ...base(t, rows),
    transform: [gbpFull("avg_rent")],
    layer: [
      {
        mark: { type: "point", shape: "square", filled: true, opacity: 0.85 },
        encoding: {
          x: { field: "commute_min", type: "quantitative", axis: { title: "Morning commute (minutes)", grid: false, tickCount: 6 } },
          y: { ...rentY(rows, "avg_rent"), scale: { zero: false }, axis: { labelExpr: gbpShort("datum.value"), tickCount: 5 } },
          size: { field: "homes", type: "quantitative", scale: { range: [60, 520] }, legend: null },
          color: color({ title: null, orient: "top", direction: "horizontal" }),
          tooltip: [
            { field: "beds", type: "nominal", title: "Bedrooms" },
            { field: "commute_min", type: "quantitative", title: "Commute (min)" },
            { field: "avg_rent_gbp", type: "nominal", title: "Average rent" },
            { field: "homes", type: "quantitative", title: "Homes", format: "," },
          ],
        },
      },
      {
        transform: [{ regression: "avg_rent", on: "commute_min", groupby: ["beds"] }],
        mark: { type: "line", strokeWidth: 2, strokeDash: [4, 3] },
        encoding: {
          x: { field: "commute_min", type: "quantitative" },
          y: { field: "avg_rent", type: "quantitative" },
          color: color(null),
        },
      },
    ],
  });
}

/* ── 4. New listings per week by bedrooms: rolling mean (window transform), legend-click isolation, pivoted tooltip ── */

const SERIES = ["0", "1", "2", "3+"];

function linesSpec(t: ChartTokens, rows: Row[]) {
  const color = (legend: unknown) => ({
    field: "beds", type: "nominal", scale: { domain: SERIES, range: t.palette.slice(0, 4) }, legend,
  });
  const hover = { condition: { param: "hover", empty: false, value: 1 }, value: 0 };
  return asSpec({
    ...base(t, rows),
    transform: [
      { window: [{ op: "mean", field: "homes", as: "smooth" }], frame: [-1, 0], groupby: ["beds"], sort: [{ field: "week" }] },
    ],
    encoding: { x: { field: "week", type: "ordinal" } },
    layer: [
      {
        // raw weekly counts, faint
        mark: { type: "line", strokeWidth: 1, opacity: 0.25, interpolate: "monotone" },
        encoding: { y: countY(rows, "homes"), color: color(null) },
      },
      {
        // 2-week rolling mean; clicking a legend entry isolates a bedroom count
        params: [{ name: "cat", select: { type: "point", fields: ["beds"] }, bind: "legend" }],
        mark: { type: "line", strokeWidth: 2.5, interpolate: "monotone" },
        encoding: {
          y: { field: "smooth", type: "quantitative" },
          color: color({ title: "Bedrooms", orient: "top", direction: "horizontal" }),
          opacity: { condition: { param: "cat", value: 1 }, value: 0.15 },
        },
      },
      {
        // invisible points drive the nearest-week hover selection
        params: [{ name: "hover", select: { type: "point", fields: ["week"], nearest: true, on: "pointerover", clear: "pointerout" } }],
        mark: { type: "point", opacity: 0 },
        encoding: { y: { field: "smooth", type: "quantitative" } },
      },
      {
        // pivot to one row per week so a single tooltip lists every series
        transform: [{ pivot: "beds", value: "smooth", groupby: ["week"] }],
        mark: { type: "rule", color: t.border },
        encoding: {
          opacity: hover,
          tooltip: [{ field: "week", type: "ordinal", title: "Week of" },
            ...SERIES.map((sr) => ({ field: sr, type: "quantitative", title: `${sr} bed`, format: ".1f" }))],
        },
      },
    ],
  });
}

/* ── components ─────────────────────────────────────────────────────────────────────────────────── */

function make(query: QueryKey, height: number, build: (t: ChartTokens, rows: Row[]) => VisualizationSpec) {
  return function VegaSample() {
    const t = useChartTokens();
    return (
      <SampleChart query={query} library="Vega-Lite" height={height}>
        {(rows) => <SpecView build={() => build(t, rows)} deps={[t, rows]} />}
      </SampleChart>
    );
  };
}

/** Memoises the spec so a chart is only re-embedded when its data or the theme change. */
function SpecView({ build, deps }: { build: () => VisualizationSpec; deps: unknown[] }) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const spec = useMemo(build, deps);
  return <VegaView spec={spec} />;
}

export const VegaHeatmap = make("vgHeat", 280, heatSpec);
export const VegaBoxplot = make("vgBox", 280, boxSpec);
export const VegaRegression = make("vgScatter", 300, scatterSpec);
export const VegaLines = make("vgLines", 320, linesSpec);
