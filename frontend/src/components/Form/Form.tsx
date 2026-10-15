import type { ReactNode } from "react";
import "./form.css";

/** Labelled form control. */
export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="field">
    <span className="field-label">{label}</span>
    {children}
  </label>
);

export function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select className="input select" value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Toggleable pill, used for multi-select lists such as chart series. */
export const Chip = ({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) => (
  <button type="button" className={`chip${on ? " chip-on" : ""}`} aria-pressed={on} onClick={onClick}>
    {children}
  </button>
);

/** Two-or-more option switch. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="segmented" role="group">
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
