"""Turn messy advert text into comparable values."""
import re
from datetime import date, datetime
from decimal import Decimal

_ABBREV = {
    "road": "rd", "street": "st", "avenue": "ave", "gardens": "gdns", "garden": "gdn", "lane": "ln", "court": "ct",
    "drive": "dr", "place": "pl", "square": "sq", "terrace": "ter", "crescent": "cres", "grove": "gr", "mews": "mews",
    "apartment": "flat", "apartments": "flats", "apt": "flat", "flat": "flat", "house": "hse", "close": "cl",
    "park": "pk", "walk": "wk", "gate": "gt", "hill": "hl", "way": "way", "row": "row", "villas": "vlls",
}
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
OUTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$", re.I)


def normalise_postcode(value: str | None) -> str | None:
    """'sw117fd' / 'SW11  7FD' -> 'SW11 7FD'. Returns None if it does not look like a full UK postcode."""
    if not value:
        return None
    m = POSTCODE_RE.search(value.upper().replace("\xa0", " "))
    return f"{m.group(1)} {m.group(2)}" if m else None


def normalise_address(address: str | None) -> str:
    """Lower-case, strip punctuation, standardise street and flat words, drop the trailing postcode and the town."""
    if not address:
        return ""
    s = POSTCODE_RE.sub(" ", address)
    s = re.sub(r"[^\w\s]", " ", s.lower())
    words = [_ABBREV.get(w, w) for w in s.split()]
    return " ".join(words).strip()


def pcm_from(amount: float | int | None, frequency: str | None) -> tuple[Decimal | None, Decimal | None]:
    """(rent_pcm, rent_pw) from an advertised amount and its period. pcm = pw x 52 / 12."""
    if amount is None:
        return None, None
    a = Decimal(str(amount))
    f = (frequency or "monthly").lower()
    if f in ("monthly", "pcm", "month"):
        return a, (a * 12 / 52).quantize(Decimal("0.01"))
    if f in ("weekly", "pw", "week"):
        return (a * 52 / 12).quantize(Decimal("0.01")), a
    if f in ("quarterly",):
        return (a / 3).quantize(Decimal("0.01")), (a * 4 / 52).quantize(Decimal("0.01"))
    if f in ("yearly", "annually", "pa"):
        return (a / 12).quantize(Decimal("0.01")), (a / 52).quantize(Decimal("0.01"))
    if f in ("daily", "pd"):
        return (a * 365 / 12).quantize(Decimal("0.01")), (a * 7).quantize(Decimal("0.01"))
    return None, None


def parse_date(value: str | None) -> date | None:
    """Advert dates come as 'dd/mm/yyyy', ISO strings, or words such as 'Ask agent' and 'Now' (which become None)."""
    if not value:
        return None
    v = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(v[:20] if fmt.startswith("%Y") else v, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
    return date.fromisoformat(m.group(1)) if m else None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def outcode_from_text(text: str | None) -> str | None:
    """The outward postcode ending an address or title, such as 'London SW18' or 'Battersea Rise, SW11'; None if absent."""
    tail = (text or "").replace(",", " ").split()
    for token in reversed(tail[-3:]):
        if OUTCODE_RE.match(token):
            return token.upper()
    return None


def html_to_text(html: str | None) -> str | None:
    """Advert HTML to plain text, keeping paragraph, list and line breaks."""
    if not html:
        return None
    from selectolax.lexbor import LexborHTMLParser

    html = re.sub(r"(?i)<br\s*/?>\s*</li>", "</li>", html)
    marked = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", lambda m: "\n\n" if m.group(0).lower() == "</p>" else "\n", html)
    text = LexborHTMLParser(marked).text(separator="")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r" ?\n ?", "\n", text)).strip() or None
