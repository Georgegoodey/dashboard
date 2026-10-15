import { PANELS, PanelKey } from "../panels";
import "./mobile-workspace.css";

/** Phone layout: the chosen panel fills the screen (the dockable layout needs room that a phone does not have). */
export function MobileWorkspace({ active }: { active: PanelKey }) {
  const Active = PANELS[active].component;
  return (
    <div className="mobile-workspace">
      <Active />
    </div>
  );
}
