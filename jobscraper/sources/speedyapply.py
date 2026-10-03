"""speedyapply-format repos, e.g. github.com/speedyapply/2027-SWE-College-Jobs.

Jobs live in markdown tables (one per section: FAANG+, Quant, Other) with
rows like:
  | <a href=...><strong>Company</strong></a> | Title | City, ST | [$Salary |] <a href="APPLY"><img ...></a> | 3d |

`files` in the config maps each markdown file to the country to assume for
its rows ("US" for the USA file), or "" to infer it from the location text.
"""

import hashlib
import html
import re
from datetime import date, timedelta

from ..geo import countries_for, is_remote
from ..http import get_text, github_raw
from ..models import Job

TAG = re.compile(r"<[^>]+>")
HREF = re.compile(r'href="([^"]+)"')
AGE = re.compile(r"^(\d+)d$")


def fetch(cfg: dict) -> list[Job]:
    jobs = []
    for path, default_country in cfg["files"].items():
        text = get_text(github_raw(cfg["repo"], cfg.get("branch", "main"), path))
        for line in text.splitlines():
            if job := _parse_row(line, default_country, cfg):
                jobs.append(job)
    return jobs


def _parse_row(line: str, default_country: str, cfg: dict) -> Job | None:
    if not line.startswith("| <a"):
        return None
    cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
    if len(cells) < 5:
        return None

    company, title, location = (_clean(c) for c in cells[:3])
    apply_cell, age_cell = cells[-2], cells[-1]
    href = HREF.search(apply_cell)
    if not href:
        return None
    url = html.unescape(href.group(1))

    # Unrecognized places in the international file are outside North America.
    countries = {default_country} if default_country else (countries_for(location) or {"OTHER"})
    age = AGE.match(age_cell)
    return Job(
        # No ids in the table; the apply URL is unique per posting.
        id="speedyapply:" + hashlib.sha1(url.encode()).hexdigest()[:16],
        source=cfg.get("name", cfg["repo"]),
        company=company,
        title=title,
        location=location,
        country=",".join(sorted(countries)) or None,
        remote=is_remote(location),
        posted_on=(date.today() - timedelta(days=int(age.group(1)))).isoformat() if age else None,
        url=url,
    )


def _clean(cell: str) -> str:
    return TAG.sub("", cell).replace("&amp;", "&").strip()
