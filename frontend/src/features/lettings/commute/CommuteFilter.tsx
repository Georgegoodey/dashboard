import { useMemo, useState } from "react";
import { Button, I, ICON_SIZE, Select } from "@/components";
import { activePoints } from "./format";
import { useCommutePoints } from "./useCommutePoints";
import "./commute.css";

/** One limit: "within MAX minutes of POINT", where POINT is a commute point or every active one. */
type Rule = { key: number; point: string; max: string };

let nextKey = 1;

/** The limits being edited, the active points they can refer to, and the `POINT:MINUTES` query values they stand for. */
export function useCommuteLimits() {
  const points = useCommutePoints();
  const active = useMemo(() => activePoints(points.data), [points.data]);
  const [rules, setRules] = useState<Rule[]>([]);
  const params = useMemo(
    () => rules.flatMap((r) => {
      const max = Math.round(Number(r.max));
      if (r.max.trim() === "" || !Number.isFinite(max) || max <= 0) return [];
      if (r.point !== "all" && !active.some((p) => String(p.id) === r.point)) return [];   // a point that was switched off
      return [`${r.point}:${max}`];
    }),
    [rules, active],
  );
  return { active, rules, setRules, params };
}

export type CommuteLimits = ReturnType<typeof useCommuteLimits>;

/** A list of commute limits, one row each: pick a point (or all of them) and the most minutes you will travel. */
export function CommuteFilter({ limits }: { limits: CommuteLimits }) {
  const { active, rules, setRules } = limits;
  const options = [
    { value: "all", label: active.length > 1 ? "Every point" : "Any point" },
    ...active.map((p) => ({ value: String(p.id), label: p.label })),
  ];
  const change = (key: number, patch: Partial<Rule>) => setRules(rules.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <section className="commute-list" aria-label="Commute limits">
      <div className="commute-list-head">
        <span className="field-label">Commute limits</span>
        {active.length > 0 && (
          <Button variant="soft" size="sm" onClick={() => setRules([...rules, { key: nextKey++, point: "all", max: "" }])}>
            <I.add size={ICON_SIZE} /> Add limit
          </Button>
        )}
      </div>
      {active.length === 0 && <div className="commute-list-empty muted small">Add a commute point first (Settings, Commute Points).</div>}
      {active.length > 0 && rules.length === 0 && <div className="commute-list-empty muted small">No limits. Add one to filter by travel time.</div>}
      {rules.length > 0 && (
        <ul className="commute-rules">
          {rules.map((r) => (
            <li key={r.key} className="commute-rule">
              <Select value={r.point} onChange={(point) => change(r.key, { point })} options={options} />
              <span className="muted small">within</span>
              <input className="input commute-max" inputMode="numeric" placeholder="min" aria-label="Maximum minutes"
                value={r.max} onChange={(e) => change(r.key, { max: e.target.value })} />
              <span className="muted small">min</span>
              <Button variant="ghost" size="sm" icon title="Remove limit" onClick={() => setRules(rules.filter((x) => x.key !== r.key))}>
                <I.close size={ICON_SIZE} />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
