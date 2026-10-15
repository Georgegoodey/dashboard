import { ITabRenderValues, Layout, TabNode } from "flexlayout-react";
import "flexlayout-react/style/dark.css";
import { I } from "@/components";
import { PANELS, PanelKey } from "../panels";
import type { useWorkspace } from "./useWorkspace";
import "./workspace.css";

/** FlexLayout's own tab buttons, drawn with the same icon set as the rest of the UI. */
const layoutIcons = {
  close: <I.close size={14} />,
  closeTabset: <I.close size={14} />,
  maximize: <I.maximize size={14} />,
  restore: <I.restore size={14} />,
  more: <I.more size={16} weight="bold" />,
};

function factory(node: TabNode) {
  const panel = PANELS[node.getComponent() as PanelKey];
  return panel ? <panel.component /> : null;
}

/** Puts each panel icon in front of its tab title. */
function renderTab(node: TabNode, values: ITabRenderValues) {
  const panel = PANELS[node.getComponent() as PanelKey];
  if (panel) values.leading = <panel.icon size={14} />;
}

export function Workspace({ workspace }: { workspace: ReturnType<typeof useWorkspace> }) {
  return (
    <Layout
      ref={workspace.layoutRef}
      model={workspace.model}
      factory={factory}
      icons={layoutIcons}
      onRenderTab={renderTab}
      onModelChange={workspace.save}
    />
  );
}
