import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Field, I, ICON_SIZE, Note } from "@/components";
import { Job, lettings } from "../lib";
import { ago, every, jobState, schedule, statsLine, Tone, until } from "./format";

/** A coloured dot plus the word, so state reads at a glance down the column. */
export function State({ tone, text }: { tone: Tone; text: string }) {
  return <span className={`jstate jstate-${tone}`}><i />{text}</span>;
}

export function JobRow({ job }: { job: Job }) {
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
  const [tone, text] = jobState(job);

  return (
    <div className={`jrow${open ? " jrow-open" : ""}`}>
      <div className="jrow-line">
        <button type="button" className="jrow-main" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span className="jname"><I.caret className="jcaret" size={12} weight="bold" />{job.title}</span>
          <State tone={tone} text={text} />
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

/** The column titles above a section's rows. */
export function JobsHead() {
  return (
    <div className="jrow-line jhead" aria-hidden>
      <div className="jrow-main"><span>Job</span><span>State</span><span>Schedule</span><span>Last success</span><span>Next run</span></div>
      <span className="jrun-gap" />
    </div>
  );
}
