import { Badge, Code, Disclosure, Empty } from "@/components";
import type { Relation } from "../api";

const describe = (r: Relation) =>
  [r.rows === null ? null : `${r.rows.toLocaleString()} ${r.rows === 1 ? "row" : "rows"}`, r.size]
    .filter(Boolean)
    .join(" · ");

/** Every table and view in the public schema, with its columns. */
export default function TablesView({ relations }: { relations: Relation[] }) {
  if (!relations.length) return <Empty>No tables yet.</Empty>;
  return (
    <>
      {relations.map((r) => (
        <Disclosure
          key={r.name}
          title={r.name}
          meta={describe(r)}
          actions={<Badge neutral={r.kind === "table"}>{r.kind}</Badge>}
        >
          <Code>
            {r.columns.map((c) => `${c.name.padEnd(22)} ${c.type}${c.nullable ? "" : "  not null"}`).join("\n")}
          </Code>
        </Disclosure>
      ))}
    </>
  );
}
