import { useStoredState } from "@/hooks";
import { isPanelKey, PanelKey } from "../panels";

/** On a phone one panel fills the screen; this remembers which. */
export function useMobilePanel() {
  return useStoredState<PanelKey>("dashboard.mobilePanel", () => "properties", isPanelKey);
}
