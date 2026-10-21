import { useMemo, useState } from "react";
import { Button, I, ICON_SIZE, Select } from "@/components";
import type { CommutePoint } from "../lib";
import { activePoints } from "./format";
import { useCommutePoints } from "./useCommutePoints";
import "./commute.css";

/** One limit: "everything must be within MAX minutes of POINT", where POINT is a commute point or every active one. */
export type CommuteRule = { key: number; point: string; max: string };

let nextKey = 1;

/** The rules being edited, the active points they can refer to, and the `POINT:MINUTES` query values they stand for. */
export function useCommuteRules() {
  const points = useCommutePoints();
  const [rules, setRules] = useState<CommuteRule[]>([]);
  const active = useMemo(() => activePoints(points.data), [points.data]);
  const params = useMemo(
    () => rules.flatMap((r) => {
      const max = Math.round(Number(r.max));
      if (r.max.trim() === "" || !Number.isFinite(max) || max <= 0) return [];
      if (r.point !== "all" && !active.some((p) => String(p.id) === r.point)) return [];   // a point that was switched off
      return [`${r.point}:${max}`];
    }),
    [rules, active],
  );
  return { rules, setRules, params, active };
}

export type CommuteRules = ReturnType<typeof useCommuteRules>;

/** Add as many commute limits as you like, each for one point or for all of them. */
export function CommuteFilter({ rules, setRules, active }: Pick<CommuteRules, "rules" | "setRules"> & { active: CommutePoint[] }) {
  const options = [{ value: "all", label: active.length > 1 ? "Every point" : "Any point" }, ...active.map((p) => ({ value: String(p.id), label: p.label }))];
  const change = (key: number, patch: Partial<CommuteRule>) => setRules(rules.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <div className="commute-filter">
      <span className="field-label">Commute limits</span>
      {active.length === 0 && <span className="muted small">Add a commute point in Settings first.</span>}
      {rules.map((r) => (
        <div key={r.key} className="commute-rule">
          <Select value={r.point} onChange={(point) => change(r.key, { point })} options={options} />
          <span className="muted small">within</span>
          <input className="input commute-max" inputMode="numeric" placeholder="min" aria-label="Maximum minutes"
            value={r.max} onChange={(e) => change(r.key, { max: e.target.value })} />
          <span className="muted small">min</span>
          <Button variant="ghost" size="sm" icon title="Remove limit" onClick={() => setRules(rules.filter((x) => x.key !== r.key))}>
            <I.close size={ICON_SIZE} />
          </Button>
        </div>
      ))}
      {active.length > 0 && (
        <Button variant="soft" size="sm" onClick={() => setRules([...rules, { key: nextKey++, point: "all", max: "" }])}>
          <I.add size={ICON_SIZE} /> Add limit
        </Button>
      )}
    </div>
  );
}
