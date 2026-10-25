import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { I, ICON_SIZE } from "../icons";
import "./modal.css";

/**
 * A dialog drawn over the page (in a portal, so no panel clips it). Escape or a click outside closes it, focus moves into it
 * and goes back to what had it, and the page behind does not scroll. Phones get it full screen.
 */
export function Modal({ onClose, title, subtitle, actions, children }: {
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Buttons or links in the header, next to the close button. */
  actions?: ReactNode;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const scroll = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); } };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = scroll;
      before?.focus?.();
    };
  }, []);

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} tabIndex={-1} ref={panel}>
        <header className="modal-head">
          <div className="modal-titles">
            <h2 className="modal-title">{title}</h2>
            {subtitle && <div className="modal-sub muted small">{subtitle}</div>}
          </div>
          {actions}
          <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label="Close" title="Close" onClick={onClose}>
            <I.close size={ICON_SIZE} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
