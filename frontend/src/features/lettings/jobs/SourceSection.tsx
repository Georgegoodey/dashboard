import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Button, I, ICON_SIZE, StatStrip } from "@/components";
import type { Stat } from "@/components";
import { gbp, Job, lettings, SourceStats } from "../lib";
import { ago, groupState } from "./format";
import { JobRow, JobsHead, State } from "./JobRow";

const NAMES: Record<string, string> = { rightmove: "Rightmove", onthemarket: "OnTheMarket", openrent: "OpenRent", foxtons: "Foxtons", rentola: "Rentola" };
export const siteName = (source: string) => NAMES[source] ?? source.charAt(0).toUpperCase() + source.slice(1);

const n = (v: number) => v.toLocaleString("en-GB");

/** The figures under a listings site's header. */
function siteStats(s: SourceStats): Stat[] {
  const detailsDone = s.active > 0 ? 1 - s.detail_pending / s.active : undefined;
  return [
    { label: "Listings", value: n(s.active), hint: s.withdrawn ? `${n(s.withdrawn)} withdrawn` : undefined, muted: s.active === 0 },
    { label: "New 24 h", value: n(s.new_24h), hint: `${n(s.new_7d)} in 7 days`, muted: s.new_24h === 0 },
    { label: "Details left", value: n(s.detail_pending), hint: detailsDone === undefined ? undefined : `${Math.round(detailsDone * 100)}% done`, progress: detailsDone, muted: s.detail_pending === 0 },
    { label: "Areas scraped", value: `${s.areas_done}/${s.areas_total}`, hint: s.last_scraped ? ago(s.last_scraped) : "never", progress: s.areas_total ? s.areas_done / s.areas_total : undefined, muted: s.areas_done === 0 },
    { label: "Median rent", value: s.median_rent == null ? "–" : gbp(s.median_rent), hint: "per month", muted: s.median_rent == null },
  ];
}

/** One block of the Jobs panel: a header (name, state, run button), its own figures, then the jobs that belong to it. */
export function Section({ title, jobs, stats, runId, children }: {
  title: string; jobs: Job[]; stats: Stat[]; runId?: string; children?: ReactNode;
}) {
  const qc = useQueryClient();
  const run = useMutation({ mutationFn: () => lettings.runJob(runId as string), onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["jobs"] }), 600) });
  const [tone, text] = groupState(jobs);
  const searching = runId ? jobs.find((j) => j.id === runId) : undefined;
  return (
    <section className="jsection" aria-label={title}>
      <header className="jsection-head">
        <h3 className="jsection-title">{title}</h3>
        <State tone={tone} text={text} />
        <span className="jspacer" />
        {runId && (
          <Button size="sm" variant="soft" onClick={() => run.mutate()} disabled={!!searching?.running || run.isPending} aria-label={`Search ${title} now`}>
            <I.run size={ICON_SIZE} weight="fill" /> Search now
          </Button>
        )}
      </header>
      <StatStrip stats={stats} />
      {children}
      <div className="jobs-list">
        <JobsHead />
        {jobs.map((j) => <JobRow key={`${j.id}-${j.interval_minutes}-${j.enabled}-${j.active_from}-${j.active_to}`} job={j} />)}
      </div>
    </section>
  );
}

export function SourceSection({ source, stats, jobs }: { source: string; stats: SourceStats; jobs: Job[] }) {
  return <Section title={siteName(source)} jobs={jobs} stats={siteStats(stats)} runId={`scrape_${source}`} />;
}
