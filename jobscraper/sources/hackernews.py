"""Hacker News "Ask HN: Who is hiring?" monthly threads (mostly startups).

Uses the official HN Algolia API: find the latest threads posted by the
`whoishiring` account, then fetch each thread's comments in one request.
Posts are free text, conventionally starting with a header line like
  Company | Role(s) | Location | ONSITE/REMOTE | ...
so the company, role and location are best-effort guesses from that line.
A post is kept only if its text mentions entry-level hiring.
"""

import html
import re
from datetime import date

from ..geo import countries_for, is_remote
from ..http import get_json
from ..models import Job
from ..workauth import CITIZEN_TEXT, CITIZEN_ONLY, NO_SPONSORSHIP, SPONSORS

NO_VISA = re.compile(r"no (visa )?sponsorship|unable to sponsor|cannot sponsor|can't sponsor|not sponsor", re.I)
VISA = re.compile(r"visa sponsorship|will sponsor|sponsor visas|h-?1b", re.I)

THREADS = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"
ENTRY = re.compile(
    r"new[ -]grads?\b|new graduates?|recent grad|entry[ -]level|\bjunior\b|early[ -]career"
    r"|university grad|college grad|0\s*[-–+]\s*[12]\+?\s*years",
    re.I,
)
ROLE = re.compile(r"engineer|developer|manager|scientist|architect|analyst|designer|programmer|\bswe\b|\bpm\b", re.I)


def fetch(cfg: dict) -> list[Job]:
    threads = [h for h in get_json(THREADS)["hits"] if h["title"].startswith("Ask HN: Who is hiring?")]
    jobs = []
    for thread in threads[: cfg.get("months", 1)]:
        for post in get_json(ITEM.format(id=thread["objectID"])).get("children", []):
            if job := _parse(post, cfg):
                jobs.append(job)
    return jobs


def _parse(post: dict, cfg: dict) -> Job | None:
    if not post.get("text"):
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", post["text"].replace("<p>", "\n")))
    if not ENTRY.search(text):
        return None

    header = text.strip().split("\n")[0]
    parts = [p.strip() for p in header.split("|") if p.strip()]
    if not parts:
        return None
    company = re.sub(r"\(\s*\)", "", re.sub(r"https?://\S+", "", parts[0])).strip(" ()")
    roles = [p for p in parts[1:] if ROLE.search(p)]
    places = [p for p in parts[1:] if countries_for(p) or is_remote(p)]
    countries = set().union(*(countries_for(p) for p in places)) if places else set()

    return Job(
        id=f"hn:{post['id']}",
        source=cfg.get("name", "Hacker News - Who is hiring"),
        company=company[:80],
        title="; ".join(roles)[:150] or "(see post)",
        location="; ".join(places)[:150],
        country=",".join(sorted(countries)) or None,
        remote=any(is_remote(p) for p in places),
        posted_on=(post.get("created_at") or "")[:10] or date.today().isoformat(),
        url=f"https://news.ycombinator.com/item?id={post['id']}",
        work_auth=_work_auth(text),
    )


def _work_auth(text: str) -> str | None:
    if CITIZEN_TEXT.search(text):
        return CITIZEN_ONLY
    if NO_VISA.search(text):
        return NO_SPONSORSHIP
    if VISA.search(text):
        return SPONSORS
    return None
