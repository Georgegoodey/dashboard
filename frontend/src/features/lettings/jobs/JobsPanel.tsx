import { useQuery } from "@tanstack/react-query";
import { Button, Disclosure, Empty, I, ICON_SIZE, Note, Panel, Scroll, Spacer, StatStrip, Toolbar } from "@/components";
import { lettings } from "../lib";
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
  const other = all.filter((j) => !j.source);
  const newToday = sites.reduce((sum, x) => sum + x.new_24h, 0);
  const active = sites.filter((x) => x.enabled).length;

  return (
    <Panel>
      {s && (
        <StatStrip
          stats={[
            { label: "Listings", value: n(s.active_listings), hint: `${active} of ${sites.length} sites on` },
            { label: "New 24 h", value: n(newToday), muted: newToday === 0 },
            { label: "Details left", value: n(s.detail_pending), muted: s.detail_pending === 0 },
            { label: "Commutes left", value: n(s.commute_pending), muted: s.commute_pending === 0 },
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
        {other.length > 0 && (
          <Section
            title="Data processing"
            jobs={other}
            stats={[
              { label: "Commutes left", value: n(s?.commute_pending ?? 0), hint: "journeys to plan", muted: !s || s.commute_pending === 0 },
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
