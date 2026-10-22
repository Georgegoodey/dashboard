import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Disclosure, I, ICON_SIZE, Note } from "@/components";
import { gbp, Job, lettings } from "../lib";
import { Section } from "./SourceSection";

const n = (v: number) => v.toLocaleString("en-GB");

/** The same home on several sites: what merging would do, the switch for doing it automatically, and a button to do it now. */
export function DuplicatesSection({ jobs }: { jobs: Job[] }) {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["dedupe"], queryFn: lettings.dedupe, refetchInterval: 60_000 });
  const refresh = () => { for (const key of ["dedupe", "jobs", "sources", "status", "properties", "map-points"]) qc.invalidateQueries({ queryKey: [key] }); };
  const auto = useMutation({ mutationFn: (on: boolean) => lettings.setDedupeAuto(on), onSuccess: refresh });
  const merge = useMutation({ mutationFn: lettings.applyDedupe, onSuccess: refresh });
  const d = info.data;
  const p = d?.preview;

  const stats = [
    { label: "Would merge", value: p ? n(p.would_absorb) : "–", hint: p ? `${n(p.groups)} groups` : undefined, muted: !p || p.would_absorb === 0 },
    { label: "Ambiguous, skipped", value: p ? n(p.ambiguous_skipped) : "–", hint: "identical flats in one block", muted: !p || p.ambiguous_skipped === 0 },
    { label: "Skipped otherwise", value: p ? n(p.different_street_skipped + p.rent_too_far_skipped + p.incomplete_groups_skipped) : "–", hint: "street, rent or chain", muted: !p },
    { label: "Merged so far", value: d ? n(d.merged_total) : "–", hint: d?.auto ? "automatic merging on" : "automatic merging off", muted: !d || d.merged_total === 0 },
  ];

  return (
    <Section title="Duplicates" jobs={jobs} stats={stats} runId="dedupe_properties" runLabel="Check now">
      <div className="jdupes">
        <div className="jdupes-actions">
          <Button size="sm" onClick={() => { if (window.confirm(`Merge ${p?.would_absorb} duplicate homes into ${p?.groups} groups? Each merge is recorded and can be reversed by hand.`)) merge.mutate(); }}
            disabled={!p || p.groups === 0 || merge.isPending}>
            <I.save size={ICON_SIZE} /> {merge.isPending ? "Merging…" : p ? `Merge ${n(p.would_absorb)} now` : "Merge now"}
          </Button>
          <label className="check" title="The check runs every 30 minutes; with this on it merges what it finds">
            <input type="checkbox" checked={!!d?.auto} disabled={!d || auto.isPending} onChange={(e) => auto.mutate(e.target.checked)} /> Merge automatically
          </label>
        </div>
        <p className="muted small">
          Two homes are the same when they have the same bedrooms, are within 30 m, are within 2% on rent, and start with the same street name.
          Homes that match more than one home on another site are left alone.
        </p>
        {merge.data && <Note>Merged {n(merge.data.absorbed)} homes into {n(merge.data.groups)} groups ({n(merge.data.listings_moved)} adverts moved).</Note>}
        {(info.error || merge.error || auto.error) && <Note kind="error">{(info.error ?? merge.error ?? auto.error)?.message}</Note>}
        {p && Object.keys(p.by_sources).length > 0 && (
          <div className="muted small">{Object.entries(p.by_sources).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}: ${n(v)}`).join(" · ")}</div>
        )}
        {!!d?.samples.length && (
          <Disclosure title="Examples" meta={`${d.samples.length} of ${p ? n(p.groups) : "?"}`}>
            <ul className="jdupes-list">
              {d.samples.map((g, i) => (
                <li key={i}>
                  {g.homes.map((h) => (
                    <div key={h.id} className="jdupes-home">
                      <span className="jdupes-addr">{h.address}</span>
                      <span className="muted small">{h.bedrooms} bed · {h.adverts.map((a) => `${a.source} ${gbp(a.rent_pcm)}`).join(" · ")}</span>
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          </Disclosure>
        )}
      </div>
    </Section>
  );
}
