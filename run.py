"""Fetch jobs from every configured source, store them, and report new ones.

Usage:
    .venv/bin/python run.py                  # normal run
    .venv/bin/python run.py --config other.toml
    .venv/bin/python run.py --all            # list every new job, not just the top ones
"""

import argparse
import sys
import tomllib
from pathlib import Path

from jobscraper.dedupe import merge
from jobscraper.export import write_excel
from jobscraper.filters import matches
from jobscraper.sources import fetch_source
from jobscraper.storage import Store
from jobscraper.workauth import H1BData, assess

ROOT = Path(__file__).resolve().parent
PREVIEW_ROWS = 25  # new jobs printed per sheet; the Excel file has all of them


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=ROOT / "config.toml", type=Path)
    parser.add_argument("--all", action="store_true", help="print every new job instead of the first few")
    args = parser.parse_args()

    cfg = tomllib.loads(args.config.read_text())
    filters = cfg.get("filters", {})
    out = cfg.get("output", {})
    out_dir = ROOT / out.get("dir", "output")
    out_dir.mkdir(exist_ok=True)

    store = Store(out_dir / out.get("database", "jobs.db"))
    first_run = not store.all_jobs()

    new_jobs, failed = [], 0
    for source in cfg.get("sources", []):
        name = source.get("name", source.get("type"))
        try:
            fetched = fetch_source(source)
        except Exception as e:  # one broken source shouldn't stop the others
            print(f"[!] {name}: failed to fetch ({e})", file=sys.stderr)
            failed += 1
            continue
        added = store.upsert(fetched)
        print(f"{name}: {len(fetched)} fetched, {len(added)} new")
        new_jobs += added

    source_order = [s.get("name", s.get("type")) for s in cfg.get("sources", [])]
    stored = store.all_jobs()
    store.close()
    new_ids = {j.id for j in new_jobs}
    matching = merge([(j, seen) for j, seen in stored if matches(j, filters)], new_ids, source_order)

    # Sort every listing into best / unknown / drop by work authorization.
    auth_cfg = cfg.get("work_auth", {})
    try:
        h1b = H1BData(ROOT / "data", auth_cfg.get("h1b_years", []))
    except Exception as e:
        print(f"[!] H-1B sponsor data unavailable ({e}); skipping that signal", file=sys.stderr)
        h1b = None
    buckets = {"best": [], "unknown": [], "drop": []}
    for item in matching:
        bucket, note = assess(item.job, h1b, auth_cfg)
        buckets[bucket].append((item, note))

    new_count = sum(item.is_new for bucket in ("best", "unknown") for item, _ in buckets[bucket])
    total = len(buckets["best"]) + len(buckets["unknown"])
    label = "matching jobs (first run, so everything is new)" if first_run else "NEW matching jobs"
    print(f"\n{new_count} {label}  |  {total} matching in total (duplicates merged)")
    print(f"  {len(buckets['best'])} best fit, {len(buckets['unknown'])} sponsorship unknown, "
          f"{len(buckets['drop'])} dropped as US-citizens-only")
    shown = None if args.all else PREVIEW_ROWS
    for bucket, heading in (("best", "BEST FIT"), ("unknown", "SPONSORSHIP UNKNOWN")):
        new_items = [(item, note) for item, note in buckets[bucket] if item.is_new]
        if new_items:
            print(f"\n  -- {heading} ({len(new_items)} new) --")
        if shown is not None and len(new_items) > shown:
            hidden = len(new_items) - shown
            new_items = new_items[:shown]
        else:
            hidden = 0
        for item, note in new_items:
            job = item.job
            where = job.location[:40] + (" [remote]" if job.remote else "")
            print(f"  {job.posted_on}  {job.company[:25]:<25}  {job.title[:55]:<55}  {where:<45}  {note}")
        if hidden:
            print(f"  ... and {hidden} more (see the Excel file, or run with --all)")

    excel_path = out_dir / out.get("excel", "jobs.xlsx")
    try:
        write_excel(excel_path, {"Best Fit": buckets["best"], "Sponsorship Unknown": buckets["unknown"]})
        print(f"\nExcel: {excel_path}")
    except PermissionError:
        print(f"\n[!] Could not write {excel_path} - close it in Excel and run again.", file=sys.stderr)
        return 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
