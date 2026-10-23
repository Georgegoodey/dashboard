import { useMemo } from "react";
import { Button, Chip, Field, I, ICON_SIZE, Select } from "@/components";
import { useDebounced } from "@/hooks";
import { CommuteFilter, useCommuteLimits } from "../commute";
import type { PropertyFilters } from "../lib";
import { countFilters, FURNISH_OPTIONS, HAS_OPTIONS, resetFilters, useFilters } from "./store";

const BEDS = [{ value: "", label: "Any beds" }, ...[0, 1, 2, 3, 4].map((n) => ({ value: String(n), label: n === 0 ? "Studio+" : `${n}+ beds` }))];
const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s.replace(/[£,\s]/g, ""))) ? undefined : Number(s.replace(/[£,\s]/g, "")));

const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

/** The filters as the API takes them, once typing has settled. The same for every panel, because the filters are shared. */
export function useListingQuery(): { query: PropertyFilters; count: number } {
  const [f] = useFilters();
  const { params } = useCommuteLimits();
  const query = useDebounced<PropertyFilters>({
    q: f.q.trim() || undefined, min_beds: num(f.minBeds), min_rent: num(f.minRent), max_rent: num(f.maxRent),
    furnish: f.furnish.length ? f.furnish : undefined, has: f.has.length ? f.has : undefined, commute: params,
  });
  return { query, count: useMemo(() => countFilters(f), [f]) };
}

/**
 * The filter fields, shared by Properties and Map. They read and write one remembered set, so what you set in one panel is
 * already set in the other. A panel adds its own controls (sort, colour) around this.
 */
export function ListingFilters() {
  const [f, set] = useFilters();
  const limits = useCommuteLimits();
  const count = countFilters(f);
  return (
    <>
      <Field label="Search">
        <input className="input" placeholder="address or headline" value={f.q} onChange={(e) => set({ q: e.target.value })} />
      </Field>
      <Field label="Bedrooms"><Select value={f.minBeds} onChange={(minBeds) => set({ minBeds })} options={BEDS} /></Field>
      <Field label="Min rent £/month">
        <input className="input" inputMode="numeric" placeholder="any" value={f.minRent} onChange={(e) => set({ minRent: e.target.value })} />
      </Field>
      <Field label="Max rent £/month">
        <input className="input" inputMode="numeric" placeholder="any" value={f.maxRent} onChange={(e) => set({ maxRent: e.target.value })} />
      </Field>
      <div className="filters-wide filters-chips">
        <div className="field">
          <span className="field-label">Furnishing</span>
          <div className="chips">
            {FURNISH_OPTIONS.map((o) => (
              <Chip key={o.value} on={f.furnish.includes(o.value)} onClick={() => set({ furnish: toggle(f.furnish, o.value) })}>{o.label}</Chip>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="field-label">Must have</span>
          <div className="chips">
            {HAS_OPTIONS.map((o) => (
              <Chip key={o.value} on={f.has.includes(o.value)} onClick={() => set({ has: toggle(f.has, o.value) })}>{o.label}</Chip>
            ))}
          </div>
        </div>
        {count > 0 && (
          <Button variant="ghost" size="sm" onClick={resetFilters} title="Clear every filter, in both Properties and Map">
            <I.reset size={ICON_SIZE} /> Clear {count} filter{count === 1 ? "" : "s"}
          </Button>
        )}
      </div>
      <CommuteFilter limits={limits} />
      {f.furnish.length > 0 && <div className="filters-wide muted small">Homes whose advert does not say how they are furnished are hidden while a furnishing is chosen.</div>}
    </>
  );
}

