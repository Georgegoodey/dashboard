import { useState } from "react";
import { Badge, Button, I, ICON_SIZE, Note, Panel, Scroll, Section, Segmented, Spacer, Toolbar } from "@/components";
import { useDatabaseOverview } from "../hooks";
import { MigrationsView } from "../migrations";
import { TablesView } from "../tables";
import "./database-panel.css";

type View = "tables" | "migrations";

/** Database manager: connection status, what is in Postgres, and migrations. */
export default function DatabasePanel() {
  const [view, setView] = useState<View>("tables");
  const db = useDatabaseOverview();
  const pending = db.data?.migrations.pending.length ?? 0;
  const server = db.data?.server_version.match(/^PostgreSQL [\d.]+/)?.[0];

  return (
    <Panel>
      <Toolbar>
        {db.data && <Badge>connected</Badge>}
        {db.error && <Badge neutral>unreachable</Badge>}
        {db.data && (
          <span className="muted">
            {db.data.name} · {server} · {db.data.size}
          </span>
        )}
        <Spacer />
        <Button variant="ghost" size="sm" onClick={() => db.refetch()} disabled={db.isFetching}>
          <I.rerun size={ICON_SIZE} /> Refresh
        </Button>
      </Toolbar>
      <Section>
        <Segmented<View>
          value={view}
          onChange={setView}
          options={[
            { value: "tables", label: `Tables${db.data ? ` (${db.data.relations.length})` : ""}` },
            { value: "migrations", label: pending ? `Migrations (${pending} pending)` : "Migrations" },
          ]}
        />
      </Section>
      {db.error && <Note kind="error">{db.error.message}</Note>}
      <Scroll>
        {db.data && view === "tables" && <TablesView relations={db.data.relations} />}
        {db.data && view === "migrations" && <MigrationsView migrations={db.data.migrations} />}
      </Scroll>
    </Panel>
  );
}
