import type { ReactNode } from "react";
import "./badge.css";

export function Badge({ children, neutral }: { children: ReactNode; neutral?: boolean }) {
  return <span className={`badge${neutral ? " badge-neutral" : ""}`}>{children}</span>;
}
