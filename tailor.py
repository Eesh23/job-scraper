"""Make a custom resume for each job link you give it, using Claude through your
Claude plan (the Claude Code CLI) - no API charges.

Usage:
    .venv/bin/python tailor.py --import                               # once: build resume/master_resume.yaml
                                                                      #   from the PDF/DOCX in resume/
    .venv/bin/python tailor.py --render-master                        # preview the master as .docx
    .venv/bin/python tailor.py <job link> [<job link> ...]            # tailor for each job
    .venv/bin/python tailor.py --jd-file job.txt --company Acme --title "Software Engineer"
    .venv/bin/python tailor.py --dry-run <job link>                   # fetch + build prompt, no Claude call

Each job gets a folder in tailored/ with resume.pdf (always one page),
resume.docx (editable copy), changes.md (what changed, what was reverted,
keywords you're missing) and the job description.
"""

import argparse
import json
import re
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path

import yaml

from jobscraper import jd as jd_mod
from jobscraper.tailor import claude_cli, guard, prompts, render, render_pdf
from jobscraper.tailor import master as master_mod

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("links", nargs="*", help="job posting URLs")
    parser.add_argument("--import", dest="import_path", nargs="?", const="", metavar="FILE",
                        help="convert your resume (PDF/DOCX/TXT) into the master; defaults to the one in resume/")
    parser.add_argument("--render-master", action="store_true", help="write the full master resume as a .docx to check it")
    parser.add_argument("--jd-file", type=Path, help="job description text file, for links that can't be read")
    parser.add_argument("--company", default="", help="company name (with --jd-file)")
    parser.add_argument("--title", default="", help="job title (with --jd-file)")
    parser.add_argument("--dry-run", action="store_true", help="fetch the job and write the prompt, without calling Claude")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    args = parser.parse_args()

    cfg = tomllib.loads(args.config.read_text()).get("tailor", {})
    resume_dir = _project_path(cfg.get("resume_dir", "resume"))
    master_path = _project_path(cfg.get("master", "resume/master_resume.yaml"))
    out_root = _project_path(cfg.get("output_dir", "tailored"))
    limits = {k: cfg.get(k, d) for k, d in (("max_bullets_per_role", 4), ("max_projects", 3),
                                            ("max_bullets_per_project", 3), ("max_leadership", 2))}
    model = cfg.get("model") or None

    try:
        if args.import_path is not None:
            source = _project_path(args.import_path) if args.import_path else _find_resume(resume_dir)
            if not source:
                print(f"No resume found. Put your resume PDF or DOCX in {resume_dir}/ "
                      f"or pass a path: --import <file>", file=sys.stderr)
                return 1
            return import_resume(source, master_path, model)
        if not master_path.exists():
            print(f"No master resume at {master_path}.\nPut your resume PDF/DOCX in {resume_dir}/ and create the master with:\n"
                  f"    .venv/bin/python tailor.py --import", file=sys.stderr)
            return 1
        master = master_mod.load(master_path)
        if args.render_master:
            # The master can run past one page on purpose; tailored resumes are fitted.
            render.render(master, master_path.with_suffix(".docx"))
            render_pdf.write(master, master_path.with_suffix(".pdf"))
            pages = render_pdf.page_count(master, None, render_pdf.Layout())
            print(f"Master resume preview: {master_path.with_suffix('.pdf')} ({pages} page{'s' * (pages > 1)})")
            return 0

        jobs = []
        if args.jd_file:
            jobs.append(jd_mod.JobDescription(str(args.jd_file), args.title, args.company, "",
                                              args.jd_file.read_text(), "file"))
        for link in args.links:
            if not link.startswith(("http://", "https://")):
                print(f"[!] {link!r} isn't a link - paste the job posting's full URL (starting with https://)",
                      file=sys.stderr)
                continue
            try:
                jobs.append(jd_mod.fetch(link))
            except jd_mod.FetchError as e:
                print(f"[!] {link}\n    {e}\n    Save the description to a file and use --jd-file instead.", file=sys.stderr)
        if not jobs:
            parser.print_help()
            return 1

        if not args.dry_run:
            claude_cli.check_ready()
        failed = 0
        for job in jobs:
            try:
                tailor_one(job, master, out_root, limits, model, args.dry_run)
            except claude_cli.ClaudeError as e:
                print(f"[!] {job.company or job.url}: {e}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0
    except claude_cli.ClaudeError as e:
        print(e, file=sys.stderr)
        return 1


def tailor_one(job, master, out_root, limits, model, dry_run):
    label = f"{job.company} - {job.title}".strip(" -") or job.url
    folder = out_root / _slug(f"{date.today()}-{job.company}-{job.title}")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "job_description.txt").write_text(
        f"{job.title}\n{job.company}\n{job.location}\n{job.url}\n(read via {job.method})\n\n{job.text}")

    master_yaml = yaml.safe_dump(master, sort_keys=False, allow_unicode=True, width=100)
    prompt = prompts.tailor_prompt(master_yaml, job.title, job.company, job.text, limits)
    if dry_run:
        (folder / "prompt.txt").write_text(prompt)
        print(f"{label}: job description read via {job.method} ({len(job.text):,} chars); prompt saved to {folder}/prompt.txt")
        return

    print(f"{label}: asking Claude (this takes a minute)...")
    tailored = _ask(prompt, prompts.TAILOR_SYSTEM, prompts.TAILOR_SCHEMA, model)
    cleaned, fixes = guard.check(master, tailored, limits)
    fitted, layout, fit_notes, pages = render_pdf.fit_one_page(master, cleaned)

    (folder / "tailored.json").write_text(json.dumps(fitted, indent=2))
    render_pdf.write(master, folder / "resume.pdf", fitted, layout)
    render.render(master, folder / "resume.docx", fitted, font_size=layout.font_size, margin=layout.margin)
    (folder / "changes.md").write_text(_report(job, fitted, fixes, fit_notes))
    print(f"  -> {folder}/resume.pdf  ({pages} page{'s' * (pages > 1)})"
          + (f"  ({len(fixes)} change(s) reverted or fixed - see changes.md)" if fixes else ""))
    if pages > 1:
        print("  [!] Still over one page even after trimming - cut material in master_resume.yaml", file=sys.stderr)


