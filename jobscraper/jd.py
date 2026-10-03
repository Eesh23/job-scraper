"""Fetch the full job description for a posting URL.

Uses each job board's public JSON where one exists (Workday, Greenhouse,
Lever, Ashby, SmartRecruiters), then falls back to the schema.org
JobPosting data most career pages embed for Google, then to the page text.
"""

import html
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import certifi

_SSL = ssl.create_default_context(cafile=certifi.where())
# Some career sites reject non-browser user agents outright.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) job-scraper/1.0 (personal use)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}


@dataclass
class JobDescription:
    url: str
    title: str
    company: str
    location: str
    text: str
    method: str  # which fetcher produced it


class FetchError(Exception):
    pass


def fetch(url: str) -> JobDescription:
    host = urlsplit(url).netloc.lower()
    fetchers = []
    if "myworkdayjobs.com" in host:
        fetchers.append(_workday)
    if "greenhouse.io" in host or "gh_jid=" in url:
        fetchers.append(_greenhouse)
    if "lever.co" in host:
        fetchers.append(_lever)
    if "ashbyhq.com" in host:
        fetchers.append(_ashby)
    if "smartrecruiters.com" in host:
        fetchers.append(_smartrecruiters)
    if "workable.com" in host:
        fetchers.append(_workable)
    if "oraclecloud.com" in host:
        fetchers.append(_oracle)
    fetchers.append(_generic)

    errors = []
    for fetcher in fetchers:
        try:
            jd = fetcher(url)
            if jd and len(jd.text) > 200:
                return jd
        except Exception as e:  # try the next method
            errors.append(f"{fetcher.__name__.strip('_')}: {e}")
    raise FetchError("could not read a job description from this link"
                     + (f" ({'; '.join(errors)})" if errors else ""))


# ---------------------------------------------------------------- per-platform

def _workday(url):
    parts = urlsplit(url)
    path = [p for p in parts.path.split("/") if p]
    if path and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]):  # locale, e.g. en-US
        path = path[1:]
    tenant = parts.netloc.split(".")[0]
    try:
        data = _get_json(f"https://{parts.netloc}/wday/cxs/{tenant}/{path[0]}/{'/'.join(path[1:])}")
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):  # Workday answers "permission denied" for removed postings
            raise FetchError("this posting looks closed (Workday no longer serves it)") from None
        raise
    info = data["jobPostingInfo"]
    company = (data.get("hiringOrganization") or {}).get("name") or tenant
    return JobDescription(url, info.get("title", ""), company, info.get("location", ""),
                          html_to_text(info.get("jobDescription", "")), "workday")


def _greenhouse(url):
    parts = urlsplit(url)
    job_id = (parse_qs(parts.query).get("gh_jid") or [None])[0]
    board = None
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?]+)/jobs/(\d+)", url)
    if m:
        board, job_id = m.group(1), m.group(2)
    if not job_id:
        raise FetchError("no Greenhouse job id")
    # For jobs embedded on a company's own site, guess the board from the domain.
    boards = [board] if board else _board_guesses(parts.netloc)
    for b in boards:
        try:
            d = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs/{job_id}")
        except Exception:
            continue
        return JobDescription(url, d.get("title", ""), d.get("company_name") or b,
                              (d.get("location") or {}).get("name", ""),
                              html_to_text(html.unescape(d.get("content", ""))), "greenhouse")
    raise FetchError("Greenhouse board not found")


def _lever(url):
    m = re.search(r"lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    d = _get_json(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
    sections = [d.get("descriptionPlain", "")]
    for block in d.get("lists", []):
        sections.append(block.get("text", "") + "\n" + html_to_text(block.get("content", "")))
    sections.append(d.get("additionalPlain", ""))
    return JobDescription(url, d.get("text", ""), m.group(1), (d.get("categories") or {}).get("location", ""),
                          "\n\n".join(s for s in sections if s), "lever")


def _ashby(url):
    m = re.search(r"ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    board = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")
    job = next((j for j in board.get("jobs", []) if j.get("id") == m.group(2)), None)
    if not job:
        raise FetchError("job no longer on the Ashby board")
    return JobDescription(url, job.get("title", ""), m.group(1), job.get("location", ""),
                          job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", "")), "ashby")


def _smartrecruiters(url):
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    d = _get_json(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}")
    sections = (d.get("jobAd") or {}).get("sections") or {}
    text = "\n\n".join(html_to_text((sections.get(k) or {}).get("text", ""))
                       for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
    loc = d.get("location") or {}
    return JobDescription(url, d.get("name", ""), (d.get("company") or {}).get("name", m.group(1)),
                          ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                          text, "smartrecruiters")


def _workable(url):
    m = re.search(r"workable\.com/([^/]+)/j/([0-9A-Za-z]+)", url)
    d = _get_json(f"https://apply.workable.com/api/v2/accounts/{m.group(1)}/jobs/{m.group(2)}")
    loc = d.get("location") or {}
    text = "\n\n".join(html_to_text(d.get(k) or "") for k in ("description", "requirements", "benefits"))
    return JobDescription(url, d.get("title", ""), m.group(1),
                          ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                          text, "workable")


def _oracle(url):
    """Oracle Recruiting Cloud: .../CandidateExperience/<lang>/sites/<site>/job/<id>"""
    parts = urlsplit(url)
    m = re.search(r"/sites/([^/]+)/job/(\d+)", parts.path)
    api = (f"https://{parts.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f"?expand=all&onlyData=true&finder=ById;Id=%22{m.group(2)}%22,siteNumber={m.group(1)}")
    d = _get_json(api)["items"][0]
    text = "\n\n".join(html_to_text(d.get(k) or "") for k in
                         ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
    return JobDescription(url, d.get("Title", ""), "", d.get("PrimaryLocation", ""), text, "oracle")


def _generic(url):
    page = _get_text(url)
    # schema.org JobPosting (used by most career sites for Google Jobs)
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                org = item.get("hiringOrganization") or {}
                loc = item.get("jobLocation") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                return JobDescription(url, item.get("title", ""), org.get("name", "") if isinstance(org, dict) else "",
                                      ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion")) if x),
                                      html_to_text(item.get("description", "")), "schema.org")
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    body = re.sub(r"<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    return JobDescription(url, html.unescape(title.group(1)).strip() if title else "", "", "",
                          html_to_text(body), "page text")


# ---------------------------------------------------------------- helpers

def html_to_text(fragment: str) -> str:
    text = re.sub(r"<\s*li[^>]*>", "\n- ", fragment, flags=re.I)
    text = re.sub(r"<\s*(br|/p|/div|/h\d|/li|/ul|/ol)[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _board_guesses(netloc: str) -> list[str]:
    name = netloc.lower().removeprefix("www.").split(".")
    base = name[-2] if len(name) >= 2 else name[0]
    stripped = re.sub(r"(careers|jobs)$", "", base)
    return list(dict.fromkeys(g for g in (base, stripped, name[0]) if g))


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30, context=_SSL) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _get_json(url: str):
    return json.loads(_get_text(url))
