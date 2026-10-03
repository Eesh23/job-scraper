# Job Scraper

A local tool for new-grad job hunting. It has two parts:

- **`run.py`** collects entry-level tech jobs from eight job lists, merges duplicates, filters
  them to North America, sorts them by visa/work-authorization fit, and writes a spreadsheet
  that highlights what's new since your last run.
- **`tailor.py`** takes job links you choose and produces a one-page PDF resume tailored to
  each one. It uses Claude through your Claude subscription, and code checks every rewrite
  against your real resume so nothing gets invented.

Everything runs on your machine. The only setup is Python. Tailoring also needs a Claude plan.

---

## Contents

- [Quick start](#quick-start)
- [Finding jobs: `run.py`](#finding-jobs-runpy)
  - [Sources](#sources)
  - [Filtering](#filtering)
  - [Duplicates](#duplicates)
  - [Work authorization](#work-authorization)
  - [Output](#output)
- [Tailoring resumes: `tailor.py`](#tailoring-resumes-tailorpy)
  - [Setup](#setup)
  - [Usage](#usage)
  - [How it keeps resumes honest](#how-it-keeps-resumes-honest)
  - [One-page PDF](#one-page-pdf)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Adding a job source](#adding-a-job-source)
- [Privacy](#privacy)
- [Limitations](#limitations)
- [Credits](#credits)

---

## Quick start

Requires Python 3.11+.

```bash
git clone <this repo> job-scraper
cd job-scraper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python run.py          # collect jobs -> output/jobs.xlsx
```

Run it as often as you like, for example every morning. Each run reports only the jobs it
hasn't seen before.

---

## Finding jobs: `run.py`

```bash
.venv/bin/python run.py          # fetch, filter, write the spreadsheet
.venv/bin/python run.py --all    # also print every new job, not just the first 25
```

### Sources

| Source | Type | What it reads |
|---|---|---|
| [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) | `simplify` | The repo's `listings.json`: direct employer links, filtered by category (Software, AI/ML/Data, Product). |
| [ricsign/Ricsign-New-Grads-Jobs-2027](https://github.com/ricsign/Ricsign-New-Grads-Jobs-2027) | `ricsign` | `data/v1/jobs.json`, new-grad SWE track. |
| [ApplyGuy/2027-New-Grad-Jobs](https://github.com/ApplyGuy/2027-New-Grad-Jobs) | `applyguy` | `data/new-grad-jobs.json`, using the employer's own posting link. |
| [Donkey0322/JobRadar-AI](https://github.com/Donkey0322/JobRadar-AI) | `jobradar` | The entry-level board's HTML table. |
| [speedyapply/2027-SWE-College-Jobs](https://github.com/speedyapply/2027-SWE-College-Jobs) | `speedyapply` | The USA and international new-grad markdown tables. |
| [Y Combinator Jobs](https://www.ycombinator.com/jobs) | `yc` | Startup engineering and product roles whose employer marked them "new grads ok". |
| [HN "Who is hiring?"](https://news.ycombinator.com/submitted?id=whoishiring) | `hackernews` | The latest monthly thread, via the official HN Algolia API; keeps posts that mention new-grad, junior or entry-level hiring. |
| [Hirly-Me/New-Grad-Software-Engineer-Jobs](https://github.com/Hirly-Me/New-Grad-Software-Engineer-Jobs) | `hirly` | The public JSON feed the repo is built from (newest 250 jobs). |

Sources are read through their public data files or APIs where possible, rather than by
scraping web pages. If one source fails, the rest still run.

### Filtering

Configured in `[filters]` in `config.toml`:

- **Location:** `countries = ["US", "CA"]` by default. Most lists only give free-text
  locations ("Toronto, ON", "NYC", "Remote in USA"), so `geo.py` works out the country from
  states, provinces, major cities and country names.
- **Entry level only:** titles with *senior, staff, principal, lead, director, intern,
  Engineer II/III* and similar words are dropped. A title that explicitly says *new grad,
  junior* or *entry level* is always kept, even if it contains one of those words.
- **Tech and product roles only:** a title must contain a tech/product word (*engineer,
  developer, data, product, architect, analyst...*). This catches mislabeled listings; some
  lists file "Housekeeper" under Software.
- **Recent only:** `max_age_days = 30`.

All keyword matching is whole-word, so "intern" doesn't match "Internal Tools Engineer".

### Duplicates

The same job often shows up on several lists. Two listings are merged into one row when
either:

- their **apply links point to the same posting**, ignoring tracking parameters, `/apply`
  suffixes, locale segments and Greenhouse jobs embedded on company sites; or
- their **company and title match after normalization**: "Software Engineer I" equals
  "Software Engineer 1", "Jr." equals "Junior", "(Hybrid)" and "2027" are ignored, and
  "Anduril Industries" equals "Anduril".

The merged row keeps the link from the source listed first in `config.toml`, so put sources
with direct employer links first. The **Sources** column shows every list the job came from.

### Work authorization

Built for a Canadian open to working in the US, and configurable in `[work_auth]`:

| Sheet | What goes there |
|---|---|
| **Best Fit** | Jobs in Canada; postings that say they sponsor visas; employers with 10+ H-1B approvals in the [USCIS H-1B Employer Data Hub](https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub) (FY2022–23). |
| **Sponsorship Unknown** | Every other US job. Most postings never mention sponsorship. |
| *(dropped)* | Postings that explicitly require US citizenship or a security clearance. |

Signals come from the job lists themselves (SimplifyJobs, ricsign, JobRadar and YC all mark
some jobs), from the title ("TS/SCI", "US Citizenship Required"), and from the USCIS employer
data. The **Work Auth** column explains why each job is in its sheet.

> Canadians can often work in the US on TN status, which doesn't require H-1B sponsorship,
> so "Sponsorship Unknown" jobs are still worth a look. This is not legal advice.

### Output

| File | Contents |
|---|---|
| `output/jobs.xlsx` | **Best Fit** and **Sponsorship Unknown** sheets. New jobs are highlighted and listed first. Columns: posted date, company, role, location, remote, work-auth note, sources, link. |
| `output/jobs.db` | SQLite history of every job ever fetched, filtered or not, with first-seen and last-seen times. Changing filters later works on the full history. |
| `data/h1b_*.csv` | USCIS employer data, downloaded automatically on the first run. |

Close `jobs.xlsx` before running, because it's rewritten each time.

---

## Tailoring resumes: `tailor.py`

A separate command that makes a custom resume **only for the job links you give it**.

It calls Claude through the **Claude Code CLI** (`claude -p`), which uses your Claude
subscription (Pro or Max) instead of the pay-per-use API. If the CLI is signed in with an API
key, the tool refuses to run, so you can't be billed by accident.

### Setup

```bash
# 1. Install the Claude Code CLI and sign in with your Claude account
curl -fsSL https://claude.ai/install.sh | bash
~/.local/bin/claude auth login

# 2. Put your resume (PDF or DOCX) in resume/, then convert it to a master resume
.venv/bin/python tailor.py --import

# 3. Check the result
.venv/bin/python tailor.py --render-master    # writes resume/master_resume.pdf
```

`--import` copies your resume word-for-word into `resume/master_resume.yaml`. See
[`master_resume.example.yaml`](master_resume.example.yaml) for the format.

**Add more than fits on one page:** extra bullets, projects and coursework. Tailoring picks
the most relevant ones for each job, so a bigger master gives better results.

### Usage

```bash
.venv/bin/python tailor.py "https://jobs.lever.co/company/1234..."
.venv/bin/python tailor.py <link> <link> <link>                       # several at once
.venv/bin/python tailor.py --jd-file job.txt --company Acme --title "Software Engineer"
.venv/bin/python tailor.py --dry-run <link>                           # fetch + build the prompt, no Claude call
```

Each job gets a folder: `tailored/<date>-<company>-<title>/`

| File | Contents |
|---|---|
| `resume.pdf` | The tailored resume. Always one page. |
| `resume.docx` | An editable copy with the same content. |
| `changes.md` | What changed and why, an honest fit assessment, keywords the job wants that your resume doesn't show, and anything the checker reverted or trimmed. |
| `job_description.txt` | The job description it was tailored against. |

**Reading job descriptions:** descriptions are fetched from each job platform's public data
(Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Oracle Recruiting Cloud). For
other sites, the tool falls back to the schema.org `JobPosting` data most career pages embed
for Google. If a link can't be read, paste the description into a text file and use
`--jd-file`.

### How it keeps resumes honest

Claude can **choose, reorder and reword** material from your master resume. It can't add
anything new. This is enforced two ways.

**1. How Claude runs.** Claude runs with every tool disabled and must answer in a fixed JSON
format, in which each bullet names the original bullet it came from.

**2. What `jobscraper/tailor/guard.py` checks.** Every rewrite is verified in code, and
anything that fails goes back to your original wording:

- **New numbers:** "35%" can't become "50%".
- **New technologies or names:** if it isn't anywhere in your master, it can't be added. For
  example, Docker can't turn into "Docker and Kubernetes".
- **Inflated roles:** "Helped migrate" can't become "Led migration".
- **Mixed-up sources:** a bullet must come from the same job it appears under.
- **Unknown skills:** skills you don't list are removed.

Every job you've held always stays on the page, in date order. All reverts are listed in
`changes.md`.

> The checker catches invented facts, not subtle exaggeration made from words already in
> your resume. Read `changes.md` before you submit anything.

### One-page PDF

After tailoring, the resume is laid out and the pages are counted. If it runs over one page:

1. **Tighten:** text shrinks in small steps, never below 9.5 pt, along with line spacing and
   margins.
2. **Trim:** if it still doesn't fit, the least relevant bullet is dropped, one at a time.
   Leadership goes first, then projects, then experience. Each job keeps at least two bullets.

Everything trimmed is listed in `changes.md`.

---

## Configuration

Everything lives in [`config.toml`](config.toml):

| Section | What it controls |
|---|---|
| `[[sources]]` | Job lists to read, in priority order. Remove a block to disable a source. |
| `[filters]` | Countries, maximum posting age, excluded and required title keywords. |
| `[work_auth]` | USCIS data years, the "known sponsor" threshold, whether to drop clearance jobs. |
| `[output]` | Where the database and spreadsheet go. |
| `[tailor]` | Resume folder, tailoring output folder, Claude model, bullet and project limits. |

---

## Project layout

```
run.py                     collect jobs -> spreadsheet
tailor.py                  tailor a resume for given job links
config.toml                all settings
master_resume.example.yaml master resume format (fictional person)

jobscraper/
  sources/                 one module per job list
  models.py                Job dataclass shared by every source
  geo.py                   free-text location -> country
  filters.py               location, seniority, role and age filters
  dedupe.py                merge the same job across sources
  workauth.py              citizenship / sponsorship / H-1B sorting
  storage.py               SQLite history and new-job detection
  export.py                Excel writer
  jd.py                    fetch full job descriptions from a link
  http.py                  shared HTTP helpers
  tailor/
    master.py              load and read the master resume
    prompts.py             Claude prompts and JSON schemas
    claude_cli.py          run Claude via the Claude Code CLI
    guard.py               verify rewrites against the master resume
    render.py              .docx output
    render_pdf.py          PDF output and one-page fitting

resume/      (git-ignored) your resume and master_resume.yaml
tailored/    (git-ignored) tailored resumes
output/      (git-ignored) job database and spreadsheet
data/        (git-ignored) downloaded USCIS data
```

---

## Adding a job source

1. Create `jobscraper/sources/<name>.py` with a `fetch(cfg: dict) -> list[Job]` function.
   Give each job a stable `id` (`"<name>:<source's own id>"`), and use `geo.resolve()` for
   the country.
2. Register it in `jobscraper/sources/__init__.py`.
3. Add a `[[sources]]` block with `type = "<name>"` to `config.toml`.

Filtering, deduplication, work-authorization sorting and the spreadsheet then apply
automatically.

---

## Privacy

- **Personal data stays out of git.** `.gitignore` excludes your resume, master resume,
  tailored resumes, job database and spreadsheet. Check `git status` before committing.
- **No API keys.** The project doesn't use any. The Claude Code login is stored outside the
  project, in `~/.claude`.
- **What leaves your machine:** `tailor.py` sends your master resume and the job description
  to Claude to produce each tailored resume. `run.py` sends nothing personal; it only
  downloads public job lists.

---

## Limitations

- **Job lists change format.** If a list changes its layout, its reader may need an update;
  the other sources keep working.
- **Hirly's feed** only holds its newest 250 jobs (about 12 days), so run at least weekly.
- **Location detection** is best-effort for free-text locations.
- **H-1B matching** is by company name, so some sponsors are missed and a few generic names
  can match the wrong employer.
- **"New grads ok" on YC** is set by the employer, and some apply it broadly.
- **Some career sites can't be read** automatically, and closed postings can't be fetched.
  Use `--jd-file` for these.
- **The `.docx` copy** may lay out slightly differently in Word. The PDF is the one
  guaranteed to fit one page.

---

## Credits

Job data comes from the maintainers of the lists above:
[SimplifyJobs](https://github.com/SimplifyJobs/New-Grad-Positions),
[ricsign](https://github.com/ricsign/Ricsign-New-Grads-Jobs-2027),
[ApplyGuy](https://github.com/ApplyGuy/2027-New-Grad-Jobs),
[JobRadar-AI](https://github.com/Donkey0322/JobRadar-AI),
[speedyapply](https://github.com/speedyapply/2027-SWE-College-Jobs),
[Hirly](https://github.com/Hirly-Me/New-Grad-Software-Engineer-Jobs),
[Y Combinator](https://www.ycombinator.com/jobs) and
[Hacker News](https://news.ycombinator.com/). Visa sponsorship data comes from the
[USCIS H-1B Employer Data Hub](https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub).
Job postings belong to the employers who published them.

This is a personal tool for your own job search. Please respect each source's terms, and
don't use it to republish their data.
