import type { VisualizationSpec } from "vega-embed";
import type { Row } from "../lib";
import type { ChartTokens } from "../hooks/useChartTokens";

/** Shared look for every chart: axis, grid, legend and font settings all come from the shared tokens. */
export const base = (t: ChartTokens, rows: Row[]) => ({
  $schema: "https://vega.github.io/schema/vega-lite/v6.json",
  width: "container",
  height: "container",
  autosize: { type: "fit", contains: "padding" },
  padding: { top: 8, right: 8, bottom: 0, left: 0 },
  background: "transparent",
  data: { values: rows.map((r) => ({ ...r })) }, // Vega tags rows with ids, so it needs its own mutable copies
  config: {
    font: t.font,
    view: { stroke: null },
    range: { category: t.palette },
    axis: {
      labelFont: t.font, labelColor: t.muted, labelFontSize: 11, labelPadding: 8,
      titleFont: t.font, titleColor: t.muted, titleFontSize: 12, titleFontWeight: "normal",
      domainColor: t.border, tickColor: t.border, gridColor: t.border, gridDash: [2, 2], domainWidth: 2, tickWidth: 2,
    },
    axisX: { grid: false, ticks: false, title: null, labelAngle: 0, labelOverlap: true },
    axisY: { domain: false, ticks: false, title: null },
    legend: { labelFont: t.font, labelColor: t.muted, labelFontSize: 12, titleFont: t.font, titleColor: t.muted, symbolType: "square" },
  },
});

export const asSpec = (s: unknown) => s as VisualizationSpec; // specs are assembled from tokens at runtime, so literal types are widened
