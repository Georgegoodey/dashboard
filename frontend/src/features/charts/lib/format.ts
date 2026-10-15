/** Compact money, e.g. 2259894 -> $2.3M, 520000 -> $520k (matches d3-format "$.2~s" used by Vega). */
export function fmtMoneyShort(n: number) {
  const a = Math.abs(n);
  const [unit, suffix] = a >= 1e6 ? [1e6, "M"] : a >= 1e3 ? [1e3, "k"] : [1, ""];
  const v = n / unit;
  return `$${Math.abs(v) >= 100 ? Math.round(v) : +v.toPrecision(2)}${suffix}`;
}

export const fmtMoneyFull = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

/** A y-axis from 0..top in "nice" steps (1/2/5 x 10^n) with explicit ticks. Assumes non-negative values. */
export function niceAxis(values: number[]) {
  const max = Math.max(...values, 1);
  const raw = max / 5;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 5, 10].find((m) => m * pow >= raw) ?? 10) * pow;
  const top = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
  return { top, ticks };
}
