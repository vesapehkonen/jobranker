from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[index]]:
            end += 1
        rank = (index + end - 1) / 2 + 1
        for position in ordered[index:end]:
            result[position] = rank
        index = end
    return result


def spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    a, b = _ranks(left), _ranks(right)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    denominator = math.sqrt(
        sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)
    )
    return numerator / denominator if denominator else None


def write_evaluation(
    rows: list[dict[str, object]], references: dict[tuple[str, str], float], output_dir: Path
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = []
    for row in rows:
        item = dict(row)
        item["ai_score"] = references.get((str(row["job_uid"]), str(row["profile_name"])))
        enriched.append(item)

    columns = list(enriched[0]) if enriched else []
    with (output_dir / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(enriched)

    methods = [name for name in ("lexical_score", "semantic_score", "hybrid_score") if rows and rows[0].get(name) is not None]
    comparable = [row for row in enriched if row["ai_score"] is not None]
    correlations = {
        method: spearman(
            [float(row[method]) for row in comparable],
            [float(row["ai_score"]) for row in comparable],
        ) for method in methods
    }

    by_job: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in comparable:
        by_job[str(row["job_uid"])].append(row)
    top_profile_agreement = {}
    for method in methods:
        agreements = 0
        eligible = 0
        for candidates in by_job.values():
            if not candidates:
                continue
            local_best = max(candidates, key=lambda row: float(row[method]))["profile_name"]
            ai_best = max(candidates, key=lambda row: float(row["ai_score"]))["profile_name"]
            agreements += local_best == ai_best
            eligible += 1
        top_profile_agreement[method] = agreements / eligible if eligible else None

    profile_summary = []
    for profile_name in sorted({str(row["profile_name"]) for row in comparable}):
        profile_rows = [row for row in comparable if row["profile_name"] == profile_name]
        item: dict[str, object] = {"profile_name": profile_name, "pair_count": len(profile_rows)}
        for method in methods:
            item[f"{method}_spearman"] = spearman(
                [float(row[method]) for row in profile_rows],
                [float(row["ai_score"]) for row in profile_rows],
            )
        profile_summary.append(item)
    if profile_summary:
        with (output_dir / "profile_summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(profile_summary[0]))
            writer.writeheader()
            writer.writerows(profile_summary)

    disagreements = sorted(
        comparable,
        key=lambda row: max(abs(float(row[method]) - float(row["ai_score"])) for method in methods),
        reverse=True,
    )
    with (output_dir / "disagreements.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(disagreements[:100])

    status_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    outcome_rows = []
    all_by_job: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in enriched:
        all_by_job[str(row["job_uid"])].append(row)
    for candidates in all_by_job.values():
        outcome_rows.append({
            "status": candidates[0]["status"],
            **{method: max(float(row[method]) for row in candidates) for method in methods},
        })
    for row in outcome_rows:
        for method in methods:
            status_scores[str(row["status"])][method].append(float(row[method]))
    by_status = {
        status: {method: round(sum(values) / len(values), 3) for method, values in scores.items()}
        for status, scores in status_scores.items()
    }
    summary = {
        "pair_count": len(rows), "ai_reference_count": len(comparable),
        "spearman_vs_ai": correlations,
        "top_profile_agreement_vs_ai": top_profile_agreement,
        "average_best_profile_score_by_job_status": by_status,
        "warning": "AI scores and statuses are evaluation references only; they were not matcher inputs.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
