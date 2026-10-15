import { I, Menu } from "@/components";
import type { MenuEntry } from "@/components";
import { MODES, PALETTES, useTheme } from "@/hooks";
import { PANELS, PANEL_SECTIONS, PanelKey } from "../panels";
import "./header.css";

/** App title plus one dropdown per section (each lists the panels you can add); View holds theme and layout.
 *  `compact` (phones) folds everything into one menu and shows which panel is open. */
export function Header({
  onAdd,
  onResetLayout,
  compact,
  active,
}: {
  onAdd: (key: PanelKey) => void;
  onResetLayout: () => void;
  compact: boolean;
  active: PanelKey;
}) {
  const { mode, setMode, palette, setPalette } = useTheme();

  const sections = PANEL_SECTIONS.map((section) => ({
    label: section.label,
    entries: section.panels.map((key): MenuEntry => ({
      type: "item",
      label: PANELS[key].title,
      icon: PANELS[key].icon,
      onSelect: () => onAdd(key),
    })),
  }));

  const appearance: MenuEntry[] = [
    { type: "heading", label: "Palette" },
    ...PALETTES.map((p): MenuEntry => ({ type: "item", label: p.label, checked: p.value === palette, onSelect: () => setPalette(p.value) })),
    { type: "separator" },
    { type: "heading", label: "Mode" },
    ...MODES.map((m): MenuEntry => ({ type: "item", label: m.label, checked: m.value === mode, onSelect: () => setMode(m.value) })),
  ];
  const resetLayout: MenuEntry[] = [
    { type: "separator" },
    { type: "item", label: "Reset layout", icon: I.reset, onSelect: onResetLayout },
  ];

  if (compact) {
    const all: MenuEntry[] = [
      ...sections.flatMap((s): MenuEntry[] => [{ type: "heading", label: s.label }, ...s.entries]),
      { type: "separator" },
      ...appearance,
    ];
    return (
      <header className="app-header">
        <span className="app-logo" />
        <div className="app-title">{PANELS[active].title}</div>
        <Menu label="Menu" entries={all} align="end" />
      </header>
    );
  }

  return (
    <header className="app-header">
      <div className="app-title">
        <span className="app-logo" />
        Lettings Finder
      </div>
      <nav className="app-menus" aria-label="Panels">
        {sections.map((s) => (
          <Menu key={s.label} label={s.label} entries={s.entries} />
        ))}
      </nav>
      <span className="spacer" />
      <Menu label="View" entries={[...appearance, ...resetLayout]} align="end" />
    </header>
  );
}
