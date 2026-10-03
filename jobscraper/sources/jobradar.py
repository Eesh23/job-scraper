"""JobRadar-AI boards, e.g. github.com/Donkey0322/JobRadar-AI/blob/main/job-postings/entry-level.md

Jobs are in an HTML <table>; each <tr> has Company, Role, Location, Link
and Date ("Oct 2", no year) cells. A company cell of "↳" means "same
company as the row above". Role cells may carry badges such as
"citizen only" after a <br />.
"""

import hashlib
import html
import re
from datetime import date, datetime

from ..geo import is_remote, resolve
from ..http import get_text, github_raw
from ..models import Job
from ..workauth import CITIZEN_ONLY, NO_SPONSORSHIP

ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
HREF = re.compile(r'href="([^"]+)"')
BADGE = re.compile(r'alt="([^"]+)"')
BADGES = {"citizen only": CITIZEN_ONLY, "no visa": NO_SPONSORSHIP}
TAG = re.compile(r"<[^>]+>")


def fetch(cfg: dict) -> list[Job]:
    text = get_text(github_raw(cfg["repo"], cfg.get("branch", "main"), cfg["path"]))

    jobs, company = [], ""
    for row in ROW.findall(text):
        cells = CELL.findall(row)
        if len(cells) < 5:
            continue
        # Featured companies show a logo instead of text; its alt is the name.
        name = _clean(cells[0]) or next(iter(BADGE.findall(cells[0])), "")
        company = company if name == "↳" else name
        href = HREF.search(cells[3])
        if not href:
            continue
        url = html.unescape(href.group(1))
        title = _clean(cells[1].split("<br")[0])
        badges = [BADGES[b] for b in BADGE.findall(cells[1]) if b in BADGES]
        location = _clean(cells[2])
        jobs.append(Job(
            id="jobradar:" + hashlib.sha1(url.encode()).hexdigest()[:16],
            source=cfg.get("name", cfg["repo"]),
            company=company,
            title=title,
            location=location,
            country=resolve([location], cfg.get("default_country")),
            remote=is_remote(location),
            posted_on=_date(_clean(cells[4])),
            url=url,
            work_auth=badges[0] if badges else None,
        ))
    return jobs


def _clean(html: str) -> str:
    return " ".join(TAG.sub("", html).replace("&amp;", "&").split())


def _date(text: str) -> str | None:
    """'Oct 2' -> most recent past date with that month/day."""
    try:
        parsed = datetime.strptime(f"{text} {date.today().year}", "%b %d %Y").date()
    except ValueError:
        return None
    if parsed > date.today():
        parsed = parsed.replace(year=parsed.year - 1)
    return parsed.isoformat()
