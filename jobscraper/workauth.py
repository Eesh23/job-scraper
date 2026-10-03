"""Work-authorization triage for a Canadian applying in the US.

Every listing lands in one bucket:
  drop     - explicitly US citizens only (or security clearance, which
             requires citizenship). Not shown at all.
  best     - in Canada, says it sponsors, or the employer has a real H-1B
             sponsorship history (USCIS H-1B Employer Data Hub).
  unknown  - everything else in the US. Most listings never mention
             sponsorship, and Canadians can often use TN status anyway.

Signals come from (a) what a source says (`Job.work_auth`), (b) the title
("... - US Citizenship Required", "TS/SCI"), and (c) USCIS approval counts.
"""

import csv
import io
import re
from pathlib import Path

from .http import get_text
from .models import Job

# Job.work_auth values, strongest first. Merged listings keep the strongest.
CITIZEN_ONLY = "citizen_only"
CLEARANCE = "clearance"
SPONSORS = "sponsors"
NO_SPONSORSHIP = "no_sponsorship"
PRIORITY = [CITIZEN_ONLY, CLEARANCE, SPONSORS, NO_SPONSORSHIP]

CITIZEN_TEXT = re.compile(
    r"u\.?s\.? citizens?(hip)?\s*(only|required|is required)|must be a u\.?s\.? citizen"
    r"|citizenship (is )?required|requires? u\.?s\.? citizenship|u\.?s\.? citizenship\b",
    re.I,
)
CLEARANCE_TEXT = re.compile(
    r"clearance|ts/sci|top secret|\bsecret\b|polygraph|\bpoly\b|\bsci\b|\bdod\b|\bitar\b",
    re.I,
)

USCIS_CSV = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{year}.csv"
NAME_NOISE = re.compile(
    r"\b(the|and|inc|incorporated|llc|l l c|ltd|limited|corp|corporation|co|company|plc|lp|llp|pllc|pc"
    r"|na|n a|group|holdings|technologies|technology|services|service|usa|us|u s|america|north america"
    r"|of america|international|solutions|labs|com|dba\b.*)\b"
)
# Job-list name -> name USCIS knows the employer by (after normalizing).
ALIASES = {
    "spacex": "spaceexploration", "rtx": "raytheon", "ngc": "northropgrumman", "citi": "citibank",
    "bny": "bankofnewyorkmellon", "ey": "ernstyoung", "jpmorgan": "jpmorganchase", "jpmorganchase": "jpmorganchase",
    "meta": "metaplatforms", "google": "google", "aws": "amazonwebservices", "homedepot": "homedepot",
    "gm": "generalmotors", "ge": "generalelectric", "capitalone": "capitalone", "kpmg": "kpmg",
}


def normalize_company(name: str) -> str:
    name = re.sub(r"\([^)]*\)", " ", name.lower())  # "Whatnot (YC W20)"
    name = name.replace("&", " ").replace(".com", " com")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    key = re.sub(r"\s+", "", NAME_NOISE.sub(" ", name))
    return ALIASES.get(key, key)


class H1BData:
    """Total H-1B approvals (initial + continuing) per employer, summed over
    the configured fiscal years. CSVs are downloaded once into data_dir."""

    def __init__(self, data_dir: Path, years: list[int]):
        self.approvals: dict[str, int] = {}
        data_dir.mkdir(parents=True, exist_ok=True)
        for year in years:
            path = data_dir / f"h1b_{year}.csv"
            if not path.exists():
                path.write_text(get_text(USCIS_CSV.format(year=year)))
            for row in csv.DictReader(io.StringIO(path.read_text(errors="replace"))):
                key = normalize_company(row.get("Employer") or "")
                if key:
                    total = int(row.get("Initial Approval") or 0) + int(row.get("Continuing Approval") or 0)
                    self.approvals[key] = self.approvals.get(key, 0) + total
        # For prefix lookups ("State Street" -> "statestreetbanktrust").
        self._keys = sorted(self.approvals)

    def lookup(self, company: str) -> int:
        key = normalize_company(company)
        if not key:
            return 0
        if key in self.approvals:
            return self.approvals[key]
        if len(key) >= 6:  # short names ("citi", "kla") would prefix-match too much
            return max((n for k, n in self.approvals.items() if k.startswith(key)), default=0)
        return 0


def from_title(title: str) -> str | None:
    if CITIZEN_TEXT.search(title):
        return CITIZEN_ONLY
    if CLEARANCE_TEXT.search(title):
        return CLEARANCE
    return None


def strongest(values) -> str | None:
    present = {v for v in values if v}
    return next((v for v in PRIORITY if v in present), None)


def assess(job: Job, h1b: H1BData | None, cfg: dict) -> tuple[str, str]:
    """Return (bucket, note) for one (merged) listing."""
    status = strongest([job.work_auth, from_title(job.title)])
    if status == CITIZEN_ONLY:
        return "drop", "US citizens only"
    if status == CLEARANCE and cfg.get("drop_clearance", True):
        return "drop", "Security clearance (US citizens only)"

    if "CA" in job.countries:
        return "best", "In Canada - no visa needed"
    if status == SPONSORS:
        return "best", "Posting says it sponsors visas"

    approvals = h1b.lookup(job.company) if h1b else 0
    if approvals >= cfg.get("min_h1b_approvals", 10):
        return "best", f"Known H-1B sponsor ({approvals:,} approvals FY{_years(cfg)})"

    if status == NO_SPONSORSHIP:
        return "unknown", "Says no visa sponsorship - TN may still work"
    if approvals:
        return "unknown", f"Small H-1B history ({approvals} approvals)"
    return "unknown", "No sponsorship info"


def _years(cfg: dict) -> str:
    years = sorted(cfg.get("h1b_years", []))
    if not years:
        return ""
    return f"{str(years[0])[2:]}-{str(years[-1])[2:]}" if len(years) > 1 else str(years[0])[2:]
