import type { ReactNode } from "react";
import { Spacer } from "@/components";
import "./chart-card.css";

/** Titled card used for charts: same frame whichever renderer draws inside it. */
export function ChartCard({
  title,
  subtitle,
  badge,
  actions,
  footer,
  height,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  height?: number;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {subtitle && <div className="card-sub">{subtitle}</div>}
        </div>
        <Spacer />
        {actions}
        {badge}
      </div>
      <div className="chart-frame" style={height ? { height } : undefined}>
        {children}
      </div>
      {footer && <div className="card-foot">{footer}</div>}
    </section>
  );
}
