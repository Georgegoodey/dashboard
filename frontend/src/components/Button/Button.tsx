import type { ButtonHTMLAttributes } from "react";
import "./button.css";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "soft" | "ghost";
  size?: "md" | "sm";
  icon?: boolean;
};

export function Button({ variant = "primary", size = "md", icon, className = "", ...rest }: ButtonProps) {
  const cls = ["btn", `btn-${variant}`, size === "sm" && "btn-sm", icon && "btn-icon", className]
    .filter(Boolean)
    .join(" ");
  return <button className={cls} {...rest} />;
}
