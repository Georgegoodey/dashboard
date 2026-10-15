import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button, Chip, Field, I, ICON_SIZE, Note, Segmented, StatStrip } from "@/components";
import { Area, lettings } from "../lib";

/** Outcodes next to the ones already searched, offered as one-click additions when they are not added yet. */
const SUGGESTIONS = ["SE5", "SE15", "SE16", "SE24", "SE14", "SE8", "SE21", "SE22", "SE23", "SE27", "SE1", "SE11", "SE17", "CR0", "SM1", "SM4", "SM5"];

type Show = "all" | "on" | "off";
const prefix = (outcode: string) => outcode.match(/^[A-Z]+/)?.[0] ?? outcode;
/** SW1A before SW2, SW9 before SW10: sort by the number, then the letter. */
const byOutcode = (a: Area, b: Area) => a.outcode.localeCompare(b.outcode, "en", { numeric: true });

export default function AreasManager() {
  const qc = useQueryClient();
  const areas = useQuery({ queryKey: ["areas"], queryFn: lettings.areas });
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [show, setShow] = useState<Show>("all");
  const [closed, setClosed] = useState<Set<string>>(new Set());

  const refresh = () => { for (const key of ["areas", "status", "properties", "map-points"]) qc.invalidateQueries({ queryKey: [key] }); };

  const add = useMutation({
    mutationFn: async (input: string) => {
      const codes = input.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
      const errors: string[] = [];
      for (const code of codes) {
        try { await lettings.addArea(code); } catch (e) { errors.push((e as Error).message); }
      }
      if (errors.length) throw new Error(errors.join("; "));
    },
    onSuccess: () => { setText(""); refresh(); },
    onError: refresh,
  });
  const toggleMany = useMutation({
    mutationFn: (items: { id: number; enabled: boolean }[]) => Promise.all(items.map((a) => lettings.setArea(a.id, a.enabled))),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (id: number) => lettings.deleteArea(id), onSuccess: refresh });

  const all = areas.data ?? [];
  const known = new Set(all.map((a) => a.outcode));
  const suggestions = SUGGESTIONS.filter((c) => !known.has(c)).slice(0, 8);
  const maxHomes = Math.max(1, ...all.map((a) => a.properties));

  const groups = useMemo(() => {
    const q = search.trim().toUpperCase();
    const visible = all
      .filter((a) => (show === "all" ? true : show === "on" ? a.enabled : !a.enabled))
      .filter((a) => !q || a.outcode.includes(q) || a.label.toUpperCase().includes(q))
      .sort(byOutcode);
    const map = new Map<string, Area[]>();
    for (const a of visible) map.set(prefix(a.outcode), [...(map.get(prefix(a.outcode)) ?? []), a]);
    return [...map.entries()].sort(([x], [y]) => x.localeCompare(y));
  }, [all, search, show]);

  const enabled = all.filter((a) => a.enabled);
  const flip = (g: string) => setClosed((c) => { const n = new Set(c); if (n.has(g)) n.delete(g); else n.add(g); return n; });

  return (
    <div className="areas-mgr">
      <StatStrip
        stats={[
          { label: "Areas", value: all.length },
          { label: "Searched", value: enabled.length, muted: enabled.length === 0, progress: all.length ? enabled.length / all.length : 0 },
          { label: "Homes", value: enabled.reduce((n, a) => n + a.properties, 0).toLocaleString("en-GB") },
        ]}
      />

      <div className="form-row areas-add">
        <Field label="Add outcodes (comma or space separated)">
          <input className="input" placeholder="SE5, SE16" value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) add.mutate(text); }} />
        </Field>
        <div className="row-actions">
          <Button size="sm" onClick={() => add.mutate(text)} disabled={!text.trim() || add.isPending}><I.add size={ICON_SIZE} /> Add</Button>
        </div>
        {add.error && <Note kind="error">{add.error.message}</Note>}
      </div>
      {suggestions.length > 0 && (
        <div className="areas-suggest">
          <span className="muted small">Nearby, not added:</span>
          {suggestions.map((c) => <Chip key={c} on={false} onClick={() => add.mutate(c)}>+ {c}</Chip>)}
        </div>
      )}

      <div className="areas-tools">
        <input className="input" placeholder="Filter areas" aria-label="Filter areas" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Segmented<Show> value={show} onChange={setShow} options={[{ value: "all", label: "All" }, { value: "on", label: "On" }, { value: "off", label: "Off" }]} />
      </div>

      {areas.data && groups.length === 0 && <div className="muted areas-none">{all.length === 0 ? "No areas yet." : "No areas match."}</div>}
      {groups.map(([g, list]) => {
        const isClosed = closed.has(g) && !search;
        const on = list.filter((a) => a.enabled).length;
        return (
          <section key={g} className="area-group">
            <header className="area-group-head">
              <button className="area-group-toggle" onClick={() => flip(g)} aria-expanded={!isClosed}>
                <span className={`caret${isClosed ? "" : " open"}`}><I.caret size={14} /></span>
                <b>{g}</b>
                <span className="muted small">{on}/{list.length} on · {list.reduce((n, a) => n + a.properties, 0).toLocaleString("en-GB")} homes</span>
              </button>
              <div className="area-group-actions">
                <Button variant="ghost" size="sm" disabled={on === list.length} onClick={() => toggleMany.mutate(list.filter((a) => !a.enabled).map((a) => ({ id: a.id, enabled: true })))}>All on</Button>
                <Button variant="ghost" size="sm" disabled={on === 0} onClick={() => toggleMany.mutate(list.filter((a) => a.enabled).map((a) => ({ id: a.id, enabled: false })))}>All off</Button>
              </div>
            </header>
            {!isClosed && (
              <ul className="area-list">
                {list.map((a) => (
                  <li key={a.id} className={`area-row${a.enabled ? "" : " off"}`}>
                    <label className="check">
                      <input type="checkbox" checked={a.enabled} onChange={(e) => toggleMany.mutate([{ id: a.id, enabled: e.target.checked }])} />
                      <b>{a.outcode}</b>
                    </label>
                    <span className="area-label muted small">{a.label !== a.outcode ? a.label : ""}</span>
                    <span className="area-bar" title={`${a.properties} homes`}><span style={{ width: `${(a.properties / maxHomes) * 100}%` }} /></span>
                    <span className="area-count small">{a.properties}</span>
                    <Button variant="ghost" size="sm" icon title={`Remove ${a.outcode}`} onClick={() => remove.mutate(a.id)}><I.close size={14} /></Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
