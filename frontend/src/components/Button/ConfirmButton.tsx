import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "./Button";

/**
 * A button that asks before it acts, without a browser dialog: the first click changes its text to `confirmLabel`, a second
 * click within a few seconds does it. Leaving the button, pressing Escape or waiting puts it back.
 */
export function ConfirmButton({ onConfirm, children, confirmLabel = "Click again to confirm", variant = "primary", size = "md", icon,
  disabled, title, className, seconds = 4 }: {
  onConfirm: () => void;
  children: ReactNode;
  confirmLabel?: ReactNode;
  variant?: "primary" | "soft" | "ghost";
  size?: "md" | "sm";
  icon?: boolean;
  disabled?: boolean;
  title?: string;
  className?: string;
  seconds?: number;
}) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const disarm = () => { window.clearTimeout(timer.current); setArmed(false); };
  return (
    <Button
      variant={armed ? "primary" : variant} size={size} icon={icon && !armed} disabled={disabled} title={armed ? undefined : title}
      className={`${className ?? ""}${armed ? " btn-confirm" : ""}`} aria-live="polite"
      onClick={() => {
        if (armed) { disarm(); onConfirm(); return; }
        setArmed(true);
        timer.current = window.setTimeout(() => setArmed(false), seconds * 1000);
      }}
      onBlur={disarm}
      onKeyDown={(e) => { if (e.key === "Escape") disarm(); }}
    >
      {armed ? confirmLabel : children}
    </Button>
  );
}
