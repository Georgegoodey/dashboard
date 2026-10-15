import type { ReactNode } from "react";
import "./empty.css";

export const Empty = ({ children }: { children: ReactNode }) => <p className="empty">{children}</p>;
