import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ConfirmButton, Empty, Field, I, ICON_SIZE, Note, Panel, Scroll, Select } from "@/components";
import { CommutePoint, Journey, JourneyIn, lettings, WEEKDAYS } from "../lib";
import { describeJourney } from "./format";
import { useCommutePoints } from "./useCommutePoints";

const DAYS = WEEKDAYS.map((d, i) => ({ value: String(i), label: d }));
const WAYS = [
  { value: "arrive_by", label: "Arrive by" },
  { value: "depart_at", label: "Leave at" },
] as const;
const DIRECTIONS = [
  { value: "to_place", label: "To point" },
  { value: "from_place", label: "From point" },
] as const;

/** Everything that depends on commute points: the lists, the map, the status strip and the journeys being planned. */
function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["commute-points", "properties", "map-points", "status", "property"]) qc.invalidateQueries({ queryKey: [key] });
  };
}

function JourneyRow({ point, j }: { point: CommutePoint; j: Journey }) {
  const refresh = useRefresh();
  const [draft, setDraft] = useState<JourneyIn>({ direction: j.direction, anchor: j.anchor, local_time: j.local_time, weekday: j.weekday, enabled: j.enabled });
  const dirty = (Object.keys(draft) as (keyof JourneyIn)[]).some((k) => draft[k] !== j[k]);
  const save = useMutation({ mutationFn: () => lettings.setJourney(j.id, draft), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => lettings.deleteJourney(j.id), onSuccess: refresh });
  const set = <K extends keyof JourneyIn>(k: K, v: JourneyIn[K]) => setDraft({ ...draft, [k]: v });
  return (
    <div className="journey-row">
      <Field label="Direction"><Select value={draft.direction} onChange={(v) => set("direction", v)} options={[...DIRECTIONS]} /></Field>
      <Field label="Timing"><Select value={draft.anchor} onChange={(v) => set("anchor", v)} options={[...WAYS]} /></Field>
      <Field label="Time"><input className="input" type="time" value={draft.local_time} onChange={(e) => set("local_time", e.target.value)} /></Field>
      <Field label="Day"><Select value={String(draft.weekday)} onChange={(v) => set("weekday", Number(v))} options={DAYS} /></Field>
      <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(e) => set("enabled", e.target.checked)} /> On</label>
      <div className="row-actions">
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending || !draft.local_time}><I.save size={ICON_SIZE} /> Save</Button>
        <Button variant="ghost" size="sm" icon title="Remove journey" onClick={() => remove.mutate()}><I.trash size={ICON_SIZE} /></Button>
      </div>
      <div className="muted small journey-text">{describeJourney(draft, point.label)}</div>
      {save.error && <Note kind="error">{save.error.message}</Note>}
    </div>
  );
}

function PointCard({ point }: { point: CommutePoint }) {
  const refresh = useRefresh();
  const [label, setLabel] = useState(point.label);
  const [postcode, setPostcode] = useState(point.postcode);
  const squash = (s: string) => s.toUpperCase().replace(/\s+/g, "");
  const moved = squash(postcode) !== squash(point.postcode);
  const dirty = label.trim() !== point.label || moved;
  const save = useMutation({
    mutationFn: () => lettings.setCommutePoint(point.id, { label, enabled: point.enabled, postcode: moved ? postcode : undefined }),
    onSuccess: refresh,
  });
  const toggle = useMutation({ mutationFn: (enabled: boolean) => lettings.setCommutePoint(point.id, { label: point.label, enabled }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => lettings.deleteCommutePoint(point.id), onSuccess: refresh });
  const addJourney = useMutation({
    mutationFn: () => lettings.addJourney(point.id, { direction: "to_place", anchor: "arrive_by", local_time: "09:00", weekday: 1, enabled: true }),
    onSuccess: refresh,
  });
  return (
    <div className={`point${point.enabled ? "" : " off"}`}>
      <div className="point-head">
        <Field label="Name"><input className="input" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label="Postcode">
          <input className="input" value={postcode} onChange={(e) => setPostcode(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && dirty) save.mutate(); }} />
        </Field>
        <label className="check" title="Switched off, it disappears from the lists and map and no journeys are fetched, but they are kept">
          <input type="checkbox" checked={point.enabled} onChange={(e) => toggle.mutate(e.target.checked)} /> Active
        </label>
        <div className="row-actions">
          <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || !label.trim() || save.isPending}><I.save size={ICON_SIZE} /> Save</Button>
          <ConfirmButton variant="ghost" size="sm" icon title="Delete this point and its journeys" confirmLabel="Click again to delete"
            onConfirm={() => remove.mutate()}><I.trash size={ICON_SIZE} /></ConfirmButton>
        </div>
        {(save.error || toggle.error) && <Note kind="error">{(save.error ?? toggle.error)?.message}</Note>}
      </div>
      <div className="point-journeys">
        {point.journeys.length === 0 && <div className="muted small journey-text">No journeys: nothing is planned for this point.</div>}
        {point.journeys.map((j) => (
          <JourneyRow key={`${j.id}-${j.direction}-${j.anchor}-${j.local_time}-${j.weekday}-${j.enabled}`} point={point} j={j} />
        ))}
        <Button variant="soft" size="sm" onClick={() => addJourney.mutate()} disabled={addJourney.isPending}><I.add size={ICON_SIZE} /> Add journey</Button>
      </div>
    </div>
  );
}

