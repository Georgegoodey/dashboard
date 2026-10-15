import type { ReactNode } from "react";
import "./code.css";

export const Code = ({ children, out }: { children: ReactNode; out?: boolean }) => (
  <pre className={`code${out ? " out" : ""}`}>{children}</pre>
);
