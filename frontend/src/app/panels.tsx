import type { ComponentType } from "react";
import {
  ChartLineUp, ChatsCircle, Code, Database, GearSix, House, ListMagnifyingGlass, Timer,
} from "@phosphor-icons/react";
import type { Icon } from "@/components";
import { ChartsPanel } from "@/features/charts";
import { ChatPanel } from "@/features/chat";
import { DataPanel } from "@/features/datasets";
import { JobsPanel, PropertiesPanel, SettingsPanel } from "@/features/lettings";
import { SqlPanel } from "@/features/sql";
import { TracePanel } from "@/features/trace";

/** Keys are stored in saved layouts (FlexLayout `component`), so renaming one resets saved layouts. */
export const PANELS = {
  properties: { title: "Properties", icon: House, component: PropertiesPanel },
  settings: { title: "Settings", icon: GearSix, component: SettingsPanel },
  jobs: { title: "Jobs", icon: Timer, component: JobsPanel },
  vega: { title: "Vega-Lite", icon: ChartLineUp, component: ChartsPanel },
  sql: { title: "SQL Console", icon: Code, component: SqlPanel },
  data: { title: "Datasets", icon: Database, component: DataPanel },
  chat: { title: "Chat", icon: ChatsCircle, component: ChatPanel },
  trace: { title: "Agent Trace", icon: ListMagnifyingGlass, component: TracePanel },
} satisfies Record<string, { title: string; icon: Icon; component: ComponentType }>;

export type PanelKey = keyof typeof PANELS;

/** How the header menu groups panels: one dropdown per section. */
export const PANEL_SECTIONS: { label: string; panels: PanelKey[] }[] = [
  { label: "Lettings", panels: ["properties", "settings", "jobs"] },
  { label: "Analytics", panels: ["vega", "sql", "data"] },
  { label: "Assistant", panels: ["chat", "trace"] },
];
