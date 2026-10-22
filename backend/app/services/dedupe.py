"""Finding the same home advertised on several portals, and merging it into one property.

Search results carry no postcode, so adverts from different portals are stored as separate properties and the matching that
`listings.insert_new` does on postcode and address never gets a key to work with. This works on what is stored instead.

Two properties are the same home when ALL of these hold:
- they have the same number of bedrooms;
- their coordinates are within MAX_DISTANCE_M of each other;
- their active rents are within RENT_MATCH of each other (a few portals round or add fees);
- they start with the same street name, after any flat or house number (the one text check that keeps two different
  buildings that happen to be next to each other, with identical flats, apart);
- no portal has an advert on both (two adverts from one portal are different homes, however alike).

And it is NOT ambiguous: a home that has more than one candidate on some other portal (a tower with identical flats) is left
alone entirely, because there is no telling which pairs with which. Merged groups must also be complete: every home in the
group matches every other, so a chain A-B, B-C with A and C too far apart is not merged.

`plan` only reads. `apply` merges, one group at a time in its own transaction, and records what it absorbed in
`property_merges` so a merge can be reversed by hand.
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from app.db.database import Database
from app.repositories import app_settings

KEY = "dedupe"
MAX_DISTANCE_M = 30
RENT_BROAD = 0.03          # candidates for the ambiguity check
RENT_MATCH = 0.02          # a pair must be this close to merge
_LEADING = frozenset({"flat", "unit", "room", "apt", "no", "floor", "ground", "first", "second", "third", "top"})


# ── settings ────────────────────────────────────────────────────────────────────────────────────────────────────

def auto_enabled(db: Database) -> bool:
    """Whether the dedupe job merges by itself. Off until you have looked at what it would do."""
    return bool(app_settings.get(db, KEY).get("auto", False))


def set_auto(db: Database, auto: bool) -> None:
    app_settings.put(db, KEY, {**app_settings.get(db, KEY), "auto": auto})


# ── planning (pure apart from reading candidate pairs) ───────────────────────────────────────────────────────────

def street_of(address_norm: str) -> str:
    """The street's first word: '12 Wilton Rd, London SW19' and 'Flat B, Wilton Rd' both give 'wilton'."""
    tokens = (address_norm or "").split()
    while tokens and (re.fullmatch(r"\d+[a-z]?", tokens[0]) or len(tokens[0]) == 1 or tokens[0] in _LEADING):
        tokens = tokens[1:]
    return tokens[0] if tokens else ""


@dataclass(frozen=True)
class Edge:
    """A pair of properties that are near each other with the same bedrooms and a similar rent."""
    a: int
    b: int
    sources_a: frozenset[str]
    sources_b: frozenset[str]
    distance_m: float
    rent_diff: float            # fraction of the rent, 0.01 = 1%
    address_a: str
    address_b: str


@dataclass
class Plan:
    clusters: list[list[int]] = field(default_factory=list)       # each: property ids to merge into one, lowest id first
    edges: int = 0
    ambiguous: int = 0                                           # properties left alone: several candidates on one portal
    different_street: int = 0                                    # pairs near each other that do not start with the same street
    rent_too_far: int = 0                                        # pairs whose rents differ by more than RENT_MATCH
    incomplete_groups: int = 0                                   # chains where not every home matches every other
    by_sources: dict[str, int] = field(default_factory=dict)      # "onthemarket + rightmove": groups

    @property
    def absorbed(self) -> int:
        return sum(len(c) - 1 for c in self.clusters)

    def summary(self) -> dict[str, Any]:
        return {"groups": len(self.clusters), "would_absorb": self.absorbed, "candidate_pairs": self.edges,
                "ambiguous_skipped": self.ambiguous, "different_street_skipped": self.different_street,
                "rent_too_far_skipped": self.rent_too_far, "incomplete_groups_skipped": self.incomplete_groups,
                "by_sources": self.by_sources}


