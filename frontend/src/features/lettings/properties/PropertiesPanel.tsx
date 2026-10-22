import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Button, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Select, Spacer, StatStrip, Toolbar } from "@/components";
import { useDebounced } from "@/hooks";
import { CommuteFilter, describeJourney, minutesText, useCommuteLimits } from "../commute";
import { gbp, lettings, Property, PropertyDetail, PropertyFilters } from "../lib";
import { FilterBar, FilterToggle } from "../filters";
import "./properties.css";

const PAGE = 50;
const SORTS = [
  { value: "newest", label: "Newest" },
  { value: "rent", label: "Rent" },
  { value: "vs_median", label: "Rent vs median" },
  { value: "bedrooms", label: "Bedrooms" },
];
const BEDS = [{ value: "", label: "Any beds" }, ...[0, 1, 2, 3, 4].map((n) => ({ value: String(n), label: n === 0 ? "Studio+" : `${n}+ beds` }))];

const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));

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
        {commutes.length === 0 && <div className="muted">None yet. Add a commute point in Settings and wait for the commute job.</div>}
        {commutes.map((c) => (
          <div key={c.profile_id} className="commute">
            <b>{c.journey}</b>
            <span className="muted"> · {c.duration_min == null ? "no route" : `${c.duration_min} min`}
              {c.transfers ? ` · ${c.transfers} change${c.transfers === 1 ? "" : "s"}` : ""}
              {c.fare_pence != null ? ` · £${(c.fare_pence / 100).toFixed(2)}` : ""}
              {c.distance_km != null ? ` · ${c.distance_km} km away` : ""}</span>
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
  const commute = useCommuteLimits();
  const [sort, setSort] = useState("newest");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [showFilters, setShowFilters] = useState(false); // phones only: the filters fold away to leave room for the list

  const sorts = useMemo(
    () => [...SORTS, ...commute.active.map((p) => ({ value: `commute:${p.id}`, label: `Commute to ${p.label}` }))],
    [commute.active],
  );
  const sortKey = sorts.some((o) => o.value === sort) ? sort : "newest";      // a point that was switched off cannot be sorted by

  const filters: PropertyFilters = useDebounced({
    q: q || undefined, min_beds: num(minBeds), max_rent: num(maxRent), commute: commute.params,
    sort: sortKey, order, limit: PAGE, offset: page * PAGE,
  });
  const commuteKey = commute.params.join(",");
  useEffect(() => setPage(0), [q, minBeds, maxRent, commuteKey, sortKey, order]);

  const list = useQuery({
    queryKey: ["properties", filters], queryFn: () => lettings.properties(filters),
    placeholderData: keepPreviousData, refetchInterval: 30_000,
  });
  const health = useQuery({ queryKey: ["health"], queryFn: lettings.health, refetchInterval: 30_000 });

  const rows = list.data?.rows ?? [];
  const total = list.data?.total ?? 0;

  return (
    <Panel>
      <StatStrip
        stats={[
          { label: "Homes", value: total.toLocaleString("en-GB") },
        ]}
      />
      <Toolbar>
        <FilterToggle open={showFilters} onToggle={() => setShowFilters((v) => !v)} />
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => list.refetch()}>
          <I.rerun size={ICON_SIZE} /> Refresh
        </Button>
      </Toolbar>
      <FilterBar open={showFilters}>
        <Field label="Search">
          <input className="input" placeholder="address or headline" value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        <Field label="Bedrooms"><Select value={minBeds} onChange={setMinBeds} options={BEDS} /></Field>
        <Field label="Max rent £/month">
          <input className="input" inputMode="numeric" placeholder="any" value={maxRent} onChange={(e) => setMaxRent(e.target.value)} />
        </Field>
        <Field label="Sort">
          <Select value={sortKey} onChange={setSort} options={sorts} />
        </Field>
        <Field label="Order">
          <Select<"asc" | "desc"> value={order} onChange={setOrder} options={[{ value: "asc", label: "Low to high" }, { value: "desc", label: "High to low" }]} />
        </Field>
        <CommuteFilter limits={commute} />
      </FilterBar>
      {health.data && !health.data.database_ok && <Note kind="error">Database unavailable: {health.data.database_error || "is Docker running?"} Start it with: docker compose up -d db</Note>}
      {list.error && <Note kind="error">{list.error.message}</Note>}
      <Scroll>
        {rows.length === 0 && !list.isPending && <Empty>No homes match. {total === 0 ? "Run a search job in the Jobs panel to fetch some." : ""}</Empty>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="table props">
              <thead>
                <tr>
                  <th>Address</th><th className="num">Rent</th><th>Beds</th><th className="num hide-sm">vs median</th>
                  {commute.active.map((pt) => <th key={pt.id} className="num hide-sm" title={`Minutes to ${pt.label}`}>{pt.label}</th>)}
                  <th className="num hide-sm">Days</th><th className="hide-sm" />
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
                      <td className="num hide-sm"><VsMedian pct={p.rent_vs_median_pct} /></td>
                      {commute.active.map((pt) => (
                        <td key={pt.id} className="num hide-sm"
                          title={pt.journeys.filter((j) => j.enabled).map((j) => describeJourney(j, pt.label)).join("\n")}>
                          {minutesText(p.commutes, pt.id)}
                        </td>
                      ))}
                      <td className="num hide-sm">{p.days_on_market}</td>
                      <td className="hide-sm">{p.url && <a href={p.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} title="Open advert in a new tab" aria-label="Open advert in a new tab"><I.external size={ICON_SIZE} /></a>}</td>
                    </tr>
                    {open === p.id && <tr className="detail-row"><td colSpan={6 + commute.active.length}><Detail id={p.id} /></td></tr>}
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
