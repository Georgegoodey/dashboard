import type { Job } from "../lib";

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 0) return "in " + Math.abs(Math.round(s / 60)) + " min";
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
/** "42%" of `part` in `whole`, rounded down so it never reads 100% until it is, and never 0% while there is some. */
export function percent(part: number, whole: number): string {
  if (whole <= 0) return "–";
  const pct = (part / whole) * 100;
  return part > 0 && pct < 1 ? "<1%" : `${Math.floor(pct)}%`;
}
export const until = (iso: string | null) => (iso ? ago(iso).replace(" ago", "") : "–");

export const every = (minutes: number) => (minutes >= 60 && minutes % 60 === 0 ? `every ${minutes / 60} h` : `every ${minutes} min`);
export const schedule = (j: Job) => `${every(j.interval_minutes)} · ${j.active_from && j.active_to ? `${j.active_from}–${j.active_to}` : "all day"}`;

const KEY_STATS = ["new", "seen", "touched", "repriced", "withdrawn", "fetched", "computed", "no_route", "looked_up",
  "properties_updated", "detail_pending", "commute_pending", "throttled", "blocked", "note"];

export function statsLine(detail: Record<string, unknown> | null): string {
  if (!detail) return "";
  return KEY_STATS.filter((k) => detail[k] !== undefined && detail[k] !== 0 && detail[k] !== "").map((k) => `${k.replace("_", " ")} ${detail[k]}`).join(" · ");
}

/** The state of a job, or of a group of jobs (running beats a problem, a problem beats ok, everything paused is paused). */
export type Tone = "run" | "ok" | "bad" | "off";
export function jobState(job: Job): [Tone, string] {
  const s = job.last_run?.status;
  if (job.running) return ["run", "running"];
  if (!job.enabled) return ["off", "paused"];
  if (!s) return ["off", "not run yet"];
  return s === "ok" ? ["ok", "ok"] : ["bad", s];
}
export function groupState(jobs: Job[]): [Tone, string] {
  const states = jobs.map(jobState);
  const running = states.filter(([t]) => t === "run").length;
  if (running) return ["run", `${running} running`];
  const bad = states.find(([t]) => t === "bad");
  if (bad) return ["bad", bad[1]];
  if (states.every(([t]) => t === "off" && jobs.every((j) => !j.enabled))) return ["off", "paused"];
  return states.every(([t]) => t === "ok") ? ["ok", "ok"] : ["off", "waiting for first run"];
}
