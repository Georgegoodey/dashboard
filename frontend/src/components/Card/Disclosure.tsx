import type { ReactNode } from "react";
import { I } from "../icons";
import "./card.css";

/** A collapsible card (a <details> with the shared card frame). */
export function Disclosure({
  title,
  meta,
  open,
  actions,
  children,
}: {
  title: ReactNode;
  meta?: ReactNode;
  open?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <details className="card" open={open}>
      <summary>
        <I.caret className="caret" size={14} weight="bold" />
        <b>{title}</b>
        {meta && <span className="muted">{meta}</span>}
        {actions && <span style={{ marginLeft: "auto" }}>{actions}</span>}
      </summary>
      <div className="card-body">{children}</div>
    </details>
  );
}
