import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { Badge, Button, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Select, Spacer, Toolbar } from "@/components";
import { gbp, lettings, Property, PropertyDetail, PropertyFilters } from "../lib";
import "./properties.css";

const PAGE = 50;
const SORTS = [
  { value: "newest", label: "Newest" },
  { value: "rent", label: "Rent" },
  { value: "commute", label: "Morning commute" },
  { value: "vs_median", label: "Rent vs median" },
  { value: "distance_work", label: "Distance to work" },
  { value: "bedrooms", label: "Bedrooms" },
];
const BEDS = [{ value: "", label: "Any beds" }, ...[0, 1, 2, 3, 4].map((n) => ({ value: String(n), label: n === 0 ? "Studio+" : `${n}+ beds` }))];

const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const commuteText = (min: number | null, changes: number | null) =>
  min == null ? "–" : `${min} min${changes ? ` · ${changes} ch` : ""}`;

function VsMedian({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="muted">–</span>;
  return <span className={pct <= 0 ? "good" : "bad"}>{pct > 0 ? "+" : ""}{pct}%</span>;
}

function Detail({ id }: { id: number }) {
  const { data, isPending, error } = useQuery<PropertyDetail>({ queryKey: ["property", id], queryFn: () => lettings.property(id) });
  if (isPending) return <Empty>Loading…</Empty>;
  if (error) return <Note kind="error">{error.message}</Note>;
  const { listings, commutes, price_history } = data;
  const active = listings.find((l) => l.status === "active") ?? listings[0];
  return (
    <div className="prop-detail">
      <div>
        <div className="detail-h">Commutes</div>
        {commutes.length === 0 && <div className="muted">None yet. Set your work address in Settings and wait for the commute job.</div>}
        {commutes.map((c) => (
          <div key={c.slug} className="commute">
            <b>{c.label}</b> <span className="muted">· {c.duration_min == null ? "no route" : `${c.duration_min} min`}
              {c.fare_pence != null && c.slug === "work_am" ? ` · £${(c.fare_pence / 100).toFixed(2)}` : ""}</span>
            <div className="muted small">{c.summary}</div>
          </div>
        ))}
      </div>
      <div>
        <div className="detail-h">Advert</div>
        {active?.headline && <div>{active.headline}</div>}
        <div className="muted small">
          {[active?.furnished, active?.let_type, active?.min_term_months ? `${active.min_term_months} month minimum` : null,
            active?.deposit ? `deposit ${gbp(active.deposit)}` : null, active?.agent_name].filter(Boolean).join(" · ")}
        </div>
        {active?.key_features && active.key_features.length > 0 && (
          <ul className="features">{active.key_features.slice(0, 6).map((f) => <li key={f}>{f}</li>)}</ul>
        )}
        {listings.map((l) => (
          <div key={l.url} className="small">
            <a href={l.url} target="_blank" rel="noreferrer">{l.source}</a> · {gbp(l.rent_pcm)} pcm · {l.status}
          </div>
        ))}
      </div>
      <div>
        <div className="detail-h">Rent history</div>
        {price_history.map((h, i) => (
          <div key={i} className="small">
            {new Date(h.observed_at).toLocaleDateString("en-GB")} · {gbp(h.rent_pcm)} {h.status && h.status !== "active" ? `(${h.status})` : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PropertiesPanel() {
  const [q, setQ] = useState("");
  const [minBeds, setMinBeds] = useState("");
  const [maxRent, setMaxRent] = useState("");
  const [maxCommute, setMaxCommute] = useState("");
  const [sort, setSort] = useState("newest");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const filters: PropertyFilters = useDebounced({
    q: q || undefined, min_beds: num(minBeds), max_rent: num(maxRent), max_commute: num(maxCommute),
    sort, order, limit: PAGE, offset: page * PAGE,
  });
  useEffect(() => setPage(0), [q, minBeds, maxRent, maxCommute, sort, order]);

  const list = useQuery({
    queryKey: ["properties", filters], queryFn: () => lettings.properties(filters),
    placeholderData: keepPreviousData, refetchInterval: 30_000,
  });
  const status = useQuery({ queryKey: ["status"], queryFn: lettings.status, refetchInterval: 15_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: lettings.health, refetchInterval: 30_000 });

  const rows = list.data?.rows ?? [];
  const total = list.data?.total ?? 0;
  const s = status.data;

  return (
    <Panel>
      <Toolbar>
        <Badge>{total.toLocaleString()} homes</Badge>
        {s && s.detail_pending > 0 && <Badge neutral>{s.detail_pending} advert details pending</Badge>}
        {s && s.commute_pending > 0 && s.places > 0 && <Badge neutral>{s.commute_pending} commutes pending</Badge>}
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => { list.refetch(); status.refetch(); }}>
          <I.rerun size={ICON_SIZE} /> Refresh
        </Button>
      </Toolbar>
      <div className="filters">
        <Field label="Search">
          <input className="input" placeholder="address or headline" value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        <Field label="Bedrooms"><Select value={minBeds} onChange={setMinBeds} options={BEDS} /></Field>
        <Field label="Max rent £/month">
          <input className="input" inputMode="numeric" placeholder="any" value={maxRent} onChange={(e) => setMaxRent(e.target.value)} />
        </Field>
        <Field label="Max commute (min)">
          <input className="input" inputMode="numeric" placeholder="any" value={maxCommute} onChange={(e) => setMaxCommute(e.target.value)} />
        </Field>
        <Field label="Sort">
          <Select value={sort} onChange={setSort} options={SORTS} />
        </Field>
        <Field label="Order">
          <Select<"asc" | "desc"> value={order} onChange={setOrder} options={[{ value: "asc", label: "Low to high" }, { value: "desc", label: "High to low" }]} />
        </Field>
      </div>
      {health.data && !health.data.database_ok && <Note kind="error">Database unavailable: {health.data.database_error || "is Docker running?"} Start it with: docker compose up -d db</Note>}
      {list.error && <Note kind="error">{list.error.message}</Note>}
      {s && s.areas === 0 && <Note>No search areas yet. Add postcode areas in Settings, then run "Rightmove: search" in Jobs.</Note>}
      {s && s.areas > 0 && s.places === 0 && <Note>Add your work (and home) address in Settings to get commute times.</Note>}
      <Scroll>
        {rows.length === 0 && !list.isPending && <Empty>No homes match. {total === 0 ? "Run the Rightmove search job to fetch some." : ""}</Empty>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="table props">
              <thead>
                <tr>
                  <th>Address</th><th className="num">Rent</th><th>Beds</th><th className="num">vs median</th>
                  <th className="num">Work am</th><th className="num">Work pm</th><th className="num">Days</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p: Property) => (
                  <Fragment key={p.id}>
                    <tr className={`clickable${open === p.id ? " open" : ""}`} onClick={() => setOpen(open === p.id ? null : p.id)}>
                      <td>
                        <div className="addr">{p.address}</div>
                        <div className="muted small">{[p.postcode ?? p.outcode, p.borough, p.property_type].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td className="num"><b>{gbp(p.rent_pcm)}</b>{p.price_changes > 0 && <span className="muted small"> ({p.price_changes}↕)</span>}</td>
                      <td>{p.bedrooms ?? "–"}{p.bathrooms ? ` / ${p.bathrooms}` : ""}</td>
                      <td className="num"><VsMedian pct={p.rent_vs_median_pct} /></td>
                      <td className="num">{commuteText(p.work_am_min, p.work_am_transfers)}</td>
                      <td className="num">{commuteText(p.work_pm_min, p.work_pm_transfers)}</td>
                      <td className="num">{p.days_on_market}</td>
                      <td>{p.url && <a href={p.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} title="Open advert in a new tab" aria-label="Open advert in a new tab"><I.external size={ICON_SIZE} /></a>}</td>
                    </tr>
                    {open === p.id && <tr className="detail-row"><td colSpan={8}><Detail id={p.id} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Scroll>
      <div className="footer">
        <span className="muted">{total === 0 ? "" : `${page * PAGE + 1}–${Math.min((page + 1) * PAGE, total)} of ${total.toLocaleString()}`}</span>
        <Spacer />
        <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
        <Button variant="ghost" size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </Panel>
  );
}
