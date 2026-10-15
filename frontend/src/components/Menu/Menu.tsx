import { KeyboardEvent, useCallback, useRef, useState } from "react";
import { useDismiss } from "@/hooks";
import { I, ICON_SIZE } from "../icons";
import type { Icon } from "../icons";
import "./menu.css";

export type MenuEntry =
  | { type: "item"; label: string; onSelect: () => void; icon?: Icon; checked?: boolean; disabled?: boolean }
  | { type: "heading"; label: string }
  | { type: "separator" };

const ITEMS = '[role^="menuitem"]:not(:disabled)';

/** A dropdown menu: click (or ArrowDown) opens it, arrows move, Enter selects, Escape or an outside click closes.
 *  Items with `checked` behave as radio items (the checked one shows a tick). */
export function Menu({
  label,
  icon: Icon,
  entries,
  align = "start",
}: {
  label: string;
  icon?: Icon;
  entries: MenuEntry[];
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(root, open, close);

  const items = () => Array.from(list.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
  const focusAt = (i: number) => {
    const all = items();
    all[(i + all.length) % all.length]?.focus();
  };
  const openAndFocus = (last = false) => {
    setOpen(true);
    // wait for the list to mount
    requestAnimationFrame(() => focusAt(last ? -1 : 0));
  };

  const onTriggerKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      openAndFocus(e.key === "ArrowUp");
    }
  };
  const onListKey = (e: KeyboardEvent) => {
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") focusAt(at + 1);
    else if (e.key === "ArrowUp") focusAt(at - 1);
    else if (e.key === "Home") focusAt(0);
    else if (e.key === "End") focusAt(-1);
    else if (e.key === "Escape" || e.key === "Tab") {
      close();
      if (e.key === "Escape") trigger.current?.focus();
      return;
    } else return;
    e.preventDefault();
  };

  return (
    <div className="menu" ref={root}>
      <button
        ref={trigger}
        type="button"
        className={`menu-trigger${open ? " open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={onTriggerKey}
      >
        {Icon && <Icon size={ICON_SIZE} />}
        {label}
        <I.caretDown size={12} weight="bold" />
      </button>
      {open && (
        <div className={`menu-list menu-${align}`} role="menu" aria-label={label} ref={list} onKeyDown={onListKey}>
          {entries.map((e, i) => {
            if (e.type === "separator") return <div key={i} className="menu-sep" role="separator" />;
            if (e.type === "heading") return <div key={i} className="menu-heading">{e.label}</div>;
            const Lead = e.icon;
            const radio = e.checked !== undefined;
            return (
              <button
                key={i}
                type="button"
                className="menu-item"
                role={radio ? "menuitemradio" : "menuitem"}
                aria-checked={radio ? e.checked : undefined}
                disabled={e.disabled}
                onClick={() => {
                  close();
                  trigger.current?.focus();
                  e.onSelect();
                }}
              >
                <span className="menu-lead">
                  {radio ? e.checked && <I.check size={14} weight="bold" /> : Lead && <Lead size={ICON_SIZE} />}
                </span>
                {e.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
