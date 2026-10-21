import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { MapPin } from "@phosphor-icons/react";
import type { ExpressionSpecification, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import Map, { Layer, Marker, NavigationControl, Popup, Source } from "react-map-gl/maplibre";
import type { MapRef } from "react-map-gl/maplibre";
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { Button, Empty, Field, I, ICON_SIZE, Note, Panel, Segmented, Select, Spacer, Toolbar } from "@/components";
import { useDebounced } from "@/hooks";
import { CommuteFilter, describeJourney, minutesText, useCommuteLimits } from "../commute";
import { gbp, lettings, MapPoint, PropertyFilters } from "../lib";
import { FilterBar, FilterToggle } from "../filters";
import "./map.css";

// Vite must bundle the map's web worker itself; without this the map fails with "Worker failed to load".
setWorkerUrl(workerUrl);

/** Dark vector basemap from CARTO (OpenStreetMap data). Free to use without a key; attribution is drawn by the map. */
const BASE_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const LONDON = { longitude: -0.2, latitude: 51.45, zoom: 10.5 };

/** The dots are coloured by a value (rent, or rent against the borough median) or by the travel time to one commute point. */
type Mode = "value" | "commute";
type ValueKey = "rent_pcm" | "rent_vs_median_pct";
const VALUES: { value: ValueKey; label: string; fmt: (n: number) => string }[] = [
  { value: "rent_pcm", label: "Rent", fmt: (n) => gbp(n) },
  { value: "rent_vs_median_pct", label: "Rent vs borough median", fmt: (n) => `${n > 0 ? "+" : ""}${n.toFixed(0)}%` },
];
const LONGEST = "longest";
const MODES = [{ value: "value" as Mode, label: "Value" }, { value: "commute" as Mode, label: "Commute" }];

/** Minutes to a point: its longest journey, or one chosen journey. Null while that has not been planned. */
function commuteValue(p: MapPoint, pointId: number, journey: string): number | null {
  const mins = p.commutes
    .filter((c) => c.point_id === pointId && (journey === LONGEST || String(c.profile_id) === journey))
    .map((c) => c.duration_min)
    .filter((m): m is number => m != null);
  return mins.length ? Math.max(...mins) : null;
}
const BEDS = [{ value: "", label: "Any beds" }, ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n}+ beds` }))];

/** Low (good) to high (bad). Colour-blind safe enough on dark: teal, amber, red-orange. */
const RAMP = ["#2dd4bf", "#fbbf24", "#f43f5e"];
const NO_DATA = "#64748b";

const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));

function quantile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))))];
}

export default function MapPanel() {
  const mapRef = useRef<MapRef>(null);
  const fitted = useRef(false);
  const [mode, setMode] = useState<Mode>("value");
  const [valueKey, setValueKey] = useState<ValueKey>("rent_pcm");
  const [pointPick, setPointPick] = useState("");
  const [journeyPick, setJourneyPick] = useState(LONGEST);
  const [minBeds, setMinBeds] = useState("");
  const [maxRent, setMaxRent] = useState("");
  const commute = useCommuteLimits();
  const [showFilters, setShowFilters] = useState(false); // phones only: the filter bar folds away to leave room for the map
  const [picked, setPicked] = useState<MapPoint | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  const filters: PropertyFilters = useDebounced({ min_beds: num(minBeds), max_rent: num(maxRent), commute: commute.params });
  const points = useQuery({
    queryKey: ["map-points", filters], queryFn: () => lettings.mapPoints(filters),
    placeholderData: keepPreviousData, refetchInterval: 60_000,
  });
  // Travel-time colouring needs a point; a point that was switched off falls back to the first active one.
  const colourPoint = commute.active.find((p) => String(p.id) === pointPick) ?? commute.active[0];
  const journeys = (colourPoint?.journeys ?? []).filter((j) => j.enabled);
  const journey = journeys.some((j) => String(j.id) === journeyPick) ? journeyPick : LONGEST;
  const byTravel = mode === "commute" && colourPoint != null;
  const def = byTravel
    ? { label: `Travel time to ${colourPoint.label}`, fmt: (n: number) => `${Math.round(n)} min` }
    : VALUES.find((v) => v.value === valueKey) ?? VALUES[0];
  const colourId = byTravel ? colourPoint.id : null;
  const metricValue = (p: MapPoint): number | null =>
    colourId != null ? commuteValue(p, colourId, journey) : valueKey === "rent_pcm" ? p.rent_pcm : p.rent_vs_median_pct;

  // Colour stops come from the data (5th / 50th / 95th percentile) so a few outliers do not flatten the ramp.
  const { geojson, stops } = useMemo(() => {
    const pts = points.data?.points ?? [];
    const values = pts.map(metricValue).filter((v): v is number => v != null).sort((a, b) => a - b);
    const lo = values.length ? quantile(values, 0.05) : 0;
    const hi = values.length ? quantile(values, 0.95) : 1;
    const mid = values.length ? quantile(values, 0.5) : 0.5;
    return {
      stops: { lo, mid: Math.min(Math.max(mid, lo), hi), hi, any: values.length > 0 },
      geojson: {
        type: "FeatureCollection" as const,
        features: pts.map((p) => ({
          type: "Feature" as const, id: p.id, geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
          properties: { id: p.id, v: metricValue(p) },
        })),
      },
    };
  }, [points.data, valueKey, colourId, journey]); // metricValue is rebuilt from exactly these

  const color = useMemo<ExpressionSpecification>(() => {
    const { lo, mid, hi } = stops;
    const ramp: (number | string)[] = hi > lo
      ? [lo, RAMP[0], Math.min(Math.max(mid, lo + (hi - lo) * 0.01), hi - (hi - lo) * 0.01), RAMP[1], hi, RAMP[2]]
      : [lo, RAMP[1], lo + 1, RAMP[1]];
    return ["case", ["==", ["get", "v"], null], NO_DATA, ["interpolate", ["linear"], ["get", "v"], ...ramp]] as ExpressionSpecification;
  }, [stops]);

  // Fit to the data once, the first time it arrives.
  useEffect(() => {
    const pts = points.data?.points;
    if (fitted.current || !pts?.length || !mapRef.current) return;
    // fit the middle 96% of points, so one stray advert far away does not zoom the whole map out
    const lons = pts.map((p) => p.lon).sort((x, y) => x - y), lats = pts.map((p) => p.lat).sort((x, y) => x - y);
    mapRef.current.fitBounds([[quantile(lons, 0.02), quantile(lats, 0.02)], [quantile(lons, 0.98), quantile(lats, 0.98)]],
      { padding: 40, duration: 0, maxZoom: 13 });
    fitted.current = true;
  }, [points.data]);

  const byId = useMemo(() => new globalThis.Map((points.data?.points ?? []).map((p) => [p.id, p])), [points.data]);
  const onClick = (e: MapLayerMouseEvent) => {
    const id = e.features?.[0]?.properties?.id;
    setPicked(id != null ? byId.get(Number(id)) ?? null : null);
  };

  const total = points.data?.total ?? 0;

  return (
    <Panel>
      <Toolbar>
        <FilterToggle open={showFilters} onToggle={() => setShowFilters((v) => !v)} />
        <span className="muted">{total.toLocaleString("en-GB")} homes with a location</span>
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => points.refetch()}><I.rerun size={ICON_SIZE} /> Refresh</Button>
      </Toolbar>
      <FilterBar open={showFilters}>
        <Field label="Colour by"><Segmented value={mode} onChange={setMode} options={MODES} /></Field>
        {mode === "value" || commute.active.length === 0 ? (
          <Field label="Value"><Select value={valueKey} onChange={setValueKey} options={VALUES} /></Field>
        ) : (
          <>
            <Field label="Travel time to">
              <Select value={String(colourPoint?.id ?? "")} onChange={setPointPick} options={commute.active.map((p) => ({ value: String(p.id), label: p.label }))} />
            </Field>
            {journeys.length > 1 && (
              <Field label="Journey">
                <Select value={journey} onChange={setJourneyPick}
                  options={[{ value: LONGEST, label: "Longest" }, ...journeys.map((j) => ({ value: String(j.id), label: describeJourney(j, colourPoint!.label).replace(/ on \w+$/, "") }))]} />
              </Field>
            )}
          </>
        )}
        <Field label="Bedrooms"><Select value={minBeds} onChange={setMinBeds} options={BEDS} /></Field>
        <Field label="Max rent £/month">
          <input className="input" inputMode="numeric" placeholder="any" value={maxRent} onChange={(e) => setMaxRent(e.target.value)} />
        </Field>
        <CommuteFilter limits={commute} />
      </FilterBar>
      {points.error && <Note kind="error">{points.error.message}</Note>}
      {mapError && <Note kind="error">Could not load the map tiles ({mapError}). Check your internet connection.</Note>}
      <div className="map-wrap">
        {points.data && total === 0 && <div className="map-empty"><Empty>No homes with a location match.</Empty></div>}
        <Map
          ref={mapRef}
          initialViewState={LONDON}
          mapStyle={BASE_STYLE as unknown as StyleSpecification}
          style={{ width: "100%", height: "100%" }}
          interactiveLayerIds={["homes"]}
          cursor="auto"
          onClick={onClick}
          onError={(e) => setMapError(e.error?.message ?? "error")}
          onLoad={() => setMapError(null)}
        >
          <NavigationControl position="top-right" showCompass={false} />
          <Source id="homes" type="geojson" data={geojson}>
            <Layer
              id="homes" type="circle"
              paint={{
                "circle-color": color,
                "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 6, 16, 10],
                "circle-opacity": 0.85, "circle-stroke-width": 1, "circle-stroke-color": "#0b1220",
              }}
            />
          </Source>
          {commute.active.map((pt) => (
            <Marker key={pt.id} longitude={pt.lon} latitude={pt.lat} anchor="center">
              <div className="map-pin work" title={`${pt.label}: ${pt.postcode}`}><MapPin size={16} weight="fill" /></div>
            </Marker>
          ))}
          {picked && (
            <Popup longitude={picked.lon} latitude={picked.lat} anchor="bottom" offset={10} closeOnClick={false} onClose={() => setPicked(null)} maxWidth="260px">
              <div className="map-popup">
                <b>{picked.address}</b>
                <div className="muted small">{[picked.borough, picked.bedrooms != null ? `${picked.bedrooms} bed` : null].filter(Boolean).join(" · ")}</div>
                <div><b>{gbp(picked.rent_pcm)}</b> pcm</div>
                {commute.active.map((pt) => (
                  <div key={pt.id} className="small">{pt.label} {minutesText(picked.commutes, pt.id)}</div>
                ))}
                {picked.rent_vs_median_pct != null && <div className="small">{picked.rent_vs_median_pct > 0 ? "+" : ""}{picked.rent_vs_median_pct}% vs borough median</div>}
                {picked.url && (
                  <a href={picked.url} target="_blank" rel="noopener noreferrer" aria-label="Open advert in a new tab">
                    Open advert <I.external size={ICON_SIZE} />
                  </a>
                )}
              </div>
            </Popup>
          )}
        </Map>
        <div className="map-legend" aria-label={`Colour scale: ${def.label}`}>
          <div className="legend-title">{def.label}</div>
          {stops.any ? (
            <>
              <div className="legend-bar" style={{ background: `linear-gradient(90deg, ${RAMP.join(", ")})` }} />
              <div className="legend-ends"><span>{def.fmt(stops.lo)}</span><span>{def.fmt(stops.hi)}</span></div>
            </>
          ) : <div className="muted small">No data for this measure yet</div>}
          <div className="legend-nodata"><span className="dot" /> no value</div>
        </div>
      </div>
    </Panel>
  );
}
