"""Describe a SQL result and infer a chart spec from its shape.

One module owns this logic so every consumer (chart gallery, SQL console, agent tools) gets the same answer.
The returned spec is plain JSON that the front-end's generic renderer draws, and users can edit it afterwards.

Spec shape (camelCase keys, consumed directly by the TypeScript side):
    type     bar | line | area | composed | pie | scatter | table
    x        column on the x axis (scatter: a measure)
    xKind    temporal | category | number
    xFormat  number format for a numeric x (scatter)
    series   [{field, name, kind: bar|line|area|scatter, axis: left|right, format}]
    group    long-form column whose values become series (client pivots), or null
    stack    stack bars/areas
    size     scatter bubble-size column, or null
    label    scatter point-label column, or null
    details  extra columns shown only in tooltips
"""
import re
from typing import Any

_NUMERIC = re.compile(r"^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?\d*|DECIMAL|DOUBLE|FLOAT\d*|REAL|NUMERIC|MONEY)", re.I)
_TEMPORAL_TYPE = re.compile(r"^(DATE|TIMESTAMP)", re.I)
_TEMPORAL_STR = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T].*)?$")
_ID_NAME = re.compile(r"(^|_)(id|uuid|key)$", re.I)
# numeric date parts (EXTRACT(MONTH ...)) are positions on an axis, not quantities to plot
_DATE_PART = re.compile(r"^(year|month|quarter|week|day|hour|yr|mth|dow|weekday)(_?(num|number|no))?$", re.I)
# small whole-number counts that act as categories when grouped by (bedrooms, changes), not as quantities to plot
_COUNT_CATEGORY = re.compile(r"^(bedrooms?|bathrooms?|beds?|baths?|rooms?|transfers|changes|.*_transfers|price_changes)$", re.I)

_MONEY = re.compile(r"revenue|sales|price|amount|cost|profit|income|spend|rent", re.I)
_PCT_POINTS = re.compile(r"pct|percent", re.I)
_FRACTION = re.compile(r"rate|ratio|share|discount|margin", re.I)
_LINEISH = re.compile(r"avg|average|moving|rolling|trend|mean|median|forecast|target", re.I)

MAX_CATEGORIES = 30      # more distinct values than this and a text column is a label, not an axis
SECONDARY_AXIS_RATIO = 0.05  # a measure this much smaller than the largest, in a different unit, goes on the right axis
PLAIN_NUMBER_RATIO = 0.01    # same test for two unformatted numbers, where the unit is a guess


