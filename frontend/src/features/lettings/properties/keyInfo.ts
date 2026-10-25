import type { Furnishing, Property } from "../lib";

export const FURNISH_LABEL: Record<Furnishing, string> = {
  furnished: "Furnished", part_furnished: "Part furnished", unfurnished: "Unfurnished", flexible: "Furnished or unfurnished",
};

/** The key facts read from the adverts, as short labels (what is known about the home, in the order that matters). */
export function keyTags(p: Pick<Property, "furnish_type" | "is_shared" | "pets_allowed" | "bills_included" | "has_garden" | "has_parking" | "has_balcony">): string[] {
  return [
    p.furnish_type ? FURNISH_LABEL[p.furnish_type] : null,
    p.is_shared ? "Shared" : null,
    p.pets_allowed ? "Pets allowed" : null,
    p.bills_included ? "Bills included" : null,
    p.has_garden ? "Garden" : null,
    p.has_parking ? "Parking" : null,
    p.has_balcony ? "Balcony" : null,
  ].filter((t): t is string => t !== null);
}

/** "08:15" from a TfL local time such as 2026-10-20T08:15:00. */
export const clock = (iso: string | null | undefined) => (iso && iso.length >= 16 ? iso.slice(11, 16) : null);

/** A stored journey summary, "Walk to X (7m) > 37 bus to Y (20m)", as its steps. */
export const steps = (summary: string | null | undefined) => (summary ?? "").split(" > ").map((s) => s.trim()).filter(Boolean);
