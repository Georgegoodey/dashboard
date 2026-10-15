import type { ReactNode } from "react";
import { I, ICON_SIZE } from "../icons";
import "./note.css";

export function Note({ children, kind = "info" }: { children: ReactNode; kind?: "info" | "error" }) {
  const Icon = kind === "error" ? I.warn : I.info;
  return (
    <div className={`note note-${kind}`}>
      <Icon size={ICON_SIZE} weight="bold" />
      <div>{children}</div>
    </div>
  );
}
