/** One place that decides which Phosphor icon means what, so the same action looks the same everywhere.
 *  (Which icon a panel gets lives with the panel registry in app/panels.tsx.) */
import {
  ArrowClockwise, ArrowCounterClockwise, ArrowSquareOut, ArrowsIn, ArrowsOut, ArrowsOutSimple, Broom, CaretDown,
  CaretRight, ChartBar, Check, DotsThree, FloppyDisk, Info, Moon, PaperPlaneRight, Play, Plus, SlidersHorizontal, Sun,
  Table, Trash, Warning, Wrench, X,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";

export type { Icon };

export const I = {
  add: Plus,
  external: ArrowSquareOut,
  save: FloppyDisk,
  trash: Trash,
  close: X,
  check: Check,
  send: PaperPlaneRight,
  run: Play,
  rerun: ArrowClockwise,
  reset: ArrowCounterClockwise,
  clear: Broom,
  customize: SlidersHorizontal,
  chart: ChartBar,
  table: Table,
  tool: Wrench,
  caret: CaretRight,
  caretDown: CaretDown,
  maximize: ArrowsOutSimple,
  expand: ArrowsOut,
  restore: ArrowsIn,
  more: DotsThree,
  sun: Sun,
  moon: Moon,
  info: Info,
  warn: Warning,
} as const;

export const ICON_SIZE = 16;