def plan_from_edges(edges: list[Edge]) -> Plan:
    plan = Plan(edges=len(edges))
    # a property with two candidates that share a portal is ambiguous (identical flats in one block)
    per_source: dict[tuple[int, str], set[int]] = defaultdict(set)
    for e in edges:
        for s in e.sources_b:
            per_source[(e.a, s)].add(e.b)
        for s in e.sources_a:
            per_source[(e.b, s)].add(e.a)
    ambiguous = {pid for (pid, _), others in per_source.items() if len(others) > 1}
    plan.ambiguous = len(ambiguous)

    accepted: list[Edge] = []
    for e in edges:
        if e.a in ambiguous or e.b in ambiguous:
            continue
        if e.rent_diff > RENT_MATCH:
            plan.rent_too_far += 1
        elif not street_of(e.address_a) or street_of(e.address_a) != street_of(e.address_b):
            plan.different_street += 1
        else:
            accepted.append(e)

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in accepted:
        parent[find(e.a)] = find(e.b)
    groups: dict[int, set[int]] = defaultdict(set)
    sources: dict[int, frozenset[str]] = {}
    for e in accepted:
        groups[find(e.a)] |= {e.a, e.b}
        sources[e.a], sources[e.b] = e.sources_a, e.sources_b
    pairs = {(e.a, e.b) for e in accepted}
    for members in groups.values():
        ids = sorted(members)
        if any((a, b) not in pairs for a, b in combinations(ids, 2)):
            plan.incomplete_groups += 1                    # a chain, not a clique
            continue
        plan.clusters.append(ids)
        label = " + ".join(sorted(set().union(*(sources[i] for i in ids))))
        plan.by_sources[label] = plan.by_sources.get(label, 0) + 1
    plan.clusters.sort()
    return plan


_EDGES_SQL = """
WITH a AS (
    SELECT p.id AS pid, p.bedrooms, p.geom, p.address_norm, l.rent_pcm,
           (SELECT array_agg(DISTINCT s.name) FROM listings x JOIN sources s ON s.id = x.source_id WHERE x.property_id = p.id) AS sources
    FROM properties p JOIN listings l ON l.property_id = p.id
    WHERE l.status = 'active' AND p.geom IS NOT NULL AND p.bedrooms IS NOT NULL AND l.rent_pcm > 0
)
SELECT DISTINCT ON (x.pid, y.pid) x.pid AS a, y.pid AS b, x.sources AS sources_a, y.sources AS sources_b,
       ST_Distance(x.geom, y.geom) AS distance_m, abs(x.rent_pcm - y.rent_pcm) / x.rent_pcm AS rent_diff,
       x.address_norm AS address_a, y.address_norm AS address_b
FROM a x JOIN a y ON x.pid < y.pid AND x.bedrooms = y.bedrooms AND ST_DWithin(x.geom, y.geom, %(dist)s)
                 AND abs(x.rent_pcm - y.rent_pcm) <= %(rent)s * x.rent_pcm AND NOT (x.sources && y.sources)
ORDER BY x.pid, y.pid, abs(x.rent_pcm - y.rent_pcm)
"""


def plan(db: Database) -> Plan:
    """What merging would do now. Reads only."""
    rows = db.fetch_all(_EDGES_SQL, {"dist": MAX_DISTANCE_M, "rent": RENT_BROAD})
    return plan_from_edges([
        Edge(r["a"], r["b"], frozenset(r["sources_a"]), frozenset(r["sources_b"]), float(r["distance_m"]), float(r["rent_diff"]),
             r["address_a"] or "", r["address_b"] or "") for r in rows])


def describe(db: Database, clusters: list[list[int]]) -> list[dict[str, Any]]:
    """The homes in each group, for showing what a merge would join."""
    ids = sorted({i for c in clusters for i in c})
    if not ids:
        return []
    rows = db.fetch_all(
        "SELECT p.id, p.address, p.postcode, p.bedrooms, s.name AS source, l.rent_pcm, l.url FROM properties p "
        "JOIN listings l ON l.property_id = p.id AND l.status = 'active' JOIN sources s ON s.id = l.source_id "
        "WHERE p.id = ANY(%s) ORDER BY p.id, s.name", (ids,))
    by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        home = by_id.setdefault(r["id"], {"id": r["id"], "address": r["address"], "postcode": r["postcode"],
                                          "bedrooms": r["bedrooms"], "adverts": []})
        home["adverts"].append({"source": r["source"], "rent_pcm": float(r["rent_pcm"]) if r["rent_pcm"] is not None else None,
                                "url": r["url"]})
    return [{"homes": [by_id[i] for i in c if i in by_id]} for c in clusters]


# ── merging ──────────────────────────────────────────────────────────────────────────────────────────────────────

