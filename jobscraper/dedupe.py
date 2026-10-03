"""Merge the same posting appearing in several sources (or several locations
of one source) into one row.

Two jobs are the same if EITHER
  - their apply links point at the same posting (after normalizing away
    tracking params, /apply suffixes, locale segments, ...), or
  - their normalized company + title match ("The Home Depot" == "Homedepot",
    "Junior Engineer (Hybrid)" == "Junior Engineer").

The row keeps the job from the highest-priority source (earliest in
config.toml) as its primary, so list sources with direct employer links first.
"""

import re
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlsplit

from .models import Job
from .workauth import strongest

COMPANY_NOISE = re.compile(
    r"\b(the|inc|llc|ltd|corp|corporation|co|company|plc|group|technologies|holdings|industries"
    r"|international|solutions|united states)\b"
)
# Parentheticals / suffixes that only say where or how you work, not what the job is.
WORK_MODE = r"hybrid|remote|on-?site|in-office|in office|usa|us|u\.s\.|united states|canada"
TITLE_NOISE = [
    re.compile(rf"\((?:[^()]*\b(?:{WORK_MODE})\b[^()]*)\)"),
    re.compile(rf"\s[-–—|]\s*(?:{WORK_MODE})\s*$"),
]
# Same word, different spelling: "Software Engineer I" == "Software Engineer 1".
TITLE_WORDS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "jr": "junior", "sr": "senior", "and": ""}
YEAR = re.compile(r"\b20\d\d\b")
URL_SUFFIXES = re.compile(r"/(apply|application|applications|apply/?\w*)$")
LOCALE_SEGMENT = re.compile(r"/[a-z]{2}-[a-z]{2}(?=/)")


@dataclass
class Listing:
    job: Job  # primary job; location/country/source merged from all members
    first_seen: str
    is_new: bool  # every member was first seen this run
    sources: list[str]


def title_key(job: Job) -> str:
    company = re.sub(r"[^a-z0-9]+", "", COMPANY_NOISE.sub("", job.company.lower()))
    title = job.title.lower().replace("&", " and ")
    for pattern in TITLE_NOISE:
        title = pattern.sub(" ", title)
    # Class years are noise unless paired with a season ("Summer 2027").
    if not re.search(r"(summer|fall|winter|spring)\s+20\d\d", title):
        title = YEAR.sub(" ", title)
    words = re.sub(r"[^a-z0-9]+", " ", title).split()
    return company + "|" + " ".join(w for w in (TITLE_WORDS.get(w, w) for w in words) if w)


def url_key(url: str) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.lower())
    query = parse_qs(parts.query)
    if "gh_jid" in query:  # Greenhouse job embedded on a company's own site
        return "greenhouse:" + query["gh_jid"][0]
    path = LOCALE_SEGMENT.sub("", URL_SUFFIXES.sub("", parts.path.rstrip("/")))
    host = parts.netloc.removeprefix("www.")
    if host.startswith("boards.greenhouse.io") or host.startswith("job-boards.greenhouse.io"):
        return "greenhouse:" + path.rsplit("/", 1)[-1]
    return host + path


def merge(rows: list[tuple[Job, str]], new_ids: set[str], source_order: list[str]) -> list[Listing]:
    rank = {name: i for i, name in enumerate(source_order)}

    # Union-find: rows sharing a title key or a URL key end up in one group.
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen_keys: dict[str, int] = {}
    for i, (job, _) in enumerate(rows):
        for k in (title_key(job), url_key(job.url)):
            if k is None:
                continue
            if k in seen_keys:
                parent[find(i)] = find(seen_keys[k])
            else:
                seen_keys[k] = i

    groups: dict[int, list[tuple[Job, str]]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)

    listings = []
    for members in groups.values():
        members.sort(key=lambda m: rank.get(m[0].source, len(rank)))
        primary = members[0][0]
        jobs = [j for j, _ in members]
        merged = replace(
            primary,
            location=_join_unique(j.location for j in jobs),
            country=",".join(sorted(set().union(*(j.countries for j in jobs)))) or None,
            remote=any(j.remote for j in jobs),
            posted_on=max((j.posted_on for j in jobs if j.posted_on), default=None),
            work_auth=strongest(j.work_auth for j in jobs),
        )
        listings.append(Listing(
            job=merged,
            first_seen=min(seen for _, seen in members),
            is_new=all(j.id in new_ids for j in jobs),
            sources=list(dict.fromkeys(j.source for j in jobs)),
        ))

    listings.sort(key=lambda l: (l.job.posted_on or "", l.first_seen), reverse=True)
    return listings


def _join_unique(values, limit=4) -> str:
    # Sources often repeat one place in different spellings; split on ";" and
    # dedupe case-insensitively before joining.
    unique = {}
    for value in values:
        for piece in value.split(";"):
            piece = piece.strip()
            if piece:
                unique.setdefault(piece.lower(), piece)
    places = list(unique.values())
    text = "; ".join(places[:limit])
    return text + f" (+{len(places) - limit} more)" if len(places) > limit else text
