import type { ReactNode } from "react";
import "./stats.css";

export type Stat = {
  label: string;
  value: ReactNode;
  /** Small line under the number, e.g. what is left to do. */
  hint?: ReactNode;
  /** 0 to 1: draws a thin progress bar under the cell. */
  progress?: number;
  /** Dims the cell when there is nothing to report. */
  muted?: boolean;
};

/** A row of key figures. Replaces banner-style badges where a number deserves to stay on screen. */
export function StatStrip({ stats }: { stats: Stat[] }) {
  return (
    <div className="stat-strip" role="list">
      {stats.map((s) => (
        <div key={s.label} role="listitem" className={`stat${s.muted ? " stat-muted" : ""}`}>
          <div className="stat-value">{s.value}</div>
          <div className="stat-label">{s.label}</div>
          {s.hint && <div className="stat-hint">{s.hint}</div>}
          {s.progress !== undefined && (
            <div className="stat-bar" aria-hidden>
              <div className="stat-bar-fill" style={{ width: `${Math.round(Math.min(Math.max(s.progress, 0), 1) * 100)}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
