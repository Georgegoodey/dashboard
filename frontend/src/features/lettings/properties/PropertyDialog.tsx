import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Empty, I, ICON_SIZE, Modal, Note, Segmented, StatStrip } from "@/components";
import type { Stat } from "@/components";
import { activePoints, minutesText, useCommutePoints } from "../commute";
import { gbp, lettings, Property, PropertyDetail } from "../lib";
import { clock, FURNISH_LABEL, keyTags, steps } from "./keyInfo";

type Tab = "details" | "commutes";
const date = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-GB") : "–");
const pounds = (pence: number | null) => (pence == null ? null : `£${(pence / 100).toFixed(2)}`);

function Commutes({ detail }: { detail: PropertyDetail }) {
  const byPoint = useMemo(() => {
    const groups = new Map<number, PropertyDetail["commutes"]>();
    for (const c of detail.commutes) groups.set(c.point_id, [...(groups.get(c.point_id) ?? []), c]);
    return [...groups.values()];
  }, [detail.commutes]);
  if (byPoint.length === 0) return <Empty>No journeys planned yet. Add a commute point in Settings and wait for the commute job.</Empty>;
  return (
    <div className="pd-commutes">
      {byPoint.map((journeys) => (
        <section key={journeys[0].point_id} className="pd-point">
          <h3 className="pd-h">{journeys[0].point_label}{journeys[0].distance_km != null && <span className="muted small"> · {journeys[0].distance_km} km away</span>}</h3>
          {journeys.map((c) => {
            const leave = clock(c.departs), arrive = clock(c.arrives);
            return (
              <article key={c.profile_id} className="pd-journey">
                <div className="pd-journey-top">
                  <b className="pd-journey-time">{c.duration_min == null ? "No route" : `${c.duration_min} min`}</b>
                  <span className="muted">{c.journey}</span>
                </div>
                <div className="muted small">
                  {[leave && arrive ? `Leave ${leave}, arrive ${arrive}` : null,
                    c.walk_min != null ? `${c.walk_min} min walking` : null,
                    c.transfers != null ? `${c.transfers} change${c.transfers === 1 ? "" : "s"}` : null,
                    pounds(c.fare_pence) ? `${pounds(c.fare_pence)} fare` : null].filter(Boolean).join(" · ")}
                </div>
                {steps(c.summary).length > 0 && (
                  <ol className="pd-steps">{steps(c.summary).map((s, i) => <li key={i}>{s}</li>)}</ol>
                )}
              </article>
            );
          })}
        </section>
      ))}
    </div>
  );
}

function Details({ detail, row }: { detail: PropertyDetail; row: Property }) {
  const { listings, price_history } = detail;
  const live = listings.filter((l) => l.status === "active");
  const best = live[0] ?? listings[0];
  const describe = listings.find((l) => l.description);
  const [more, setMore] = useState(false);
  const features = [...new Set(listings.flatMap((l) => l.key_features ?? []))];
  const deposit = Math.max(0, ...live.map((l) => Number(l.deposit ?? 0)));
  const term = live.map((l) => l.min_term_months).find(Boolean);
  const facts: [string, string | null][] = [
    ["Furnishing", row.furnish_type ? FURNISH_LABEL[row.furnish_type] : null],
    ["Deposit", deposit ? gbp(deposit) : null],
    ["Available from", best?.available_from ? date(best.available_from) : null],
    ["Let type", best?.let_type ?? null],
    ["Minimum term", term ? `${term} months` : null],
    ["Property type", row.property_type],
    ["Area", [row.postcode ?? row.outcode, row.borough].filter(Boolean).join(" · ") || null],
    ["On the market", `${row.days_on_market} day${row.days_on_market === 1 ? "" : "s"}`],
  ];
  return (
    <div className="pd-details">
      <dl className="pd-facts">
        {facts.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>
      {features.length > 0 && <ul className="pd-features">{features.slice(0, 12).map((f) => <li key={f}>{f}</li>)}</ul>}
      {describe?.description && (
        <div>
          <h3 className="pd-h">Description</h3>
          <p className={`pd-desc${more ? "" : " pd-desc-clamp"}`}>{describe.description}</p>
          {describe.description.length > 360 && <button type="button" className="link-button" onClick={() => setMore((v) => !v)}>{more ? "Show less" : "Show all"}</button>}
        </div>
      )}
      <div>
        <h3 className="pd-h">Listed on</h3>
        {listings.map((l) => (
          <div key={l.url} className="pd-listing">
            <a href={l.url} target="_blank" rel="noreferrer">{l.source} <I.external size={12} /></a>
            <span>{gbp(l.rent_pcm)} pcm</span>
            <span className="muted">{l.status}{l.agent_name ? ` · ${l.agent_name}` : ""}</span>
          </div>
        ))}
      </div>
      {price_history.length > 1 && (
        <div>
          <h3 className="pd-h">Rent history</h3>
          {price_history.map((h, i) => (
            <div key={i} className="small">{date(h.observed_at)} · {gbp(h.rent_pcm)}{h.status && h.status !== "active" ? ` (${h.status})` : ""}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * A home in a dialog: price, commute times and the link to the advert first, then the details, with the journey directions on
 * their own tab. Opens at once from the row's own figures; the rest fills in when the detail arrives.
 */
export function PropertyDialog({ row, onClose }: { row: Property; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("details");
  const points = activePoints(useCommutePoints().data);
  const { data, isPending, error } = useQuery<PropertyDetail>({ queryKey: ["property", row.id], queryFn: () => lettings.property(row.id) });
  const tags = keyTags(row);

  const stats: Stat[] = [
    { label: "Rent", value: `${gbp(row.rent_pcm)} pcm`, hint: row.rent_vs_median_pct == null ? undefined : `${row.rent_vs_median_pct > 0 ? "+" : ""}${row.rent_vs_median_pct}% vs median` },
    ...points.map((p): Stat => ({ label: p.label, value: minutesText(row.commutes, p.id), hint: "commute" })),
    { label: "Beds · baths", value: `${row.bedrooms === 0 ? "Studio" : row.bedrooms ?? "–"}${row.bathrooms ? ` · ${row.bathrooms}` : ""}` },
  ];

  return (
    <Modal
      onClose={onClose}
      title={row.address ?? "Home"}
      subtitle={[row.postcode ?? row.outcode, row.borough, row.property_type].filter(Boolean).join(" · ")}
      actions={row.url && (
        <a className="btn btn-primary btn-sm pd-open" href={row.url} target="_blank" rel="noopener noreferrer">Open advert <I.external size={ICON_SIZE} /></a>
      )}
    >
      <div className="pd-key"><StatStrip stats={stats} /></div>
      {tags.length > 0 && <div className="pd-tags">{tags.map((t) => <span key={t} className="pd-tag">{t}</span>)}</div>}
      <div className="pd-tabs">
        <Segmented<Tab> value={tab} onChange={setTab} options={[
          { value: "details", label: "Details" },
          { value: "commutes", label: `Commutes${data ? ` (${data.commutes.length})` : ""}` },
        ]} />
      </div>
      <div className="pd-pane">
        {isPending && <Empty>Loading…</Empty>}
        {error && <Note kind="error">{error.message}</Note>}
        {data && (tab === "details" ? <Details detail={data} row={row} /> : <Commutes detail={data} />)}
      </div>
    </Modal>
  );
}
