import { Badge, Button, DataTable, I, ICON_SIZE, Note } from "@/components";
import type { Migrations } from "../api";
import { useMigrate } from "../hooks";

/** Applied and pending migrations, with a button to apply whatever is pending. */
export default function MigrationsView({ migrations }: { migrations: Migrations }) {
  const migrate = useMigrate();
  const { applied, pending } = migrations;
  const rows = [...applied.map((m) => [m.version, "applied"]), ...pending.map((v) => [v, "pending"])];

  return (
    <>
      <div className="db-actions">
        <Badge neutral={!pending.length}>{pending.length ? `${pending.length} pending` : "up to date"}</Badge>
        <Button size="sm" disabled={!pending.length || migrate.isPending} onClick={() => migrate.mutate()}>
          <I.run size={ICON_SIZE} />
          {migrate.isPending ? "Applying…" : "Apply pending"}
        </Button>
      </div>
      {migrate.error && <Note kind="error">{migrate.error.message}</Note>}
      <DataTable columns={["revision", "status"]} rows={rows} />
    </>
  );
}
