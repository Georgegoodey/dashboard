import type { ComponentType } from "react";
import {
  ChartLineUp, ChatsCircle, Code, Database, GearSix, House, ListMagnifyingGlass, MapPin, MapTrifold, Timer,
} from "@phosphor-icons/react";
import type { Icon } from "@/components";
import { ChartsPanel } from "@/features/charts";
import { ChatPanel } from "@/features/chat";
import { DatabasePanel } from "@/features/database";
import { CommutePointsPanel, JobsPanel, MapPanel, PropertiesPanel, SettingsPanel } from "@/features/lettings";
import { SqlPanel } from "@/features/sql";
import { TracePanel } from "@/features/trace";

/** Keys are stored in saved layouts (FlexLayout `component`), so renaming one resets saved layouts. */
export const PANELS = {
  properties: { title: "Properties", icon: House, component: PropertiesPanel },
  map: { title: "Map", icon: MapTrifold, component: MapPanel },
  commutes: { title: "Commute Points", icon: MapPin, component: CommutePointsPanel },
  settings: { title: "Search Settings", icon: GearSix, component: SettingsPanel },
  jobs: { title: "Jobs", icon: Timer, component: JobsPanel },
  vega: { title: "Market Analysis", icon: ChartLineUp, component: ChartsPanel },
  sql: { title: "SQL Console", icon: Code, component: SqlPanel },
  database: { title: "Database", icon: Database, component: DatabasePanel },
  chat: { title: "Chat", icon: ChatsCircle, component: ChatPanel },
  trace: { title: "Agent Trace", icon: ListMagnifyingGlass, component: TracePanel },
} satisfies Record<string, { title: string; icon: Icon; component: ComponentType }>;

export type PanelKey = keyof typeof PANELS;
export const isPanelKey = (v: string): v is PanelKey => v in PANELS;

/** How the header menu groups panels: one dropdown per section. */
export const PANEL_SECTIONS: { label: string; panels: PanelKey[] }[] = [
  { label: "Lettings", panels: ["properties", "map"] },
  { label: "Settings", panels: ["commutes", "settings"] },
  { label: "Analysis", panels: ["vega", "sql", "chat", "trace"] },
  { label: "Database", panels: ["database", "jobs"] },
];
