# Deterministic Python extraction experiment

The reusable extractors and comparison logic live in `job_matching/`. The
experiment modules re-export those functions so experiment commands and the
production local filter use the same implementation. Production filtering applies
its own documented rejection rules; experiment comparisons retain their existing
reporting behavior.

This phase extracts technologies, engineering capabilities, education
requirements, and minimum experience years using Python only. It does not load
or call an LLM, embedding model, Ollama, or `sentence-transformers`.

## Extract a local resume profile

Create a deterministic comparison profile from the original resume text stored
in SQLite:

```bash
python -m experiments.structured_matching.extract_profile --profile backend
```

The command reads only `profiles.resume_text`; it does not read the AI-generated
`profile_json` and does not change the database. By default it prints the JSON
and writes it to
`/tmp/jobranker-structured-matching/profiles/backend.local.json`. Use `--output`
to select another file and `--as-of YYYY-MM` to make ongoing employment-duration
calculations reproducible.

## Compare a job with the local profile

After extracting a job and local resume profile, compare their technologies,
experience, and education:

```bash
python -m experiments.structured_matching.compare_profile \
  --job /tmp/jobranker-structured-matching/jobs/<job_uid>.local.json \
  --profile /tmp/jobranker-structured-matching/profiles/backend.local.json
```

The result is printed and written by default to
`/tmp/jobranker-structured-matching/comparisons/`. Technology coverage is the
fraction of job technologies present in the profile. A job with no extracted
technologies has coverage `1.0`; absent education and experience requirements
are treated as met. Use `--output` to select an explicit output file.

## Run the complete local comparison

Generate the profile, job extraction, and comparison for one database job:

```bash
python -m experiments.structured_matching.run_local_comparison <job_uid>
```

The default output directory is
`/tmp/jobranker-structured-matching/results/<job_uid>/`, containing:

```text
backend.local.json
<job_uid>.cleaned.txt
<job_uid>.local.json
<job_uid>.comparison.json
selected_job_uids.json
```

Or select a batch by application state and optionally limit its size:

```bash
python -m experiments.structured_matching.run_local_comparison \
  --state experiment \
  --limit 10 \
  --output /tmp/jobranker-experiment-results
```

The batch creates `backend.local.json` once, followed by
`<job_uid>.cleaned.txt`, `<job_uid>.local.json`, and
`<job_uid>.comparison.json` for every selected job in the same directory. It
also writes `selected_job_uids.json`. `--status` is accepted as an alias for
`--state`.

## Compare technology and capability coverage with AI scores

Run the deterministic matching experiment for jobs selected by state:

```bash
python -m experiments.structured_matching.evaluate_technology \
  --state experiment \
  --limit 100
```

Omit `--state` to evaluate cleaned jobs from every application state. `--limit`
then applies to the complete ordered job set:

```bash
python -m experiments.structured_matching.evaluate_technology --limit 100
```

It runs the local extraction/comparison pipeline and joins each result with the
selected profile's existing AI score from `profile_rankings`. The output
directory retains `backend.local.json`, every `<job_uid>.cleaned.txt`,
`<job_uid>.local.json`, and `<job_uid>.comparison.json`, as well as
`technology_vs_ai.csv` and `technology_vs_ai_summary.json`. The current run's
job UIDs are recorded in `selected_job_uids.json`, so older retained artifacts
are not included in a later limited evaluation. The CSV and summary report
technology and capability coverage separately, including separate confidence,
Spearman correlation, and low-coverage/high-AI counts. Input quality is checked
before any field extraction. Clearly invalid
captures are retained with `comparison_status: invalid_job_description`, but
technology, capability, experience, and education comparison is skipped. For
valid jobs, confidence is `unknown` for zero matches, `low` for one or two, and
`high` for three or more. Each correlation includes only valid,
high-confidence jobs for that dimension.

Use `--output <directory>` to choose another destination, `--profile` to select
a different resume, and `--as-of YYYY-MM` for reproducible ongoing-employment
calculations.

It reads cleaned job descriptions and the selected existing profile from the
production SQLite database in read-only mode. Results are written outside the
database.

## Run

```bash
source .venv/bin/activate
python -m experiments.structured_matching.run \
  --status experiment \
  --profile backend \
  --limit 10
```

Remove `--limit` to process every job with `experiment` status. No Ollama server
is needed.

## Matching

The curated alias dictionary is in `technologies.py`. For example, `Postgres`
maps to `PostgreSQL`, `K8s` maps to `Kubernetes`, and `Google Cloud Platform`
maps to `GCP`. Matching is case-insensitive and uses token boundaries so `Java`
does not match `JavaScript`.

Ambiguous short names use stricter variants: `Go` requires `Golang`, `Go
language`, or `Go programming`; `C` requires `C language`, `C programming`, or
`C/C++`.

The reported overlap is the percentage of technologies found in the job that
also occur in the profile. It is an inventory comparison, not yet a final job
ranking, because this phase does not determine whether a technology is required
or merely mentioned.

Engineering capabilities are extracted separately using the canonical aliases
in `capabilities.py`. They cover practices and architectural competencies such
as CI/CD, containerization, distributed systems, microservices, observability,
test automation, and infrastructure as code. Capability coverage is the
fraction of job capabilities also found in the original resume text. It is not
combined with technology coverage.

Education extraction recognizes high-school/GED, associate, bachelor, master,
and doctorate requirements, including degree-or-equivalent-experience language.
Every match retains its source context and is marked required, preferred, or
unspecified when headings or nearby wording make that distinction possible. The
minimum level is the lowest mandatory education level. Preferred degrees and
degrees with an explicit equivalent-experience path remain visible in the
mentions but do not set the required minimum.

Experience extraction recognizes numeric and spelled-out minimums, `N+ years`,
`N-M years`, and `N or more years`. It reports the highest non-preferred minimum
because a job may require both total experience and a smaller number of years in
a particular technology. Company-age and graduation-window phrases are excluded.

## Review output

The default output directory is `/tmp/jobranker-structured-matching`:

```text
jobs/<job_uid>.cleaned.txt     Original Python-cleaned description
jobs/<job_uid>.local.json      Technologies and qualification matches with contexts
jobs/<job_uid>.comparison.md   Readable extraction review
scores.csv                     Technology overlap, education, and experience columns
summary.json                   Run mode and extraction counts
```

The CSV is flushed after each job. Running the command again replaces files in
the selected output directory.

## Applied-job golden regression

The reviewed expectations for the 50 applied jobs are kept locally in
`golden_records_applied.json`. This file is ignored by Git and is not included
in a fresh checkout. The regression requires both this local file and the
matching jobs in the local database. Run the database-backed regression test with:

```bash
source .venv/bin/activate
python -m unittest experiments.structured_matching.regression_test
```

The standalone runner executes the actual experiment pipeline with `--status
applied` in a temporary output directory. It requires all 50 job UIDs and
compares technology membership, minimum required education, and minimum
experience years exactly. Technology ordering is ignored; missing or additional
technologies fail. It prints aggregate and detailed results and exits with code
0 only when every golden field matches; otherwise it exits with code 1.
