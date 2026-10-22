import type { Anchor, CommutePoint, Direction, Journey, RouteSummary } from "../lib";
import { WEEKDAYS } from "../lib";

/** The points that are switched on, which are the only ones the lists, filters and map show. */
export const activePoints = (points: CommutePoint[] | undefined): CommutePoint[] => (points ?? []).filter((p) => p.enabled);

/** A point's journeys for one property, in the order they were added. */
export const routesFor = (commutes: RouteSummary[], pointId: number): RouteSummary[] =>
  commutes.filter((c) => c.point_id === pointId);

/** The longest journey to a point (what "within 30 minutes" means when it has a morning and an evening trip). */
export function worstMinutes(commutes: RouteSummary[], pointId: number): number | null {
  const mins = routesFor(commutes, pointId).map((c) => c.duration_min).filter((m): m is number => m != null);
  return mins.length ? Math.max(...mins) : null;
}

/** "22 min", or "22 / 27 min" when the point has several journeys; "–" when none has been planned yet. */
export function minutesText(commutes: RouteSummary[], pointId: number): string {
  const routes = routesFor(commutes, pointId);
  if (routes.length === 0) return "–";
  const parts = routes.map((r) => (r.duration_min == null ? "–" : String(r.duration_min)));
  return `${parts.join(" / ")} min`;
}

export const verb = (anchor: Anchor) => (anchor === "arrive_by" ? "arrive by" : "leave at");
export const way = (direction: Direction) => (direction === "to_place" ? "To" : "From");

/** "To Work, arrive by 09:00 on Tuesday" */
export const describeJourney = (j: Pick<Journey, "direction" | "anchor" | "local_time" | "weekday">, label: string) =>
  `${way(j.direction)} ${label}, ${verb(j.anchor)} ${j.local_time} on ${WEEKDAYS[j.weekday]}`;