function NewPoint() {
  const refresh = useRefresh();
  const [label, setLabel] = useState("");
  const [postcode, setPostcode] = useState("");
  const [time, setTime] = useState("09:00");
  const [weekday, setWeekday] = useState("1");
  const [amPm, setAmPm] = useState(false);
  const add = useMutation({
    mutationFn: () => lettings.addCommutePoint({ postcode, label: label.trim() || undefined, am_pm: amPm, local_time: time, weekday: Number(weekday) }),
    onSuccess: () => { setLabel(""); setPostcode(""); refresh(); },
  });
  return (
    <div className="point-new">
      <div className="form-row">
        <Field label="Name"><input className="input" placeholder="Work, Gym, Parents" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label="Postcode">
          <input className="input" placeholder="e.g. EC2R 8AH" value={postcode} onChange={(e) => setPostcode(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && postcode.trim()) add.mutate(); }} />
        </Field>
        <Field label="Arrive by"><input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
        <Field label="Day"><Select value={weekday} onChange={setWeekday} options={DAYS} /></Field>
      </div>
      <div className="form-row">
        <label className="check">
          <input type="checkbox" checked={amPm} onChange={(e) => setAmPm(e.target.checked)} /> Also plan the journey back (an AM and PM pair, leaving at 18:00)
        </label>
        <div className="row-actions">
          <Button size="sm" onClick={() => add.mutate()} disabled={!postcode.trim() || !time || add.isPending}><I.add size={ICON_SIZE} /> Add commute point</Button>
        </div>
      </div>
      {add.error && <Note kind="error">{add.error.message}</Note>}
    </div>
  );
}

/** Any number of places to commute to. Each has one journey by default, or a morning and evening pair. */
export default function CommutePointsPanel() {
  const points = useCommutePoints();
  const health = useQuery({ queryKey: ["health"], queryFn: lettings.health });
  return (
    <Panel>
      <Scroll>
        <section className="card commute-card">
          <div className="card-head">
            <div>
              <div className="card-title">Commute points</div>
              <div className="card-sub">Places you travel to, as many as you like. Each gets a public-transport journey from every home; add a return journey for a morning and evening pair.</div>
            </div>
          </div>
          <div className="card-body">
            {health.data && !health.data.tfl_key_configured && (
              <Note>No TfL key set, so journeys are fetched at 1 a second. Add TFL_APP_KEY to .env (free from api-portal.tfl.gov.uk) for 5 a second.</Note>
            )}
            {points.error && <Note kind="error">{points.error.message}</Note>}
            {points.data?.length === 0 && <Empty>No commute points yet. Add one below and its journeys are planned for every home.</Empty>}
            {points.data?.map((p) => (
              <PointCard key={`${p.id}-${p.label}-${p.postcode}-${p.enabled}`} point={p} />
            ))}
            <NewPoint />
          </div>
        </section>
      </Scroll>
    </Panel>
  );
}
