"""Best-effort location string -> ISO country code(s), for sources that only
give free-text locations like "Toronto, ON, Canada", "NYC", "Chicago IL" or
"Remote in USA". Only North America is recognized precisely; anything else
returns "OTHER" when it clearly names a non-NA place, or nothing when it
can't tell.
"""

import re
import unicodedata

US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire",
    "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
    "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
    "PR": "puerto rico",
}
CA_PROVINCES = {
    "AB": "alberta", "BC": "british columbia", "MB": "manitoba", "NB": "new brunswick",
    "NL": "newfoundland", "NS": "nova scotia", "NT": "northwest territories", "NU": "nunavut",
    "ON": "ontario", "PE": "prince edward island", "QC": "quebec", "SK": "saskatchewan",
    "YT": "yukon",
}

# Whole-part matches (the entire comma-separated piece, lowercased).
US_EXACT = {"usa", "us", "u.s.", "u.s", "u.s.a.", "nyc", "sf", "la", "d.c.", "dc", "bay area"}
CA_EXACT = {"can", "ca-on", "ca-bc", "ca-qc"}
MX_EXACT = {"mex"}

# Phrases matched as whole words anywhere in a piece. Countries come first so
# "Melbourne, Australia" isn't caught by a US phrase.
PHRASES = [
    ("OTHER", [
        "united kingdom", "england", "scotland", "ireland", "europe", "emea", "apac", "india",
        "germany", "france", "spain", "italy", "poland", "netherlands", "singapore", "australia",
        "japan", "china", "israel", "vietnam", "brazil", "romania", "bulgaria", "malaysia",
        "philippines", "switzerland", "sweden", "portugal", "czechia", "hungary", "korea",
        "taiwan", "hong kong", "london", "dublin", "berlin", "munich", "paris", "amsterdam",
        "bangalore", "bengaluru", "hyderabad", "melbourne", "sydney", "tokyo", "tel aviv",
        "uk",
    ]),
    ("MX", ["mexico", "guadalajara", "monterrey"]),
    ("CA", ["canada", *CA_PROVINCES.values(), "toronto", "vancouver", "montreal", "waterloo",
            "ottawa", "calgary", "edmonton", "kitchener", "mississauga"]),
    ("US", ["united states", "united states of america", "u.s.", *US_STATES.values(),
            "new york city", "san francisco", "los angeles", "seattle", "boston", "austin",
            "chicago", "denver", "boulder", "atlanta", "sunnyvale", "mountain view", "palo alto",
            "san mateo", "san jose", "santa clara", "menlo park", "cupertino", "redmond",
            "bellevue", "san diego", "ann arbor", "pittsburgh", "philadelphia", "dallas",
            "houston", "miami", "boise", "salt lake city", "raleigh", "nashville", "phoenix"]),
]
_PHRASE_RE = [
    (code, re.compile(r"(?<![a-z])(" + "|".join(re.escape(p) for p in sorted(words, key=len, reverse=True)) + r")(?![a-z])"))
    for code, words in PHRASES
]


def countries_for(location: str) -> set[str]:
    """Return country codes for one location string (may be empty)."""
    text = _strip_accents(re.sub(r"\s*\+\s*\d+(\s*more)?\s*$", "", location))  # "Québec, Canada +3"
    parts = [p.strip() for p in re.split(r",|\bin\b|/|\(|\)| - |;|>|:", text) if p.strip()]

    # Last piece decides first: "Toronto, ON, Canada", "Austin, TX", "London, UK".
    for part in reversed(parts):
        if code := _match_part(part):
            return {code}
    return set()


def countries_for_all(locations: list[str]) -> set[str]:
    return set().union(*(countries_for(loc) for loc in locations)) if locations else set()


def is_remote(text: str) -> bool:
    return "remote" in text.lower()


def _match_part(part: str) -> str | None:
    low = part.lower().strip(" .")
    if part in US_STATES or low in US_EXACT or low + "." in US_EXACT:
        return "US"
    if part in CA_PROVINCES or low in CA_EXACT:
        return "CA"
    if low in MX_EXACT:
        return "MX"

    # Trailing state/province code: "Chicago IL", "San Mateo CA USA".
    for token in part.split()[-2:]:
        if token.strip("-.").lower() in ("us", "usa"):
            return "US"
        if token in US_STATES:
            return "US"
        if token in CA_PROVINCES:
            return "CA"

    for code, pattern in _PHRASE_RE:
        if pattern.search(low):
            return code
    return None


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def resolve(locations: list[str], default: str | None = None) -> str | None:
    """Comma-joined country codes for a job, falling back to the source's
    default country (for US-only lists) when no location is recognized."""
    found = countries_for_all(locations) or ({default} if default else set())
    return ",".join(sorted(found)) or None