def humanize(name: str) -> str:
    s = name.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def _numbers(values: list[Any]) -> list[float]:
    return [abs(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def guess_format(name: str, values: list[Any]) -> str:
    nums = _numbers(values)
    if _PCT_POINTS.search(name):
        return "percent_pt"
    if _FRACTION.search(name) and nums and max(nums) <= 1:
        return "percent"
    if _MONEY.search(name):
        return "money"
    return "number"


def column_role(name: str, type_str: str, values: list[Any]) -> str:
    """measure | temporal | dimension (low-cardinality text) | label (high-cardinality text or id)."""
    if _TEMPORAL_TYPE.match(type_str):
        return "temporal"
    if _NUMERIC.match(type_str):
        if _ID_NAME.search(name) or (len(values) > 1 and len(set(values)) == 1):
            return "label"  # an id, or a number that is the same on every row, is not something to plot
        if _DATE_PART.match(name) or (_COUNT_CATEGORY.match(name) and len(set(values)) <= MAX_CATEGORIES):
            return "dimension"
        return "measure"
    non_null = [v for v in values if v is not None]
    if non_null and all(isinstance(v, str) and _TEMPORAL_STR.match(v) for v in non_null):
        return "temporal"
    distinct = len(set(non_null))
    # a column with one value across several rows (e.g. year = 2025) carries no information for an axis or split
    if distinct == 1 and len(values) > 1:
        return "label"
    return "dimension" if distinct <= MAX_CATEGORIES else "label"


def describe(columns: list[str], types: list[str], rows: list[list[Any]]) -> dict:
    cols = {c: [r[i] for r in rows] for i, c in enumerate(columns)}
    roles = {c: column_role(c, t, cols[c]) for c, t in zip(columns, types)}
    formats = {c: guess_format(c, cols[c]) for c in columns if roles[c] == "measure"}
    return {"roles": roles, "formats": formats}


def _series(measures: list[str], cols: dict[str, list[Any]], formats: dict[str, str], temporal: bool) -> list[dict]:
    mags = {m: max(_numbers(cols[m]), default=0) for m in measures}
    top = max(mags.values(), default=0) or 1
    top_format = formats[max(measures, key=lambda m: mags[m])]
    out = []
    for i, m in enumerate(measures):
        # A second axis is for a different unit (orders next to revenue), not just a smaller number:
        # same-unit series such as per-category revenue must share one axis to stay comparable.
        # Unformatted numbers carry no unit hint, so only a very large gap (rating 4 vs 2,500 orders) splits them.
        limit = SECONDARY_AXIS_RATIO if formats[m] != top_format else PLAIN_NUMBER_RATIO if formats[m] == "number" else 0
        small = mags[m] < top * limit
        axis = "right" if len(measures) > 1 and small else "left"
        if len(measures) == 1:
            kind = "area" if temporal else "bar"
        elif (i == 0 or not temporal) and axis == "left" and not _LINEISH.search(m):
            kind = "bar"
        else:
            kind = "line"
        out.append({"field": m, "name": humanize(m), "axis": axis, "kind": kind, "format": formats[m]})
    # a category axis with only lines reads badly: make the first left-axis series bars
    if not temporal and out and not any(o["kind"] == "bar" for o in out):
        first_left = next((o for o in out if o["axis"] == "left"), None)
        if first_left:
            first_left["kind"] = "bar"
    # a derived metric (moving_avg, rolling_mean, ...) shares units with the series it is drawn beside
    for s in out:
        if s["format"] == "number" and _LINEISH.search(s["field"]):
            base = next((o for o in out if o is not s and o["axis"] == s["axis"] and not _LINEISH.search(o["field"])), None)
            if base:
                s["format"] = base["format"]
    return out


def _overall_type(series: list[dict]) -> str:
    kinds = {s["kind"] for s in series}
    return kinds.pop() if len(kinds) == 1 else "composed"


def infer(columns: list[str], types: list[str], rows: list[list[Any]]) -> dict:
    info = describe(columns, types, rows)
    roles, formats = info["roles"], info["formats"]
    cols = {c: [r[i] for r in rows] for i, c in enumerate(columns)}

    measures = [c for c in columns if roles[c] == "measure"]
    temporal = [c for c in columns if roles[c] == "temporal"]
    dims = [c for c in columns if roles[c] == "dimension"]
    labels = [c for c in columns if roles[c] == "label"]

    spec: dict = {
        "type": "table", "x": None, "xKind": "category", "xFormat": None, "series": [],
        "group": None, "stack": False, "size": None, "label": None, "details": [],
    }
    if not rows or not measures:
        return {**info, "spec": spec}

    x_candidates = temporal + dims
    if not x_candidates:
        if len(measures) < 2:
            return {**info, "spec": spec}
        # No axis-worthy dimension: plot measure against measure (optionally sized), labelled by id/text.
        x, y, *rest = measures
        spec.update(
            type="scatter", x=x, xKind="number", xFormat=formats[x],
            series=[{"field": y, "name": humanize(y), "axis": "left", "kind": "scatter", "format": formats[y]}],
            size=rest[0] if rest else None,
            label=(labels or [None])[0],
            details=rest[1:],
        )
        return {**info, "spec": spec}

    x = x_candidates[0]
    is_temporal = roles[x] == "temporal"
    others = [c for c in x_candidates if c != x]
    spec.update(x=x, xKind="temporal" if is_temporal else "category")

    if len(measures) == 1 and others:
        # long-form: (x, group, value) becomes one series per group value
        m = measures[0]
        kind = "line" if is_temporal else "bar"
        spec.update(
            series=[{"field": m, "name": humanize(m), "axis": "left", "kind": kind, "format": formats[m]}],
            group=others[0],
            stack=not is_temporal,
            type=kind,
        )
        return {**info, "spec": spec}

    series = _series(measures, cols, formats, is_temporal)
    stackable = [s for s in series if s["kind"] == "bar" and s["axis"] == "left"]
    spec.update(series=series, type=_overall_type(series), stack=len(stackable) >= 2 and len(stackable) == len(series))
    return {**info, "spec": spec}
