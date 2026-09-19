# Compare nano and mini base ranking

## Recorded result: keep mini (2026-09-18)

Decision: keep `gpt-5.4-mini` for production base ranking and final resume
ranking. In the user-reported 100-job comparison, nano's score differences were
too large to trust it as a replacement rejection gate. Keep the production
base-score threshold at 75; do not switch to nano based on cost alone.

The run completed 100 pairs with 200 new calls and no cache hits. At a threshold
of 75 for both models, decisions disagreed on 28 jobs (28%). All 28 were rejected
by nano and passed by mini. Nano rejected 45 jobs, including 11 applied jobs;
mini rejected 17 jobs. Lowering nano's threshold reduced disagreement but did
not eliminate rejection of applied jobs:

| Nano threshold | Nano rejections | Mini passes / nano rejects (mini threshold 75) | Applied jobs rejected by nano |
| --- | ---: | ---: | ---: |
| 65 | 24 | 7 | 3 |
| 70 | 26 | 9 | 3 |
| 75 | 45 | 28 | 11 |

| Model | Total tokens | Estimated ranking cost (USD) |
| --- | ---: | ---: |
| `gpt-5.4-nano` | 355,103 | $0.11463088 |
| `gpt-5.4-mini` | 336,551 | $0.33300705 |

All results had known pricing. Nano cost about 66% less for this sample, but
that saving did not justify the observed decision differences. These costs
cover the comparison ranking calls, not extraction or profile merging.

Mini is not ground truth. In particular, the previously identified news-page
capture `2567d571d4558b16` received nano=45 and mini=81. That disagreement is
not evidence of a worthwhile job missed by nano: invalid descriptions must be
stopped by local validation before ranking. The sample also includes legacy
extractions and deliberately emphasizes review cases, so these figures are not
population-wide accuracy estimates. The decision records the user's assessment
of suitability for this pipeline, not a general model-quality claim.

The summary above preserves the supplied experiment results; generated reports
and cached responses remain ignored by Git. No production model setting was
changed as part of recording this decision.

## Run the comparison

Prepare a reproducible sample without making AI calls:

```bash
source .venv/bin/activate
python -m experiments.base_ranking.run --limit 100
```

Review `experiments/base_ranking/output/manifest.json`, then run the comparison:

```bash
set -a
source .env
set +a
python -m experiments.base_ranking.run --run
```

Default models are `gpt-5.4-nano` and `gpt-5.4-mini`. Override them with
`--nano-model` and `--mini-model`. This makes up to two ranking calls per job;
no extraction calls are made. API errors produce a nonzero exit status and remain
visible in the CSV. Successful results remain reusable on the next invocation.

The production SQLite database is opened read-only. Production scores, statuses,
rankings, cache and cost records are not changed. Run one comparison process per
output directory. All default output files, including resume snapshots, are
ignored by Git. Use `--output /tmp/my-comparison` for a separate run, and
`--database <path>` for another database.

## Sample and resume behavior

Only jobs with saved nonempty AI extraction are eligible. Jobs rejected before
AI extraction cannot be included without paying for extraction first; this script
excludes them. Selection alternates between applied jobs, borderline jobs with a
previous base score from 65 through 85, previously filtered jobs, and other jobs.
Categories are exclusive for sampling in that priority order; all applicable tags
are retained. Scarce categories are supplemented by the remaining groups.
Selection is seeded (`--seed 42` by default), and may return fewer than requested
when fewer eligible jobs exist. `--limit` supports 1–100 (default 100).

The manifest freezes job UIDs, structured jobs, statuses and the current base
profile. Subsequent invocations reuse it even if production data, `--limit`, or
`--seed` changes. Use a new output directory to select a fresh sample. Existing
production scores are used only for selection; both models rank the frozen
inputs with the same current production prompt, schema and scoring weights.

Responses are cached by the complete API request, including model, profile, job,
prompt, weights and schema. Production caches are not reused. Raw responses are
written before validation, so even malformed output is not charged again on a
retry. To deliberately retry a malformed response, remove its corresponding
`output/cache/<request-hash>.json` file. API calls that fail before a response is
received cannot be cached. An interrupted API call might still incur a charge.

## Reports

- `scores.csv`: job/status/tags, both scores, pass decisions at 75, tokens,
  estimated USD cost and errors.
- `disagreements.csv`: different pass decisions, with nano-reject/mini-pass first,
  prioritizing applied jobs within each disagreement direction.
- `rankings.json`: full ranking explanations and dimension scores.
- `summary.json`: completed pairs, disagreements, cache hits/new calls, token and
  known cost totals, and nano thresholds 65/70/75 compared with mini at 75.
- `cache/`: raw responses and exact requests for reproducibility.

Reports are updated after each job. Costs describe all reported results,
including cached calls, rather than new spending on this invocation. Unknown
model prices remain unpriced. Resume extraction/merging costs are not included.
The sample intentionally emphasizes review cases; its rejection rate is not an
unbiased estimate for all incoming jobs. Mini is a comparison point, not ground
truth: manually review disagreements and rejected applied jobs before changing
the production threshold.

```bash
python -m unittest experiments.base_ranking.tests -v
```
