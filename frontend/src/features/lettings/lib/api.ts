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
  lat: number | null;
  lon: number | null;
  commutes: RouteSummary[];
  /** Read from the adverts: furnishing and what they mention. */
  furnish_type: Furnishing | null;
  is_shared: boolean;
  pets_allowed: boolean;
  bills_included: boolean;
  has_garden: boolean;
  has_parking: boolean;
  has_balcony: boolean;
};
/** "flexible" means the landlord will do either. */
export type Furnishing = "furnished" | "part_furnished" | "unfurnished" | "flexible";

/** One computed journey from a property to a commute point. A point has one or more (e.g. morning and evening). */
export type RouteSummary = {
  point_id: number; profile_id: number; direction: Direction; anchor: Anchor; local_time: string;
  duration_min: number | null; walk_min: number | null; transfers: number | null; fare_pence: number | null;
  distance_km: number | null;
};
export type Direction = "to_place" | "from_place";
export type Anchor = "arrive_by" | "depart_at";

export type PropertyFilters = {
  q?: string;
  min_rent?: number;
  max_rent?: number;
  min_beds?: number;
  max_beds?: number;
  /** "POINT_ID:MINUTES" or "all:MINUTES", one per limit; every limit must hold. */
  commute?: string[];
  borough?: string;
  /** Any of furnished, part_furnished, unfurnished (a home whose landlord is flexible matches all). */
  furnish?: string[];
  /** Features the home must mention: pets, bills, garden, parking, balcony. */
  has?: string[];
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type MapPoint = {
  id: number; lat: number; lon: number; address: string | null; url: string | null; rent_pcm: number | null;
  bedrooms: number | null; borough: string | null; rent_vs_median_pct: number | null; days_on_market: number;
  commutes: RouteSummary[]; furnish_type: Furnishing | null;
};

export type PropertyDetail = {
  property: Property;
  listings: {
    source: string; url: string; status: string; rent_pcm: number; deposit: number | null; furnished: string | null;
    let_type: string | null; min_term_months: number | null; available_from: string | null; agent_name: string | null;
    headline: string | null; description: string | null; key_features: string[] | null; first_seen: string; last_seen: string;
  }[];
  price_history: { observed_at: string; rent_pcm: number | null; status: string | null }[];
  commutes: (Omit<RouteSummary, "profile_id"> & {
    profile_id: number; point_label: string; journey: string; summary: string | null; departs: string | null; arrives: string | null;
  })[];
};

export type Status = {
  active_listings: number; properties: number; detail_pending: number; areas: number; commute_points: number; commute_pending: number; commute_total: number;
};
export type Area = { id: number; label: string; outcode: string; enabled: boolean; properties: number };
export type SearchFilters = { min_bedrooms: number | null; max_bedrooms: number | null; max_rent: number | null };
export type Journey = {
  id: number; point_id: number; direction: Direction; anchor: Anchor; local_time: string; weekday: number; enabled: boolean;
};
export type JourneyIn = Omit<Journey, "id" | "point_id">;
export type CommutePoint = {
  id: number; label: string; address: string | null; postcode: string; lat: number; lon: number; enabled: boolean;
  position: number; journeys: Journey[];
};
export type JobRun = {
  started_at: string; finished_at: string | null; status: string; trigger: string | null;
  rows_added: number; rows_updated: number; detail: Record<string, unknown> | null; error: string | null;
};
/** What merging the same home on several sites would do, from /api/dedupe. */
export type DedupePreview = {
  auto: boolean; merged_total: number;
  preview: {
    groups: number; would_absorb: number; candidate_pairs: number; ambiguous_skipped: number; different_street_skipped: number;
    rent_too_far_skipped: number; incomplete_groups_skipped: number; by_sources: Record<string, number>;
  };
  samples: { homes: { id: number; address: string | null; postcode: string | null; bedrooms: number | null; adverts: { source: string; rent_pcm: number | null; url: string }[] }[] }[];
};
/** Figures for one listings site, from /api/sources. */
export type SourceStats = {
  name: string; enabled: boolean; active: number; withdrawn: number; new_24h: number; new_7d: number; detail_pending: number;
  median_rent: number | null; areas_done: number; areas_total: number; last_scraped: string | null;
};
export type Job = {
  id: string; title: string; description: string; /** the listings site it belongs to, if any */ source: string | null; enabled: boolean; interval_minutes: number;
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

/** Query string for the properties endpoints; list values (the commute limits) repeat the parameter. */
function query(f: PropertyFilters): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) {
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else if (v !== undefined && v !== "" && v !== null) p.set(k, String(v));
  }
  return p;
}

export const lettings = {
  health: () => call<Health>("/health"),
  status: () => call<Status>("/api/status"),

  properties: (f: PropertyFilters) => call<{ total: number; rows: Property[] }>(`/api/properties?${query(f)}`),
  mapPoints: (f: PropertyFilters) => call<{ total: number; points: MapPoint[] }>(`/api/properties/map?${query(f)}`),
  property: (id: number) => call<PropertyDetail>(`/api/properties/${id}`),

  areas: () => call<Area[]>("/api/areas"),
  addArea: (outcode: string, label?: string) => call("/api/areas", send("POST", { outcode, label })),
  setArea: (id: number, enabled: boolean) => call(`/api/areas/${id}`, send("PUT", { enabled })),
  deleteArea: (id: number) => call(`/api/areas/${id}`, send("DELETE")),

  filters: () => call<SearchFilters>("/api/filters"),
  setFilters: (f: SearchFilters) =>
    call<SearchFilters & { hidden: number; restored: number }>("/api/filters", send("PUT", f)),

  commutePoints: () => call<CommutePoint[]>("/api/commute-points"),
  addCommutePoint: (p: { postcode: string; label?: string; am_pm: boolean; local_time: string; weekday: number }) =>
    call<{ id: number; postcode: string; borough: string | null }>("/api/commute-points", send("POST", p)),
  setCommutePoint: (id: number, p: { label: string; postcode?: string; enabled: boolean }) =>
    call(`/api/commute-points/${id}`, send("PUT", p)),
  deleteCommutePoint: (id: number) => call(`/api/commute-points/${id}`, send("DELETE")),
  addJourney: (pointId: number, j: JourneyIn) => call(`/api/commute-points/${pointId}/journeys`, send("POST", j)),
  setJourney: (id: number, j: JourneyIn) => call(`/api/journeys/${id}`, send("PUT", j)),
  deleteJourney: (id: number) => call(`/api/journeys/${id}`, send("DELETE")),

  jobs: () => call<Job[]>("/api/jobs"),
  sources: () => call<SourceStats[]>("/api/sources"),
  dedupe: () => call<DedupePreview>("/api/dedupe"),
  setDedupeAuto: (auto: boolean) => call<{ auto: boolean }>("/api/dedupe", send("PUT", { auto })),
  applyDedupe: () => call<{ groups: number; absorbed: number; listings_moved: number }>("/api/dedupe/apply", send("POST")),
  setJob: (id: string, j: { enabled: boolean; interval_minutes: number; active_from: string | null; active_to: string | null }) =>
    call(`/api/jobs/${id}`, send("PUT", j)),
  runJob: (id: string) => call(`/api/jobs/${id}/run`, send("POST")),
  runs: () => call<RunRow[]>("/api/jobs/runs?limit=30"),
};

export const gbp = (n: number | null | undefined) => (n == null ? "–" : `£${Math.round(n).toLocaleString("en-GB")}`);
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
