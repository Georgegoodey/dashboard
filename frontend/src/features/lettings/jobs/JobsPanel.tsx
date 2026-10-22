import { useQuery } from "@tanstack/react-query";
import { Button, Disclosure, Empty, I, ICON_SIZE, Note, Panel, Scroll, Spacer, StatStrip, Toolbar } from "@/components";
import { lettings } from "../lib";
import { DuplicatesSection } from "./DuplicatesSection";
import { percent } from "./format";
import { RunHistory } from "./RunHistory";
import { Section, SourceSection } from "./SourceSection";
import "./jobs.css";

const n = (v: number) => v.toLocaleString("en-GB");

export default function JobsPanel() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: lettings.jobs, refetchInterval: 4000 });
  const sources = useQuery({ queryKey: ["sources"], queryFn: lettings.sources, refetchInterval: 10_000 });
  const status = useQuery({ queryKey: ["status"], queryFn: lettings.status, refetchInterval: 10_000 });
  const s = status.data;
  const all = jobs.data ?? [];
  const running = all.filter((j) => j.running).length;

  // a section per listings site that has jobs; whatever is left (borough lookups, commute journeys) goes in the last one
  const sites = (sources.data ?? []).filter((src) => all.some((j) => j.source === src.name));
  const dupes = all.filter((j) => j.id === "dedupe_properties");
  const other = all.filter((j) => !j.source && j.id !== "dedupe_properties");
  const newToday = sites.reduce((sum, x) => sum + x.new_24h, 0);

  return (
    <Panel>
      {s && (
        <StatStrip
          stats={[
            { label: "Active adverts", value: n(s.active_listings), hint: `${n(s.properties)} homes` },
            { label: "New 24 h", value: n(newToday), muted: newToday === 0 },
            {
              label: "Details done", value: percent(s.active_listings - s.detail_pending, s.active_listings),
              hint: s.detail_pending > 0 ? `${n(s.detail_pending)} left` : "complete",
              progress: s.active_listings > 0 ? 1 - s.detail_pending / s.active_listings : undefined, muted: s.detail_pending === 0,
            },
            {
              label: "Commutes done", value: percent(s.commute_total - s.commute_pending, s.commute_total),
              hint: s.commute_total === 0 ? "add a commute point" : s.commute_pending > 0 ? `${n(s.commute_pending)} left` : "complete",
              progress: s.commute_total > 0 ? 1 - s.commute_pending / s.commute_total : undefined, muted: s.commute_pending === 0,
            },
          ]}
        />
      )}
      <Toolbar>
        {jobs.data && <span className="muted">{all.length} jobs{running ? ` · ${running} running` : ""}</span>}
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => { jobs.refetch(); sources.refetch(); }}><I.rerun size={ICON_SIZE} /> Refresh</Button>
      </Toolbar>
      <Scroll>
        {(jobs.error || sources.error) && <Note kind="error">{(jobs.error ?? sources.error)?.message}</Note>}
        {jobs.data?.length === 0 && <Empty>No jobs registered.</Empty>}
        {sites.map((site) => <SourceSection key={site.name} source={site.name} stats={site} jobs={all.filter((j) => j.source === site.name)} />)}
        {dupes.length > 0 && <DuplicatesSection jobs={dupes} />}
        {other.length > 0 && (
          <Section
            title="Data processing"
            jobs={other}
            stats={[
              {
                label: "Commutes done", value: s ? percent(s.commute_total - s.commute_pending, s.commute_total) : "–",
                hint: s && s.commute_total > 0 ? (s.commute_pending > 0 ? `${n(s.commute_pending)} left` : "complete") : undefined,
                progress: s && s.commute_total > 0 ? 1 - s.commute_pending / s.commute_total : undefined,
                muted: !s || s.commute_pending === 0,
              },
              { label: "Commute points", value: n(s?.commute_points ?? 0), muted: !s || s.commute_points === 0 },
              { label: "Search areas", value: n(s?.areas ?? 0), muted: !s || s.areas === 0 },
            ]}
          />
        )}
        <Disclosure title="Run history" meta="latest 30">
          <RunHistory />
        </Disclosure>
      </Scroll>
    </Panel>
  );
}
