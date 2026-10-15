import { Actions, Layout, Model, TabNode, TabSetNode } from "flexlayout-react";
import { useRef, useState } from "react";
import { storage } from "@/lib";
import { PANELS, PanelKey } from "../panels";
import { defaultLayout, tab } from "./defaultLayout";

const STORAGE_KEY = "dashboard.layout.v8";

/** Saved layouts remember each tab's title; refresh them so renaming a panel in code shows up without resetting the layout. */
function withCurrentTitles(model: Model): Model {
  model.visitNodes((n) => {
    if (!(n instanceof TabNode)) return;
    const panel = PANELS[n.getComponent() as PanelKey];
    if (panel && n.getName() !== panel.title) model.doAction(Actions.renameTab(n.getId(), panel.title));
  });
  return model;
}

function loadModel(): Model {
  try {
    const saved = storage.get(STORAGE_KEY);
    if (saved) return withCurrentTitles(Model.fromJson(JSON.parse(saved)));
  } catch {
    /* corrupt saved layout: fall through to the default */
  }
  return Model.fromJson(defaultLayout);
}

/** Owns the FlexLayout model: restores and saves it, adds panels, resets to the default arrangement. */
export function useWorkspace() {
  const [model, setModel] = useState(loadModel);
  const layoutRef = useRef<Layout>(null);

  const addPanel = (key: PanelKey) => {
    const layout = layoutRef.current;
    if (!layout) return;
    const node = tab(key);
    if (model.getActiveTabset()) return void layout.addTabToActiveTabSet(node);
    // nothing has been clicked yet, so no tabset is active: fall back to the first one
    let first: TabSetNode | undefined;
    model.visitNodes((n) => {
      if (!first && n instanceof TabSetNode) first = n;
    });
    if (first) layout.addTabToTabSet(first.getId(), node);
  };

  const resetLayout = () => {
    storage.remove(STORAGE_KEY);
    setModel(Model.fromJson(defaultLayout));
  };

  const save = (m: Model) => storage.set(STORAGE_KEY, JSON.stringify(m.toJson()));

  return { model, layoutRef, addPanel, resetLayout, save };
}
