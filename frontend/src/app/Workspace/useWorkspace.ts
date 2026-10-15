import { Layout, Model, TabSetNode } from "flexlayout-react";
import { useRef, useState } from "react";
import { storage } from "@/lib";
import { PanelKey } from "../panels";
import { defaultLayout, tab } from "./defaultLayout";

const STORAGE_KEY = "dashboard.layout.v8";

function loadModel(): Model {
  try {
    const saved = storage.get(STORAGE_KEY);
    if (saved) return Model.fromJson(JSON.parse(saved));
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
