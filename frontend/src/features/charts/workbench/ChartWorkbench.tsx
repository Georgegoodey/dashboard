import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Badge, Button, I, ICON_SIZE } from "@/components";
import AutoChart from "../auto-chart/AutoChart";
import { ChartCard } from "../ChartCard";
import type { ChartResult, ChartSpec } from "../lib";
import SpecEditor from "./SpecEditor";

/** One chart card for any ChartResult: draws the (inferred or user-edited) spec and offers the spec editor.
 *  Used by the gallery and by the SQL console, so both behave identically. */
export default function ChartWorkbench({
  result,
  title,
  subtitle,
  height = 280,
  override,
  startOpen = false,
  extraActions,
}: {
  result: ChartResult;
  title: string;
  subtitle?: string;
  height?: number;
  /** Partial spec merged over the inferred one (e.g. force a donut for a share query). */
  override?: Partial<ChartSpec>;
  startOpen?: boolean;
  /** Rendered before the Customize button (e.g. a table/chart switch). */
  extraActions?: ReactNode;
}) {
  const base = useMemo<ChartSpec>(() => ({ ...result.spec, ...override }), [result, override]);
  const [custom, setCustom] = useState<ChartSpec | null>(null);
  const [open, setOpen] = useState(startOpen);
  useEffect(() => setCustom(null), [result]); // a new query starts from its own inferred spec
  const spec = custom ?? base;

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      height={height}
      actions={
        <>
          {extraActions}
          <Button variant="ghost" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <I.customize size={ICON_SIZE} />
            {open ? "Hide" : "Customize"}
          </Button>
        </>
      }
      badge={<Badge>{spec.type}</Badge>}
      footer={open && <SpecEditor result={result} spec={spec} onChange={setCustom} onReset={() => setCustom(null)} />}
    >
      <AutoChart data={result.data} spec={spec} formats={result.formats} />
    </ChartCard>
  );
}
