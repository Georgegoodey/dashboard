import { useEffect } from "react";
import { useStoredState } from "./useStoredState";

export type Mode = "light" | "dark";
export const MODES: { value: Mode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];
export const PALETTES = [
  { value: "terminal", label: "Terminal" },
  { value: "synth", label: "Synthwave" },
  { value: "blue", label: "Blueprint" },
] as const;
export type Palette = (typeof PALETTES)[number]["value"];

const isMode = (v: string): v is Mode => v === "light" || v === "dark";
const isPalette = (v: string): v is Palette => PALETTES.some((p) => p.value === v);
const systemMode = (): Mode => (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");

/** Light/dark mode (a class on <html>) and colour palette (data-theme on <html>), both remembered. */
export function useTheme() {
  const [mode, setMode] = useStoredState<Mode>("dashboard.theme", systemMode, isMode);
  const [palette, setPalette] = useStoredState<Palette>("dashboard.palette", () => "terminal", isPalette);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", mode === "dark");
  }, [mode]);
  useEffect(() => {
    document.documentElement.dataset.theme = palette;
  }, [palette]);
  return { mode, setMode, palette, setPalette };
}