def import_resume(path: Path, master_path: Path, model) -> int:
    claude_cli.check_ready()
    text = master_mod.read_resume_file(path)
    if len(text.strip()) < 200:
        print(f"Couldn't read much text from {path} (is it a scanned image?). Try exporting it as DOCX.", file=sys.stderr)
        return 1
    print(f"Converting {path.name} into a master resume (one Claude call)...")
    data = _ask(prompts.import_prompt(text), prompts.IMPORT_SYSTEM, prompts.IMPORT_SCHEMA, model)

    target = master_path if not master_path.exists() else master_path.with_name(master_path.stem + ".imported.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    master_mod.save(data, target)
    print(f"Saved {target}\n"
          "Next: open it and check it matches your resume. Add any extra bullets or projects that\n"
          "didn't fit on the page - tailoring picks the best ones per job. Then preview it with:\n"
          "    .venv/bin/python tailor.py --render-master")
    if target != master_path:
        print(f"(Your existing {master_path.name} was left untouched.)")
    return 0


def _project_path(value: str) -> Path:
    """Config/CLI paths are relative to this project unless absolute or ~."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


def _find_resume(folder: Path) -> Path | None:
    """The most recently modified PDF/DOCX in the resume folder."""
    if not folder.is_dir():
        return None
    # Skip Word lock files and the --render-master preview (master_resume.docx).
    files = [p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".docx")
             and not p.name.startswith("~$") and not p.stem.startswith("master_resume")]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def _ask(prompt, system_text, schema, model):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(system_text)
    try:
        return claude_cli.ask(prompt, Path(f.name), schema, model)
    finally:
        Path(f.name).unlink(missing_ok=True)


def _report(job, tailored, fixes, fit_notes=()) -> str:
    lines = [f"# {job.title} - {job.company}", "", job.url, "", "## Fit", "", tailored.get("fit_notes", ""), "",
             "## What changed", ""]
    lines += [f"- {c}" for c in tailored.get("changes", [])] or ["- (nothing reported)"]
    lines += ["", "## Keywords the job wants that your master resume doesn't show", "",
              "Only add these if you genuinely have the experience:", ""]
    lines += [f"- {k}" for k in tailored.get("missing_keywords", [])] or ["- (none)"]
    if fixes:
        lines += ["", "## Automatic fixes (Claude's version couldn't be verified against your master)", ""]
        lines += [f"- {f}" for f in fixes]
    if fit_notes:
        lines += ["", "## Fitting to one page", ""]
        lines += [f"- {n}" for n in fit_notes]
    return "\n".join(lines) + "\n"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


if __name__ == "__main__":
    sys.exit(main())
