import { useEffect, useState } from "react";

/** Theme values resolved to plain sRGB strings, because chart libraries cannot read CSS variables
 *  (and Radix serves display-p3 colors on wide-gamut screens, which Vega cannot parse). */
export type ChartTokens = {
  font: string;
  text: string;
  muted: string;
  border: string;
  surface: string;
  accent: string;
  accentAlpha: (a: number) => string;
  /** Categorical series colors, defined per theme as --chart-1..6 in tokens.css. */
  palette: string[];
};

const PALETTE_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6"];

let ctx: CanvasRenderingContext2D | null = null;

function toRgb(cssValue: string): [number, number, number] {
  ctx ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!ctx) return [0, 0, 0];
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = "#000";
  ctx.fillStyle = cssValue; // ignored if unparsable
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data; // canvas is sRGB, so this converts p3 -> sRGB
  return [r, g, b];
}

function read(): ChartTokens {
  const cs = getComputedStyle(document.documentElement);
  const rgb = (name: string) => `rgb(${toRgb(cs.getPropertyValue(name).trim()).join(",")})`;
  const accentRgb = toRgb(cs.getPropertyValue("--accent").trim());
  return {
    font: cs.getPropertyValue("--font").trim() || "system-ui, sans-serif",
    text: rgb("--text"),
    muted: rgb("--text-muted"),
    border: rgb("--border"),
    surface: rgb("--surface"),
    accent: `rgb(${accentRgb.join(",")})`,
    accentAlpha: (a) => `rgba(${accentRgb.join(",")},${a})`,
    palette: PALETTE_VARS.map(rgb),
  };
}

/** Re-reads tokens whenever the light/dark class on <html> changes. */
export function useChartTokens(): ChartTokens {
  const [tokens, setTokens] = useState(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setTokens(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => mo.disconnect();
  }, []);
  return tokens;
}

/** "rgb(r,g,b)" + alpha -> "rgba(r,g,b,a)". Palette entries are always in the rgb() form produced above. */
export const withAlpha = (rgb: string, a: number) => rgb.replace(/^rgb\((.*)\)$/, `rgba($1,${a})`);
