import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Disclosure, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Spacer, Toolbar } from "@/components";
import { Job, lettings } from "../lib";
import "./jobs.css";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 0) return "in " + Math.abs(Math.round(s / 60)) + " min";
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
const until = (iso: string | null) => (iso ? ago(iso).replace(" ago", "") : "–");

const KEY_STATS = ["new", "seen", "touched", "repriced", "withdrawn", "fetched", "computed", "no_route", "looked_up",
  "properties_updated", "detail_pending", "commute_pending", "throttled", "blocked"];

function statsLine(detail: Record<string, unknown> | null): string {
  if (!detail) return "";
  return KEY_STATS.filter((k) => detail[k] !== undefined && detail[k] !== 0 && detail[k] !== "").map((k) => `${k.replace("_", " ")} ${detail[k]}`).join(" · ");
}

function StatusBadge({ job }: { job: Job }) {
  if (job.running) return <Badge>running</Badge>;
  const s = job.last_run?.status;
  if (!s) return <Badge neutral>not run yet</Badge>;
  return <Badge neutral={s === "ok"}>{s === "ok" ? "ok" : s}</Badge>;
}

function JobCard({ job }: { job: Job }) {
  const qc = useQueryClient();
  const [enabled, setEnabled] = useState(job.enabled);
  const [minutes, setMinutes] = useState(String(job.interval_minutes));
  const [from, setFrom] = useState(job.active_from ?? "");
  const [to, setTo] = useState(job.active_to ?? "");
  const dirty = enabled !== job.enabled || Number(minutes) !== job.interval_minutes || (from || null) !== job.active_from || (to || null) !== job.active_to;
  const refresh = () => qc.invalidateQueries({ queryKey: ["jobs"] });
  const save = useMutation({
    mutationFn: () => lettings.setJob(job.id, { enabled, interval_minutes: Math.max(1, Number(minutes) || job.interval_minutes), active_from: from || null, active_to: to || null }),
    onSuccess: refresh,
  });
  const run = useMutation({ mutationFn: () => lettings.runJob(job.id), onSuccess: () => setTimeout(refresh, 600) });
  const last = job.last_run;

  return (
    <section className="card job-card">
      <div className="card-head">
        <div>
          <div className="card-title">{job.title}</div>
          <div className="card-sub">{job.description}</div>
        </div>
        <Spacer />
        <StatusBadge job={job} />
      </div>
      <div className="card-body">
        <div className="job-grid">
          <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
          <Field label="Every (minutes)"><input className="input" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} /></Field>
          <Field label="Only from"><input className="input" type="time" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="Until"><input className="input" type="time" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          <div className="row-actions">
            <Button size="sm" variant="soft" onClick={() => save.mutate()} disabled={!dirty || save.isPending}><I.save size={ICON_SIZE} /> Save</Button>
            <Button size="sm" onClick={() => run.mutate()} disabled={job.running || run.isPending}><I.run size={ICON_SIZE} weight="fill" /> Run now</Button>
          </div>
        </div>
        <div className="job-facts muted small">
          <span>Last success: {ago(job.last_ok)}</span>
          <span>Next run: {job.enabled ? until(job.next_run) : "paused"}</span>
          {last && <span>Last run: {last.status} · {last.trigger} · +{last.rows_added} / ~{last.rows_updated}</span>}
        </div>
        {last && statsLine(last.detail) && <div className="small">{statsLine(last.detail)}</div>}
        {last?.error && <Note kind="error">{last.error}</Note>}
        {run.error && <Note kind="error">{run.error.message}</Note>}
      </div>
    </section>
  );
}

export default function JobsPanel() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: lettings.jobs, refetchInterval: 4000 });
  const status = useQuery({ queryKey: ["status"], queryFn: lettings.status, refetchInterval: 10_000 });
  const s = status.data;
  return (
    <Panel>
      <Toolbar>
        <Badge neutral>Runs inside this app</Badge>
        {s && <span className="muted small">{s.active_listings} listings · {s.detail_pending} details pending · {s.commute_pending} commutes pending</span>}
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => jobs.refetch()}><I.rerun size={ICON_SIZE} /> Refresh</Button>
      </Toolbar>
      <Scroll>
        {jobs.error && <Note kind="error">{jobs.error.message}</Note>}
        {jobs.data?.length === 0 && <Empty>No jobs registered.</Empty>}
        {jobs.data?.map((j) => <JobCard key={`${j.id}-${j.interval_minutes}-${j.enabled}-${j.active_from}-${j.active_to}`} job={j} />)}
        <Disclosure title="Run history" meta="latest 30">
          <RunHistory />
        </Disclosure>
      </Scroll>
    </Panel>
  );
}

function RunHistory() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: lettings.runs, refetchInterval: 8000 });
  if (!runs.data?.length) return <div className="muted">No runs yet.</div>;
  return (
    <table className="table">
      <thead><tr><th>Job</th><th>When</th><th>Trigger</th><th>Status</th><th className="num">Added</th><th className="num">Updated</th></tr></thead>
      <tbody>
        {runs.data.map((r) => (
          <tr key={r.id} title={r.error ?? ""}>
            <td>{r.job_id}</td><td>{ago(r.started_at)}</td><td>{r.trigger}</td><td>{r.status}</td>
            <td className="num">{r.rows_added}</td><td className="num">{r.rows_updated}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
