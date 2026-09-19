# JobRanker

Local AI-powered job ranking and application workflow tool.

JobRanker helps you collect job postings directly from your browser, extract structured information using AI, rank opportunities against your interests, and manage your application workflow locally.

> [!WARNING]
> JobRanker is designed for local use only. Keep the backend bound to
> `127.0.0.1` and do not expose it directly to the internet. Report data and
> other read-only endpoints are not authenticated, and the dashboard receives
> the API token needed for workflow updates.

![JobRanker Screenshot](jobranker.jpg)

---

# Features

- Browser extension for capturing job postings
- AI-powered job extraction and ranking
- Local-first SQLite architecture
- Searchable, paginated web dashboard
- Application workflow tracking
- Resume profile support
- SQLite-backed background processing queue
- AI token and cost tracking
- Simple setup with shell scripts

---

# Architecture

```text
Browser Extension
        ↓
FastAPI Capture API
        ↓
SQLite jobs, artifacts, and queue
        ↓
AI Extraction + Ranking Worker
        ↓
SQLite rankings and workflow state
        ↓
API-driven Web Report
```

FastAPI and the worker share `data/jobranker.db`. The browser extension
captures the active page, the worker processes pending queue entries, and the
report loads job summaries and details from the API.

---

# Requirements

- Python 3.11+
- Node.js + npm
- OpenAI API key
- Linux or macOS

---

# Setup

Clone repository:

```bash
git clone https://github.com/vesapehkonen/jobranker.git
cd jobranker
```

Run setup:

```bash
./setup.sh
```

The setup script will:

- Create Python virtual environment
- Install Python dependencies
- Install and build browser extension
- Create `.env`
- Generate API token

Edit `.env` and add your OpenAI API key:

```env
OPENAI_API_KEY=your-api-key
OPENAI_JOB_EXTRACT_MODEL=gpt-5.4-nano
OPENAI_JOB_RANK_MODEL=gpt-5.4-mini
OPENAI_RESUME_EXTRACT_MODEL=gpt-5.4-mini
```

`setup.sh` generates `API_TOKEN` automatically. The API and browser extension
use it to authorize capture and workflow updates.

---

## Add Resume Profile

Resume profiles are stored in SQLite and used for AI-powered job ranking. Source resumes must be in text format (`.txt` or `.md`).

Add a resume profile using:

```bash
source .venv/bin/activate
set -a
source .env
set +a
python extract_resume_ai.py <profile-name> <resume-file>
```

This extracts the structured profile and stores both it and the resume text in `data/jobranker.db`.

After each successful extraction, the command refreshes a separate merged base
profile from **all stored resume profiles**, including disabled profiles. The base
is a broad inventory of the candidate's qualifications; enabled profiles still
control which resumes participate in job ranking. The base is not a selectable
resume. Local job filtering uses it before AI extraction and resume ranking.

With one resume, its extracted profile is copied without an additional AI call.
With multiple resumes, the merge uses `RESUME_EXTRACT_MODEL` to combine supported
qualifications, deduplicate employment and education, and avoid double-counting
overlapping experience. Each merged field or list item records its supporting
resume names. Source content hashes, merge time, model, and status are stored
with the base. Merge token usage is recorded as `resume_merge` in AI costs.
Unchanged source profiles skip the merge. As with resume extraction, merged
claims and experience totals are AI-generated and should be reviewed.

Build the base for existing profiles, retry a failed merge, or inspect the result:

```bash
python merge_resume_profiles.py
```

Use `--force` to regenerate an unchanged base or `--database <path>` to select a
different SQLite database. To delete a resume profile and its associated ranking
records, then refresh the base:

```bash
python merge_resume_profiles.py --delete-profile <profile-name>
```

Profile inserts, content changes, and deletions immediately mark the base stale.
If merging fails, the saved resume and previous base remain available, but the
base stays stale and the command exits with an error. `load_base_profile()` hides
stale results unless `allow_stale=True` is explicitly requested for inspection.
Direct database changes require running the merge command afterward. Deleting
the last resume clears the base.


## Local job filtering

The worker cleans each captured description, then uses the shared deterministic
extractors in `job_matching/` before making any job-related AI calls. The scripts
in `experiments/structured_matching/` import these same extraction and comparison
functions. Build a current base profile with `python merge_resume_profiles.py`
before processing jobs; missing or stale bases fail the queue item, as do local
extraction errors. Use Retry after fixing the cause.

The local filter applies these rules:

- Missing or invalid descriptions are filtered out with validation reasons.
- A clearly required education level above the base profile's level filters out
  the job. Preferred degrees and recognized equivalent-experience alternatives
  do not cause rejection. Unknown profile education skips this check.
- Required experience above 1.15 times the base profile's experience filters out
  the job. Equality passes; unknown profile experience skips this check.
- Fewer than three distinct recognized technologies skips the technology check
  only. It does not override an education or experience rejection.
- For three or more technologies, less than 15% coverage filters out the job.
  Coverage is matched distinct technologies divided by JD distinct technologies;
  the decision uses unrounded counts. Exactly 15% passes.

Capabilities are extracted and compared for inspection but are not a rejection
rule. Qualification mentions classified as unspecified do not cause rejection.
Technology mentions include optional tools, so this remains a heuristic filter.

