import { I, Menu } from "@/components";
import type { MenuEntry } from "@/components";
import { MODES, PALETTES, useTheme } from "@/hooks";
import { PANELS, PANEL_SECTIONS, PanelKey } from "../panels";
import "./header.css";

/** App title plus one dropdown per section (each lists the panels you can add); View holds theme and layout. */
export function Header({ onAdd, onResetLayout }: { onAdd: (key: PanelKey) => void; onResetLayout: () => void }) {
  const { mode, setMode, palette, setPalette } = useTheme();

  const view: MenuEntry[] = [
    { type: "heading", label: "Palette" },
    ...PALETTES.map((p): MenuEntry => ({ type: "item", label: p.label, checked: p.value === palette, onSelect: () => setPalette(p.value) })),
    { type: "separator" },
    { type: "heading", label: "Mode" },
    ...MODES.map((m): MenuEntry => ({ type: "item", label: m.label, checked: m.value === mode, onSelect: () => setMode(m.value) })),
    { type: "separator" },
    { type: "item", label: "Reset layout", icon: I.reset, onSelect: onResetLayout },
  ];

  return (
    <header className="app-header">
      <div className="app-title">
        <span className="app-logo" />
        Agent Dashboard
      </div>
      <nav className="app-menus" aria-label="Panels">
        {PANEL_SECTIONS.map((section) => (
          <Menu
            key={section.label}
            label={section.label}
            entries={section.panels.map((key): MenuEntry => ({
              type: "item",
              label: PANELS[key].title,
              icon: PANELS[key].icon,
              onSelect: () => onAdd(key),
            }))}
          />
        ))}
      </nav>
      <span className="spacer" />
      <Menu label="View" entries={view} align="end" />
    </header>
  );
}
