import type { IJsonModel } from "flexlayout-react";
import { PANELS, PanelKey } from "../panels";

export const tab = (component: PanelKey) => ({ type: "tab" as const, name: PANELS[component].title, component });

export const defaultLayout: IJsonModel = {
  global: { tabSetEnableMaximize: true, splitterSize: 6 },
  layout: {
    type: "row",
    // FlexLayout flips orientation per nesting level: root = horizontal, its child row = vertical (stacked),
    // and that row's children are horizontal again. Chat is intentionally not open by default (Analysis menu).
    children: [
      {
        type: "row",
        children: [
          {
            type: "row",
            weight: 64,
            children: [
              { type: "tabset", weight: 64, children: [tab("properties"), tab("map")] },
              { type: "tabset", weight: 36, children: [tab("settings"), tab("jobs")] },
            ],
          },
          {
            type: "row",
            weight: 36,
            children: [
              { type: "tabset", weight: 50, children: [tab("sql"), tab("vega")] },
              { type: "tabset", weight: 50, children: [tab("trace"), tab("database")] },
            ],
          },
        ],
      },
    ],
  },
};
