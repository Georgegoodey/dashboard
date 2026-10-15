import "./vega.css";
import { useEffect, useRef } from "react";
import type { VisualizationSpec } from "vega-embed";

/** Renders a Vega-Lite spec. vega-embed is loaded on demand so it stays out of the main bundle. */
export function VegaView({ spec }: { spec: VisualizationSpec }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let ro: ResizeObserver | undefined;
    let finalize: (() => void) | undefined;

    import("vega-embed").then(async ({ default: embed }) => {
      if (!ref.current) return;
      const result = await embed(ref.current, spec, { actions: false, renderer: "svg", tooltip: true });
      if (cancelled) return result.finalize();
      finalize = result.finalize;
      // spec width/height are "container": re-measure when the dock panel is resized
      ro = new ResizeObserver(() => void result.view.resize().runAsync());
      ro.observe(ref.current);
    });

    return () => {
      cancelled = true;
      ro?.disconnect();
      finalize?.();
    };
  }, [spec]);

  return <div ref={ref} />;
}