Each decision is appended to `local_filter_evaluations`, with reasons, supporting
extraction contexts, comparison values, thresholds, rule/extractor versions, base
source hashes and merge time, description hash, and evaluation time. Application
status is preserved. Filtered jobs finish their queue work without AI extraction
or ranking. Filtered jobs are hidden by default; enable **Show filtered jobs**
to review them. The toggle is remembered in this browser and applies independently
of application status. Failed jobs remain visible. Open job details to see a short
rejection reason; evidence is under the collapsed **Processing details** section. **Recheck** queues a new evaluation using the current
base and rules; earlier evaluations remain stored. Passing jobs continue through AI extraction and the base-profile ranking gate
below before ranking against enabled resumes.


## AI base-profile ranking gate

After AI extraction is saved, the same queue item enters `base_rank`. The existing
single-profile AI ranker compares the extracted job against the merged base,
using `JOB_RANK_MODEL` and the existing weighted dimension score (rounded to an
integer). Scores **below 75** are filtered out; **75 or above** continues to the
existing batch ranking against enabled resume profiles.

`base_rank_evaluations` stores the score, threshold, full explanation and dimension
scores, model, base version, input hashes, timestamp, and outcome for each
attempt that reaches a valid decision. Filtered jobs finish with queue phase
`base_filtered`, preserving their application status and extracted job data.
The report keeps base scores and diagnostics in **Processing details** at the
bottom of job details. Successful processing badges are omitted from the job list.
The detail header shows estimated per-job AI cost across all recorded calls,
including retries. If any calls lack pricing, it shows tokens instead; the known
partial cost and call breakdown are available in Processing details. Jobs with
no recorded calls are labeled accordingly, rather than assigned an assumed cost.
Recheck is available for jobs filtered by either stage. API failures, invalid
scores, and missing/stale bases fail the queue item and can be retried. A base
that changes during ranking prevents the outdated result from being published.

Retries and rechecks reuse successful AI extraction when the cleaned input,
prompt, extraction schema, model and extraction version match. They reuse base
ranking when the structured job, base content/version, ranking schema, weights,
model and ranking version match. Rechecking unchanged inputs therefore keeps the
same score without another base-ranking call. A changed threshold is applied to
the cached score. Legacy extractions without a recorded cache key are regenerated
once. Cache rows and evaluations are deleted with their job.

AI usage for this extra ranking call is recorded separately as `base_rank`.
This gate saves the final resume-ranking call only for jobs it rejects; passing
jobs incur an additional AI call. Resume rankings themselves retain their current
retry behavior. These changes apply to newly queued or explicitly retried jobs,
not automatically to previously completed jobs.

---

# Start

Run:

```bash
./start.sh
```

This will:

- Start FastAPI server
- Start worker process
- Initialize or upgrade the SQLite schema
- Open dashboard automatically

Dashboard URL:

```text
http://127.0.0.1:8000/report
```

Jobs received by email can be added from the dashboard with **Add job manually**.
Paste the description and optionally include the title, company, recruiter details,
notes, and an application URL. A URL is not required and can be added later from
the job details drawer.

## Experiment capture mode

Set `EXPERIMENT_CAPTURE=1` before starting JobRanker to store new browser and
manual captures with the `experiment` status while still processing them through
the normal worker:

```bash
export EXPERIMENT_CAPTURE=1
./start.sh
```

Unset it and restart JobRanker to return new captures to the normal `new` status:

```bash
unset EXPERIMENT_CAPTURE
./start.sh
```

This mode does not change enabled resume profiles. Manage those separately before
and after a controlled experiment collection period.

---

# Browser Extension Setup

After running `setup.sh`:

1. Open browser extensions page
2. Enable Developer Mode
3. Click **Load unpacked**
4. Select the `extension` directory

When capturing the first job posting, the extension will ask for the API token.

Copy `API_TOKEN` from `.env` and paste it into the extension prompt.

You can now capture a job posting from the active browser page.

---

# Development

## Build Browser Extension

```bash
cd extension
npm install
npx tsc
```

## Backend

```bash
source .venv/bin/activate
set -a
source .env
set +a
uvicorn app:app --reload
```

## Worker

```bash
source .venv/bin/activate
set -a
source .env
set +a
python worker.py
```

## Tests

```bash
.venv/bin/python -m unittest discover -v
```

## AI Usage Report

```bash
.venv/bin/python ai_cost_report.py
```

This prints recorded OpenAI calls, token usage, and estimated costs from
SQLite.

---

# Project Structure

```text
jobranker/
├── app.py
├── database.py
├── worker.py
├── report_data.py
├── extract_job_ai.py
├── extract_resume_ai.py
├── rank_job_ai.py
├── migrations/
├── templates/
│   └── jobs_report.html
├── static/
│   ├── jobs-report.css
│   └── jobs-report.js
├── extension/
│   ├── src/
│   ├── dist/
│   └── manifest.json
├── tests/
├── data/
│   └── jobranker.db
├── setup.sh
├── start.sh
└── requirements.txt
```

---

# Security Notes

- Capture and workflow mutation endpoints use a bearer token
- Some report and read-only endpoints are currently unauthenticated
- Backend binds to localhost by default
- No cloud storage
- Job data and resume profiles stay in local SQLite storage
- Resume and job content is sent to OpenAI for extraction and ranking

---

# Future Ideas

- Better recommendation engine
- Resume tailoring
- Cover letter generation
- Company memory/history
- Better duplicate detection
- Docker support
- Optional PostgreSQL backend

---

# License

JobRanker is available under the [MIT License](LICENSE).
