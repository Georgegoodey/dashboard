import type { ReactNode } from "react";
import { Button, I, ICON_SIZE } from "@/components";
import "./filters.css";

/** The row of filter fields under a panel toolbar. On phones it folds away until its toggle is pressed. */
export function FilterBar({ open, children }: { open: boolean; children: ReactNode }) {
  return <div className={`filters${open ? " filters-open" : ""}`}>{children}</div>;
}

/** Phones only: shows or hides the FilterBar. Hidden on wider screens, where the bar is always visible. */
export function FilterToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <Button variant="soft" size="sm" className="filters-toggle" aria-expanded={open} onClick={onToggle}>
      <I.customize size={ICON_SIZE} /> {open ? "Hide filters" : "Filters"}
    </Button>
  );
}
