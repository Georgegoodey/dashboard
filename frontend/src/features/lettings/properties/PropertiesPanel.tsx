import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Select, Spacer, StatStrip, Toolbar } from "@/components";
import { useDebounced } from "@/hooks";
import { describeJourney, minutesText, useCommuteLimits } from "../commute";
import { FilterBar, FilterToggle, ListingFilters, useListingQuery } from "../filters";
import { gbp, lettings, Property, PropertyFilters } from "../lib";
import { keyTags } from "./keyInfo";
import { PropertyDialog } from "./PropertyDialog";
import "./properties.css";

const PAGE = 50;
const SORTS = [
  { value: "newest", label: "Newest" },
  { value: "rent", label: "Rent" },
  { value: "vs_median", label: "Rent vs median" },
  { value: "bedrooms", label: "Bedrooms" },
];

function VsMedian({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="muted">–</span>;
  return <span className={pct <= 0 ? "good" : "bad"}>{pct > 0 ? "+" : ""}{pct}%</span>;
}

export default function PropertiesPanel() {
  const [sort, setSort] = useState("newest");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Property | null>(null);
  const [showFilters, setShowFilters] = useState(false); // phones only: the filters fold away to leave room for the list
  const commute = useCommuteLimits();
  const { query, count } = useListingQuery();        // the filters, shared with the map and remembered

  const sorts = useMemo(
    () => [...SORTS, ...commute.active.map((p) => ({ value: `commute:${p.id}`, label: `Commute to ${p.label}` }))],
    [commute.active],
  );
  const sortKey = sorts.some((o) => o.value === sort) ? sort : "newest";      // a point that was switched off cannot be sorted by

  const filters: PropertyFilters = useDebounced({ ...query, sort: sortKey, order, limit: PAGE, offset: page * PAGE });
  const queryKey = JSON.stringify(query);
  useEffect(() => setPage(0), [queryKey, sortKey, order]);

  const list = useQuery({
    queryKey: ["properties", filters], queryFn: () => lettings.properties(filters),
    placeholderData: keepPreviousData, refetchInterval: 30_000,
  });
  const health = useQuery({ queryKey: ["health"], queryFn: lettings.health, refetchInterval: 30_000 });

  const rows = list.data?.rows ?? [];
  const total = list.data?.total ?? 0;

  return (
    <Panel>
      <StatStrip stats={[{ label: "Homes", value: total.toLocaleString("en-GB"), hint: count > 0 ? `${count} filter${count === 1 ? "" : "s"} on` : undefined }]} />
      <Toolbar>
        <FilterToggle open={showFilters} onToggle={() => setShowFilters((v) => !v)} />
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => list.refetch()}>
          <I.rerun size={ICON_SIZE} /> Refresh
        </Button>
      </Toolbar>
      <FilterBar open={showFilters}>
        <ListingFilters />
        <Field label="Sort">
          <Select value={sortKey} onChange={setSort} options={sorts} />
        </Field>
        <Field label="Order">
          <Select<"asc" | "desc"> value={order} onChange={setOrder} options={[{ value: "asc", label: "Low to high" }, { value: "desc", label: "High to low" }]} />
        </Field>
      </FilterBar>
      {health.data && !health.data.database_ok && <Note kind="error">Database unavailable: {health.data.database_error || "is Docker running?"} Start it with: docker compose up -d db</Note>}
      {list.error && <Note kind="error">{list.error.message}</Note>}
      <Scroll>
        {rows.length === 0 && !list.isPending && <Empty>No homes match. {total === 0 ? (count > 0 ? "Try clearing a filter." : "Run a search job in the Jobs panel to fetch some.") : ""}</Empty>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="table props">
              <thead>
                <tr>
                  <th>Address</th><th className="num">Rent</th><th>Beds</th><th className="num hide-sm">vs median</th>
                  {commute.active.map((pt) => <th key={pt.id} className="num hide-sm" title={`Minutes to ${pt.label}`}>{pt.label}</th>)}
                  <th className="num hide-sm">Days</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p: Property) => {
                  const tags = keyTags(p);
                  return (
                    <tr key={p.id} className={`clickable${selected?.id === p.id ? " open" : ""}`} tabIndex={0}
                      onClick={() => setSelected(p)} onKeyDown={(e) => { if (e.key === "Enter") setSelected(p); }}>
                      <td>
                        <div className="addr">{p.address}</div>
                        <div className="muted small">{[p.postcode ?? p.outcode, p.borough, p.property_type].filter(Boolean).join(" · ")}</div>
                        {tags.length > 0 && <div className="row-tags">{tags.map((t) => <span key={t} className="pd-tag">{t}</span>)}</div>}
                      </td>
                      <td className="num"><b>{gbp(p.rent_pcm)}</b>{p.price_changes > 0 && <span className="muted small"> ({p.price_changes}↕)</span>}</td>
                      <td>{p.bedrooms === 0 ? "Studio" : p.bedrooms ?? "–"}{p.bathrooms ? ` / ${p.bathrooms}` : ""}</td>
                      <td className="num hide-sm"><VsMedian pct={p.rent_vs_median_pct} /></td>
                      {commute.active.map((pt) => (
                        <td key={pt.id} className="num hide-sm"
                          title={pt.journeys.filter((j) => j.enabled).map((j) => describeJourney(j, pt.label)).join("\n")}>
                          {minutesText(p.commutes, pt.id)}
                        </td>
                      ))}
                      <td className="num hide-sm">{p.days_on_market}</td>
                    </tr>
                  );
                })}
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
      {selected && <PropertyDialog row={selected} onClose={() => setSelected(null)} />}
    </Panel>
  );
}
