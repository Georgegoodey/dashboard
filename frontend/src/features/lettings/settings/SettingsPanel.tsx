import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Field, I, ICON_SIZE, Note, Panel, Scroll, Select, Spacer, Toolbar } from "@/components";
import { lettings, Place, Profile, WEEKDAYS } from "../lib";
import "./settings.css";

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card settings-card">
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {hint && <div className="card-sub">{hint}</div>}
        </div>
      </div>
      <div className="card-body">{children}</div>
    </section>
  );
}

function PlaceRow({ kind, label, place }: { kind: "home" | "work"; label: string; place?: Place }) {
  const qc = useQueryClient();
  const [postcode, setPostcode] = useState(place?.postcode ?? "");
  useEffect(() => setPostcode(place?.postcode ?? ""), [place?.postcode]);
  const save = useMutation({
    mutationFn: () => lettings.setPlace(kind, postcode),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["places"] }); qc.invalidateQueries({ queryKey: ["status"] }); qc.invalidateQueries({ queryKey: ["properties"] }); },
  });
  const remove = useMutation({
    mutationFn: () => lettings.deletePlace(kind),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["places"] }); qc.invalidateQueries({ queryKey: ["properties"] }); },
  });
  return (
    <div className="form-row">
      <Field label={label}>
        <input className="input" placeholder="Postcode, e.g. SW11 7FD" value={postcode} onChange={(e) => setPostcode(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && postcode.trim()) save.mutate(); }} />
      </Field>
      <div className="row-actions">
        <Button size="sm" onClick={() => save.mutate()} disabled={!postcode.trim() || save.isPending}>
          <I.save size={ICON_SIZE} /> Save
        </Button>
        {place && <Button variant="ghost" size="sm" icon title="Remove" onClick={() => remove.mutate()}><I.trash size={ICON_SIZE} /></Button>}
      </div>
      {save.error && <Note kind="error">{save.error.message}</Note>}
      {save.data && <div className="muted small">Saved{save.data.borough ? ` · ${save.data.borough}` : ""}. Commutes will be recomputed.</div>}
    </div>
  );
}

function ProfileRow({ p }: { p: Profile }) {
  const qc = useQueryClient();
  const [time, setTime] = useState(p.local_time);
  const [weekday, setWeekday] = useState(String(p.weekday));
  const [enabled, setEnabled] = useState(p.enabled);
  const dirty = time !== p.local_time || Number(weekday) !== p.weekday || enabled !== p.enabled;
  const save = useMutation({
    mutationFn: () => lettings.setProfile(p.slug, time, Number(weekday), enabled),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["profiles"] }); qc.invalidateQueries({ queryKey: ["properties"] }); qc.invalidateQueries({ queryKey: ["status"] }); },
  });
  const verb = p.anchor === "arrive_by" ? "Arrive by" : "Leave at";
  return (
    <div className="form-row profile-row">
      <div className="profile-label">
        <b>{p.label}</b>
        <div className="muted small">{p.direction === "to_place" ? "to" : "from"} {p.place_kind} · {verb.toLowerCase()}</div>
      </div>
      <Field label="Day"><Select value={weekday} onChange={setWeekday} options={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} /></Field>
      <Field label={verb}><input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> On</label>
      <div className="row-actions">
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}><I.save size={ICON_SIZE} /> Save</Button>
      </div>
      {save.error && <Note kind="error">{save.error.message}</Note>}
    </div>
  );
}

const BEDS = [
  { value: "", label: "No limit" },
  ...[0, 1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: n === 0 ? "Studio" : `${n} bedroom${n === 1 ? "" : "s"}` })),
];
const asNumber = (s: string): number | null => {
  const n = Number(s.replace(/[£,\s]/g, ""));
  return s.trim() === "" || Number.isNaN(n) ? null : n;
};

