import "./workbench.css";
import { Button, Chip, Field, I, ICON_SIZE, Select } from "@/components";
import { CHART_TYPES, ChartResult, ChartSpec, ChartType, retype, setGroup, setX, toggleSeries } from "../lib";

/** Edits a ChartSpec from the columns the back-end described. Every control goes through the helpers in
 *  spec.ts, so the spec stays valid whichever combination the user picks. */
export default function SpecEditor({
  result,
  spec,
  onChange,
  onReset,
}: {
  result: ChartResult;
  spec: ChartSpec;
  onChange: (s: ChartSpec) => void;
  onReset: () => void;
}) {
  const { data, roles } = result;
  const cols = data.columns;
  const measures = cols.filter((c) => roles[c] === "measure");
  const dims = cols.filter((c) => roles[c] !== "measure");
  const none = { value: "", label: "None" };
  const colOptions = (list: string[]) => list.map((c) => ({ value: c, label: c }));
  const splitBy = dims.filter((c) => c !== spec.x);
  const isScatter = spec.type === "scatter";
  const cartesian = spec.type !== "table" && !isScatter;

  return (
    <div className="editor">
      <Field label="Chart type">
        <Select<ChartType> value={spec.type} onChange={(t) => onChange(retype(spec, t, result))} options={CHART_TYPES} />
      </Field>

      {spec.type !== "table" && (
        <Field label={isScatter ? "X axis (measure)" : spec.type === "pie" ? "Slices" : "X axis"}>
          <Select value={spec.x ?? ""} onChange={(f) => onChange(setX(spec, f, result))}
            options={colOptions(isScatter ? measures : cols)} />
        </Field>
      )}

      {cartesian && splitBy.length > 0 && (
        <Field label="Split by">
          <Select value={spec.group ?? ""} onChange={(g) => onChange(setGroup(spec, g || null))}
            options={[none, ...colOptions(splitBy)]} />
        </Field>
      )}

      {isScatter && (
        <>
          <Field label="Bubble size">
            <Select value={spec.size ?? ""} onChange={(f) => onChange({ ...spec, size: f || null })}
              options={[none, ...colOptions(measures.filter((c) => c !== spec.x && c !== spec.series[0]?.field))]} />
          </Field>
          <Field label="Label">
            <Select value={spec.label ?? ""} onChange={(f) => onChange({ ...spec, label: f || null })}
              options={[none, ...colOptions(dims)]} />
          </Field>
        </>
      )}

      {spec.type !== "table" && (
        <div className="editor-wide">
          <Field label={isScatter ? "Y axis" : spec.group ? "Value" : "Series"}>
            <div className="chips">
              {measures.filter((c) => c !== (isScatter ? spec.x : "")).map((c) => (
                <Chip key={c} on={spec.series.some((s) => s.field === c)}
                  onClick={() =>
                    onChange(isScatter ? { ...spec, series: toggleSeries({ ...spec, series: [] }, c, result).series } : toggleSeries(spec, c, result))
                  }>
                  {c}
                </Chip>
              ))}
            </div>
          </Field>
        </div>
      )}

      <div className="editor-wide" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {cartesian && (
          <label className="check">
            <input type="checkbox" checked={spec.stack} onChange={(e) => onChange({ ...spec, stack: e.target.checked })} />
            Stack
          </label>
        )}
        <span className="chart-note">
          {data.rows.length} rows{data.truncated ? " (truncated)" : ""} · config inferred from result columns
        </span>
        <span className="spacer" />
        <Button variant="ghost" size="sm" onClick={onReset}>
          <I.reset size={ICON_SIZE} /> Reset to inferred
        </Button>
      </div>
    </div>
  );
}
