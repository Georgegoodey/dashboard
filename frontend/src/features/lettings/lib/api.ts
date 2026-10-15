/** Typed client for the lettings endpoints (properties, settings, jobs). */

import { jsonInit as send, request as call } from "@/lib";

export type Property = {
  id: number;
  url: string | null;
  address: string | null;
  headline: string | null;
  sources: string | null;
  rent_pcm: number | null;
  deposit: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  property_type: string | null;
  furnished: string | null;
  let_type: string | null;
  available_from: string | null;
  postcode: string | null;
  outcode: string | null;
  borough: string | null;
  days_on_market: number;
  price_changes: number;
  rent_vs_median_pct: number | null;
  work_am_min: number | null;
  work_am_transfers: number | null;
  work_am_walk_min: number | null;
  work_pm_min: number | null;
  work_pm_transfers: number | null;
  work_fare_pence: number | null;
  home_min: number | null;
  distance_to_home_km: number | null;
  distance_to_work_km: number | null;
  lat: number | null;
  lon: number | null;
};

export type PropertyFilters = {
  q?: string;
  min_rent?: number;
  max_rent?: number;
  min_beds?: number;
  max_beds?: number;
  max_commute?: number;
  borough?: string;
  furnished?: string;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type MapPoint = {
  id: number; lat: number; lon: number; address: string | null; url: string | null; rent_pcm: number | null;
  bedrooms: number | null; borough: string | null; work_am_min: number | null; work_pm_min: number | null;
  rent_vs_median_pct: number | null; days_on_market: number;
};

export type PropertyDetail = {
  property: Property;
  listings: {
    source: string; url: string; status: string; rent_pcm: number; deposit: number | null; furnished: string | null;
    let_type: string | null; min_term_months: number | null; available_from: string | null; agent_name: string | null;
    headline: string | null; description: string | null; key_features: string[] | null; first_seen: string; last_seen: string;
  }[];
  price_history: { observed_at: string; rent_pcm: number | null; status: string | null }[];
  commutes: {
    slug: string; label: string; ref_date: string; duration_min: number | null; walk_min: number | null;
    transfers: number | null; fare_pence: number | null; summary: string | null;
  }[];
};

export type Status = {
  active_listings: number; properties: number; detail_pending: number; areas: number; places: number; commute_pending: number;
};
export type Area = { id: number; label: string; outcode: string; enabled: boolean; properties: number };
export type SearchFilters = { min_bedrooms: number | null; max_bedrooms: number | null; max_rent: number | null };
export type Place = { kind: "home" | "work"; label: string; address: string | null; postcode: string; lat: number; lon: number };
export type Profile = {
  slug: string; label: string; place_kind: "home" | "work"; direction: string; anchor: string;
  local_time: string; weekday: number; enabled: boolean;
};
export type JobRun = {
  started_at: string; finished_at: string | null; status: string; trigger: string | null;
  rows_added: number; rows_updated: number; detail: Record<string, unknown> | null; error: string | null;
};
export type Job = {
  id: string; title: string; description: string; enabled: boolean; interval_minutes: number;
  active_from: string | null; active_to: string | null; running: boolean; next_run: string | null;
  last_ok: string | null; last_run: JobRun | null;
};
export type RunRow = {
  id: number; job_id: string; started_at: string; finished_at: string | null; status: string; trigger: string | null;
  rows_added: number; rows_updated: number; error: string | null;
};
export type Health = {
  status: string; database_ok: boolean; database_error: string; llm_configured: boolean; llm_provider: string;
  llm_model: string; llm_reason: string; tfl_key_configured: boolean;
};

export const lettings = {
  health: () => call<Health>("/health"),
  status: () => call<Status>("/api/status"),

  properties: (f: PropertyFilters) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== "" && v !== null) p.set(k, String(v));
    return call<{ total: number; rows: Property[] }>(`/api/properties?${p}`);
  },
  mapPoints: (f: PropertyFilters) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== "" && v !== null) p.set(k, String(v));
    return call<{ total: number; points: MapPoint[] }>(`/api/properties/map?${p}`);
  },
  property: (id: number) => call<PropertyDetail>(`/api/properties/${id}`),

  areas: () => call<Area[]>("/api/areas"),
  addArea: (outcode: string, label?: string) => call("/api/areas", send("POST", { outcode, label })),
  setArea: (id: number, enabled: boolean) => call(`/api/areas/${id}`, send("PUT", { enabled })),
  deleteArea: (id: number) => call(`/api/areas/${id}`, send("DELETE")),

  filters: () => call<SearchFilters>("/api/filters"),
  setFilters: (f: SearchFilters) =>
    call<SearchFilters & { hidden: number; restored: number }>("/api/filters", send("PUT", f)),

  places: () => call<Place[]>("/api/places"),
  setPlace: (kind: "home" | "work", postcode: string, label?: string) =>
    call<{ postcode: string; borough: string | null }>(`/api/places/${kind}`, send("PUT", { postcode, label })),
  deletePlace: (kind: "home" | "work") => call(`/api/places/${kind}`, send("DELETE")),

  profiles: () => call<Profile[]>("/api/profiles"),
  setProfile: (slug: string, local_time: string, weekday: number, enabled: boolean) =>
    call(`/api/profiles/${slug}`, send("PUT", { local_time, weekday, enabled })),

  jobs: () => call<Job[]>("/api/jobs"),
  setJob: (id: string, j: { enabled: boolean; interval_minutes: number; active_from: string | null; active_to: string | null }) =>
    call(`/api/jobs/${id}`, send("PUT", j)),
  runJob: (id: string) => call(`/api/jobs/${id}/run`, send("POST")),
  runs: () => call<RunRow[]>("/api/jobs/runs?limit=30"),
};

export const gbp = (n: number | null | undefined) => (n == null ? "–" : `£${Math.round(n).toLocaleString("en-GB")}`);
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
