# Local matching experiment

This standalone experiment compares resume profiles with jobs without using any
AI-extracted fields as matcher inputs.

## Input boundary

The matching loader reads only:

- `jobs.job_uid`, `jobs.page_title`, and `jobs.application_status`
- Python-produced `job_artifacts.cleaned_json`
- Original `profiles.resume_text`

It deliberately does not select `structured_json`, `ranked_json`, or
`profiles.profile_json`. The evaluation module separately reads scores from
`profile_rankings` after matching; those scores are references only.

## Run lexical comparison

The lexical implementation is dependency-free:

```bash
source .venv/bin/activate
python -m experiments.local_matching.run --method lexical
```

## Run semantic and hybrid comparison

Install the CPU tensor runtime first, then the experiment-only dependency and
run all matchers:

```bash
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r experiments/local_matching/requirements.txt
python -m experiments.local_matching.run --method all
```

For captures made in experiment mode, restrict both sides explicitly:

```bash
python -m experiments.local_matching.run \
  --status experiment \
  --profile backend \
  --method all
```

The default semantic model is `sentence-transformers/all-MiniLM-L6-v2` and runs
on CPU. Its first run downloads model files; later runs load only the local
cache. Use `--limit 20` for a quick check.

## Output

Results are written to the ignored `experiments/local_matching/output/` folder:

- `scores.csv`: every job/profile pair and its local scores
- `disagreements.csv`: the 100 largest differences from existing AI scores
- `profile_summary.csv`: correlation with AI scores for each resume profile
- `summary.json`: correlations and average scores by application status

Local scores are similarity measures, not calibrated replacements for the
current 0–100 fit score. Review rankings and disagreements before selecting
thresholds or integrating a matcher into the application.

## Tests

```bash
python -m unittest discover -s experiments/local_matching/tests -v
```
