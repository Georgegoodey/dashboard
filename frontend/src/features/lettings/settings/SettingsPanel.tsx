import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button, Field, I, ICON_SIZE, Note, Panel, Scroll, Select } from "@/components";
import { lettings } from "../lib";
import AreasManager from "./AreasManager";
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
  return (
    <Panel>
      <Scroll>
        <Section title="Search filters" hint="Only homes inside these limits are fetched and shown. Loosening a limit brings hidden homes back.">
          <FiltersSection />
        </Section>

        <Section title="Search areas" hint="Postcode areas (outcodes) to search. Tick the ones to include; groups can be switched on or off together.">
          <AreasManager />
        </Section>
      </Scroll>
    </Panel>
  );
}
