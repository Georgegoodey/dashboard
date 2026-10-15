import type { ReactNode } from "react";
import "./panel.css";

/** Every panel is: header bar (bottom border) / content (16px padding) / optional footer bar (top border). */
export const Panel = ({ children }: { children: ReactNode }) => <div className="panel">{children}</div>;
export const Scroll = ({ children }: { children: ReactNode }) => <div className="scroll">{children}</div>;

/** Header bar (border below). Footer is the same bar with the border above. */
export const Toolbar = ({ children }: { children: ReactNode }) => <div className="toolbar">{children}</div>;
export const Footer = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`footer ${className}`}>{children}</div>
);
/** Padded, bottom-bordered block between header and content (e.g. an editor). */
export const Section = ({ children }: { children: ReactNode }) => <div className="section">{children}</div>;
export const Spacer = () => <span className="spacer" />;