_FILL = """
UPDATE properties s SET
    uprn = coalesce(s.uprn, o.uprn), postcode = coalesce(s.postcode, o.postcode), outcode = coalesce(s.outcode, o.outcode),
    borough = coalesce(s.borough, o.borough), bathrooms = coalesce(s.bathrooms, o.bathrooms),
    property_type = coalesce(s.property_type, o.property_type), floor_area_m2 = coalesce(s.floor_area_m2, o.floor_area_m2),
    epc_rating = coalesce(s.epc_rating, o.epc_rating), geom = coalesce(s.geom, o.geom),
    first_seen = least(s.first_seen, o.first_seen), last_seen = greatest(s.last_seen, o.last_seen)
FROM (SELECT (array_agg(uprn ORDER BY id) FILTER (WHERE uprn IS NOT NULL))[1] AS uprn,
             (array_agg(postcode ORDER BY id) FILTER (WHERE postcode IS NOT NULL))[1] AS postcode,
             (array_agg(outcode ORDER BY id) FILTER (WHERE outcode IS NOT NULL))[1] AS outcode,
             (array_agg(borough ORDER BY id) FILTER (WHERE borough IS NOT NULL))[1] AS borough,
             (array_agg(bathrooms ORDER BY id) FILTER (WHERE bathrooms IS NOT NULL))[1] AS bathrooms,
             (array_agg(property_type ORDER BY id) FILTER (WHERE property_type IS NOT NULL))[1] AS property_type,
             (array_agg(floor_area_m2 ORDER BY id) FILTER (WHERE floor_area_m2 IS NOT NULL))[1] AS floor_area_m2,
             (array_agg(epc_rating ORDER BY id) FILTER (WHERE epc_rating IS NOT NULL))[1] AS epc_rating,
             (array_agg(geom::geometry ORDER BY id) FILTER (WHERE geom IS NOT NULL))[1]::geography AS geom,
             min(first_seen) AS first_seen, max(last_seen) AS last_seen
      FROM properties WHERE id = ANY(%(others)s)) o
WHERE s.id = %(survivor)s
"""

_SNAPSHOT = """
SELECT jsonb_agg(jsonb_build_object(
    'property', to_jsonb(p) - 'geom', 'lat', ST_Y(p.geom::geometry), 'lon', ST_X(p.geom::geometry),
    'listing_ids', (SELECT coalesce(jsonb_agg(l.id), '[]'::jsonb) FROM listings l WHERE l.property_id = p.id))) AS absorbed
FROM properties p WHERE p.id = ANY(%s)
"""


def merge_group(db: Database, ids: list[int]) -> dict[str, int]:
    """Merge the properties in `ids` into one. The survivor is the one with a postcode, then the lowest id.
    Its listings and commute routes come with it; the rest are deleted after being recorded in property_merges."""
    with db.conn() as c:
        rows = c.execute("SELECT id FROM properties WHERE id = ANY(%s) ORDER BY (postcode IS NOT NULL) DESC, id", (ids,)).fetchall()
        if len(rows) < 2:
            return {"absorbed": 0, "listings_moved": 0}                  # one was already merged or removed
        survivor, others = rows[0]["id"], [r["id"] for r in rows[1:]]
        snapshot = c.execute(_SNAPSHOT, (others,)).fetchone()
        moved = c.execute("UPDATE listings SET property_id = %s WHERE property_id = ANY(%s)", (survivor, others)).rowcount
        for other in others:                                             # one at a time: their routes may overlap
            c.execute(
                "UPDATE commute_routes r SET property_id = %(s)s WHERE r.property_id = %(o)s AND NOT EXISTS ("
                "SELECT 1 FROM commute_routes x WHERE x.property_id = %(s)s AND x.profile_id = r.profile_id "
                "AND x.provider = r.provider AND x.ref_date = r.ref_date)", {"s": survivor, "o": other})
        c.execute(_FILL, {"survivor": survivor, "others": others})
        c.execute("INSERT INTO property_merges (survivor_id, absorbed) VALUES (%s, %s::jsonb)",
                  (survivor, json.dumps(snapshot["absorbed"] if snapshot else [], default=str)))
        c.execute("DELETE FROM properties WHERE id = ANY(%s)", (others,))
    return {"absorbed": len(others), "listings_moved": moved}


def apply(db: Database, plan_to_apply: Plan | None = None) -> dict[str, int]:
    """Merge every group in the plan (a fresh one if none is given). Returns what was done."""
    todo = plan_to_apply or plan(db)
    done = {"groups": 0, "absorbed": 0, "listings_moved": 0}
    for ids in todo.clusters:
        result = merge_group(db, ids)
        if result["absorbed"]:
            done["groups"] += 1
            done["absorbed"] += result["absorbed"]
            done["listings_moved"] += result["listings_moved"]
    return done


def merged_total(db: Database) -> int:
    """How many properties have been absorbed into others so far."""
    row = db.fetch_one("SELECT coalesce(sum(jsonb_array_length(absorbed)), 0)::int AS n FROM property_merges")
    return int(row["n"]) if row else 0
