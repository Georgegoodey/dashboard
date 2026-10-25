import { useSyncExternalStore } from "react";
import { storage } from "@/lib";

/**
 * The listing filters, one set for every panel that shows listings (Properties and Map), remembered in localStorage.
 * Changing a filter in one panel changes it in the other straight away, and it is still there after a reload.
 */
export type CommuteRule = { key: number; point: string; max: string };
export type Filters = {
  q: string;
  minBeds: string;
  minRent: string;
  maxRent: string;
  furnish: string[];
  has: string[];
  commute: CommuteRule[];
};

export const NO_FILTERS: Filters = { q: "", minBeds: "", minRent: "", maxRent: "", furnish: [], has: [], commute: [] };
export const FURNISH_OPTIONS = [
  { value: "furnished", label: "Furnished" },
  { value: "part_furnished", label: "Part furnished" },
  { value: "unfurnished", label: "Unfurnished" },
];
export const HAS_OPTIONS = [
  { value: "pets", label: "Pets allowed" },
  { value: "bills", label: "Bills included" },
  { value: "garden", label: "Garden" },
  { value: "parking", label: "Parking" },
  { value: "balcony", label: "Balcony" },
];

const KEY = "lettings.filters.v1";

const text = (v: unknown) => (typeof v === "string" ? v : "");
const only = (v: unknown, allowed: { value: string }[]) =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && allowed.some((a) => a.value === x)) : [];

/** What was saved, trusted only as far as its shape: anything unexpected falls back to no filter. */
export function parseFilters(raw: string | null): Filters {
  if (!raw) return NO_FILTERS;
  try {
    const v = JSON.parse(raw) as Record<string, unknown>;
    const rules = Array.isArray(v.commute) ? v.commute : [];
    return {
      q: text(v.q), minBeds: text(v.minBeds), minRent: text(v.minRent), maxRent: text(v.maxRent),
      furnish: only(v.furnish, FURNISH_OPTIONS), has: only(v.has, HAS_OPTIONS),
      commute: rules.flatMap((r): CommuteRule[] => {
        const rule = r as Record<string, unknown>;
        return typeof rule?.key === "number" ? [{ key: rule.key, point: text(rule.point) || "all", max: text(rule.max) }] : [];
      }),
    };
  } catch {
    return NO_FILTERS;
  }
}

let state: Filters = parseFilters(storage.get(KEY));
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

export function updateFilters(patch: Partial<Filters>): void {
  state = { ...state, ...patch };
  storage.set(KEY, JSON.stringify(state));
  notify();
}
export const resetFilters = () => updateFilters(NO_FILTERS);

// another browser tab changed them
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) { state = parseFilters(e.newValue); notify(); }
  });
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export function useFilters() {
  const filters = useSyncExternalStore(subscribe, () => state);
  return [filters, updateFilters, resetFilters] as const;
}

/** How many filters are set (a commute limit with no minutes does not count). */
export function countFilters(f: Filters): number {
  return [f.q.trim(), f.minBeds, f.minRent, f.maxRent].filter(Boolean).length + f.furnish.length + f.has.length
    + f.commute.filter((r) => r.max.trim() !== "").length;
}
