import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { Button, Code, Disclosure, Empty, I, ICON_SIZE, Note, Panel, Scroll, Toolbar } from "@/components";
import { datasetsApi } from "./api";

export default function DataPanel() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const sets = useQuery({ queryKey: ["datasets"], queryFn: datasetsApi.list });
  const refresh = () => qc.invalidateQueries({ queryKey: ["datasets"] });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) await datasetsApi.upload(f);
    },
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: datasetsApi.remove, onSuccess: refresh });

  return (
    <Panel>
      <Toolbar>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".csv,.parquet,.json"
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) upload.mutate(files);
            e.target.value = "";
          }}
        />
        <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          <I.upload size={ICON_SIZE} />
          {upload.isPending ? "Loading…" : "Upload data"}
        </Button>
        <span className="muted">.csv .parquet .json → DuckDB table</span>
      </Toolbar>
      {upload.error && <Note kind="error">{upload.error.message}</Note>}
      {sets.error && <Note kind="error">Backend unreachable: {sets.error.message}</Note>}
      <Scroll>
        {sets.data?.length === 0 && <Empty>No datasets yet.</Empty>}
        {sets.data?.map((d) => (
          <Disclosure
            key={d.table}
            title={d.table}
            meta={`${d.rows.toLocaleString()} rows`}
            open
            actions={
              <Button variant="ghost" size="sm" icon title="Drop table" onClick={() => remove.mutate(d.table)}>
                <I.close size={ICON_SIZE} />
              </Button>
            }
          >
            <Code>{d.columns.map((c) => `${c.name.padEnd(14)} ${c.type}`).join("\n")}</Code>
          </Disclosure>
        ))}
      </Scroll>
    </Panel>
  );
}
