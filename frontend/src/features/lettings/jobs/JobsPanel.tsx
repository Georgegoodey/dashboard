import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Disclosure, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Spacer, StatStrip, Toolbar } from "@/components";
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

const every = (minutes: number) => (minutes >= 60 && minutes % 60 === 0 ? `every ${minutes / 60} h` : `every ${minutes} min`);
const schedule = (j: Job) => `${every(j.interval_minutes)} · ${j.active_from && j.active_to ? `${j.active_from}–${j.active_to}` : "all day"}`;

const KEY_STATS = ["new", "seen", "touched", "repriced", "withdrawn", "fetched", "computed", "no_route", "looked_up",
  "properties_updated", "detail_pending", "commute_pending", "throttled", "blocked"];

function statsLine(detail: Record<string, unknown> | null): string {
  if (!detail) return "";
  return KEY_STATS.filter((k) => detail[k] !== undefined && detail[k] !== 0 && detail[k] !== "").map((k) => `${k.replace("_", " ")} ${detail[k]}`).join(" · ");
}

/** A coloured dot plus the word, so state reads at a glance down the column. */
function State({ job }: { job: Job }) {
  const s = job.last_run?.status;
  const [tone, text] = job.running ? ["run", "running"] : !job.enabled ? ["off", "paused"] : !s ? ["off", "not run yet"] : s === "ok" ? ["ok", "ok"] : ["bad", s];
  return <span className={`jstate jstate-${tone}`}><i />{text}</span>;
}

function JobRow({ job }: { job: Job }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
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
  const detail = last && statsLine(last.detail);
  const next = job.enabled ? until(job.next_run) : "paused";

  return (
    <div className={`jrow${open ? " jrow-open" : ""}`}>
      <div className="jrow-line">
        <button type="button" className="jrow-main" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span className="jname"><I.caret className="jcaret" size={12} weight="bold" />{job.title}</span>
          <State job={job} />
          <span className="jsched">{schedule(job)}</span>
          <span className="jlast">{ago(job.last_ok)}</span>
          <span className="jnext">{next}</span>
          <span className="jmeta">{every(job.interval_minutes)} · next {next}</span>
        </button>
        <Button size="sm" variant="soft" title="Run now" aria-label={`Run ${job.title} now`} onClick={() => run.mutate()} disabled={job.running || run.isPending}>
          <I.run size={ICON_SIZE} weight="fill" /><span className="jrun-label"> Run</span>
        </Button>
      </div>

      {open && (
        <div className="jdetail">
          <p className="jdesc">{job.description}</p>
          <dl className="jfacts">
            <div><dt>Last run</dt><dd>{last ? `${last.status} · ${last.trigger} · ${ago(last.started_at)} · +${last.rows_added} / ~${last.rows_updated}` : "never"}</dd></div>
            {detail && <div><dt>Result</dt><dd>{detail}</dd></div>}
          </dl>
          {last?.error && <Note kind="error">{last.error}</Note>}
          {run.error && <Note kind="error">{run.error.message}</Note>}
          <div className="jedit">
            <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
            <Field label="Every (minutes)"><input className="input" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} /></Field>
            <Field label="Only from"><input className="input" type="time" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="Until"><input className="input" type="time" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            <Button size="sm" variant="soft" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              <I.save size={ICON_SIZE} /> Save
            </Button>
          </div>
          {save.error && <Note kind="error">{save.error.message}</Note>}
        </div>
      )}
    </div>
  );
}

export default function JobsPanel() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: lettings.jobs, refetchInterval: 4000 });
  const status = useQuery({ queryKey: ["status"], queryFn: lettings.status, refetchInterval: 10_000 });
  const s = status.data;
  const running = jobs.data?.filter((j) => j.running).length ?? 0;
  return (
    <Panel>
      {s && (
        <StatStrip
          stats={[
            { label: "Listings", value: s.active_listings.toLocaleString("en-GB") },
            { label: "Details left", value: s.detail_pending.toLocaleString("en-GB"), muted: s.detail_pending === 0 },
            { label: "Commutes left", value: s.commute_pending.toLocaleString("en-GB"), muted: s.commute_pending === 0 },
          ]}
        />
      )}
      <Toolbar>
        {jobs.data && <span className="muted">{jobs.data.length} jobs{running ? ` · ${running} running` : ""}</span>}
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => jobs.refetch()}><I.rerun size={ICON_SIZE} /> Refresh</Button>
      </Toolbar>
      <Scroll>
        {jobs.error && <Note kind="error">{jobs.error.message}</Note>}
        {jobs.data?.length === 0 && <Empty>No jobs registered.</Empty>}
        {!!jobs.data?.length && (
          <div className="jobs-list">
            <div className="jrow-line jhead" aria-hidden>
              <div className="jrow-main"><span>Job</span><span>State</span><span>Schedule</span><span>Last success</span><span>Next run</span></div>
              <span className="jrun-gap" />
            </div>
            {jobs.data.map((j) => <JobRow key={`${j.id}-${j.interval_minutes}-${j.enabled}-${j.active_from}-${j.active_to}`} job={j} />)}
          </div>
        )}
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
    <div className="runs-wrap">
      <table className="table runs">
        <thead>
          <tr>
            <th>Job</th><th>When</th><th className="hide-narrow">Trigger</th><th>Status</th>
            <th className="num">Added</th><th className="num hide-narrow">Updated</th>
          </tr>
        </thead>
        <tbody>
          {runs.data.map((r) => (
            <tr key={r.id} title={r.error ?? ""}>
              <td>{r.job_id.replace(/_/g, " ")}</td><td>{ago(r.started_at)}</td><td className="hide-narrow">{r.trigger}</td><td>{r.status}</td>
              <td className="num">{r.rows_added}</td><td className="num hide-narrow">{r.rows_updated}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