function FiltersSection() {
  const qc = useQueryClient();
  const current = useQuery({ queryKey: ["filters"], queryFn: lettings.filters });
  const [minB, setMinB] = useState("");
  const [maxB, setMaxB] = useState("");
  const [rent, setRent] = useState("");
  useEffect(() => {
    if (!current.data) return;
    setMinB(current.data.min_bedrooms == null ? "" : String(current.data.min_bedrooms));
    setMaxB(current.data.max_bedrooms == null ? "" : String(current.data.max_bedrooms));
    setRent(current.data.max_rent == null ? "" : String(current.data.max_rent));
  }, [current.data]);

  const save = useMutation({
    mutationFn: () => lettings.setFilters({ min_bedrooms: asNumber(minB), max_bedrooms: asNumber(maxB), max_rent: asNumber(rent) }),
    onSuccess: () => {
      for (const key of ["filters", "properties", "status"]) qc.invalidateQueries({ queryKey: [key] });
    },
  });
  const c = current.data;
  const dirty = !c || asNumber(minB) !== c.min_bedrooms || asNumber(maxB) !== c.max_bedrooms || asNumber(rent) !== c.max_rent;

  return (
    <div className="form-row">
      <Field label="Minimum bedrooms"><Select value={minB} onChange={setMinB} options={BEDS} /></Field>
      <Field label="Maximum bedrooms"><Select value={maxB} onChange={setMaxB} options={BEDS} /></Field>
      <Field label="Maximum rent (£ per month)">
        <input className="input" inputMode="numeric" placeholder="No limit" value={rent} onChange={(e) => setRent(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") save.mutate(); }} />
      </Field>
      <div className="row-actions">
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}><I.save size={ICON_SIZE} /> Save</Button>
      </div>
      {save.error && <Note kind="error">{save.error.message}</Note>}
      {save.data && (
        <div className="muted small">
          Saved. {save.data.hidden} stored home{save.data.hidden === 1 ? "" : "s"} hidden, {save.data.restored} restored.
          The next search run uses these limits.
        </div>
      )}
    </div>
  );
}

export default function SettingsPanel() {
  const qc = useQueryClient();
  const places = useQuery({ queryKey: ["places"], queryFn: lettings.places });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: lettings.profiles });
  const areas = useQuery({ queryKey: ["areas"], queryFn: lettings.areas });
  const health = useQuery({ queryKey: ["health"], queryFn: lettings.health });
  const [areaText, setAreaText] = useState("");

  const addAreas = useMutation({
    mutationFn: async (text: string) => {
      const codes = text.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
      const errors: string[] = [];
      for (const code of codes) {
        try { await lettings.addArea(code); } catch (e) { errors.push((e as Error).message); }
      }
      if (errors.length) throw new Error(errors.join("; "));
    },
    onSuccess: () => { setAreaText(""); qc.invalidateQueries({ queryKey: ["areas"] }); qc.invalidateQueries({ queryKey: ["status"] }); },
    onError: () => qc.invalidateQueries({ queryKey: ["areas"] }),
  });
  const toggle = useMutation({ mutationFn: (a: { id: number; enabled: boolean }) => lettings.setArea(a.id, a.enabled), onSuccess: () => qc.invalidateQueries({ queryKey: ["areas"] }) });
  const remove = useMutation({ mutationFn: (id: number) => lettings.deleteArea(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["areas"] }); qc.invalidateQueries({ queryKey: ["status"] }); } });

  const place = (kind: "home" | "work") => places.data?.find((p) => p.kind === kind);

  return (
    <Panel>
      <Toolbar>
        <Badge neutral>Everything here is stored in the database</Badge>
        <Spacer />
      </Toolbar>
      <Scroll>
        <Section title="Home and work" hint="Used for commute times and distances. A full UK postcode is enough.">
          <PlaceRow kind="work" label="Work" place={place("work")} />
          <PlaceRow kind="home" label="Home" place={place("home")} />
        </Section>

        <Section title="Commute times" hint="Which weekday and time to plan each journey for. Changing one recomputes its journeys.">
          {health.data && !("tfl_key_configured" in health.data && (health.data as { tfl_key_configured?: boolean }).tfl_key_configured) && (
            <Note>No TfL key set, so journeys are fetched at 1 a second. Add TFL_APP_KEY to .env (free from api-portal.tfl.gov.uk) for 5 a second.</Note>
          )}
          {profiles.data?.map((p) => <ProfileRow key={`${p.slug}-${p.local_time}-${p.weekday}-${p.enabled}`} p={p} />)}
        </Section>

        <Section title="Search filters" hint="Only homes inside these limits are fetched and shown. Loosening a limit brings hidden homes back.">
          <FiltersSection />
        </Section>

        <Section title="Search areas" hint="Postcode areas (outcodes) to search, e.g. SW11, SW18, TW9. Add as many as you like.">
          <div className="form-row">
            <Field label="Add outcodes (comma or space separated)">
              <input className="input" placeholder="SW11, SW12, SW18" value={areaText} onChange={(e) => setAreaText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && areaText.trim()) addAreas.mutate(areaText); }} />
            </Field>
            <div className="row-actions">
              <Button size="sm" onClick={() => addAreas.mutate(areaText)} disabled={!areaText.trim() || addAreas.isPending}>
                <I.add size={ICON_SIZE} /> Add
              </Button>
            </div>
            {addAreas.error && <Note kind="error">{addAreas.error.message}</Note>}
          </div>
          <div className="areas">
            {areas.data?.length === 0 && <div className="muted">No areas yet.</div>}
            {areas.data?.map((a) => (
              <div key={a.id} className={`area${a.enabled ? "" : " off"}`}>
                <label className="check">
                  <input type="checkbox" checked={a.enabled} onChange={(e) => toggle.mutate({ id: a.id, enabled: e.target.checked })} />
                  <b>{a.outcode}</b>
                </label>
                <span className="muted small">{a.properties} homes</span>
                <Button variant="ghost" size="sm" icon title="Remove area" onClick={() => remove.mutate(a.id)}><I.close size={14} /></Button>
              </div>
            ))}
          </div>
        </Section>
      </Scroll>
    </Panel>
  );
}
