from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiments.local_matching.data import connect_read_only
from .quality import technology_confidence


DEFAULT_DATABASE = Path("data/jobranker.db")
DEFAULT_OUTPUT_ROOT = Path("/tmp/jobranker-structured-matching/evaluation")
AI_POSITIVE_SCORE = 70.0
LOW_COVERAGE = 0.30


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _ranks(values: list[float]) -> list[float]:
    result = [0.0] * len(values)
    ordered = sorted(range(len(values)), key=values.__getitem__)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[position]]:
            end += 1
        average_rank = (position + 1 + end) / 2
        for index in ordered[position:end]:
            result[index] = average_rank
        position = end
    return result


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = (left_variance * right_variance) ** 0.5
    return numerator / denominator if denominator else None


def spearman(left: list[float], right: list[float]) -> float | None:
    correlation = _pearson(_ranks(left), _ranks(right))
    return round(correlation, 3) if correlation is not None else None


def load_ai_scores(
    database: Path, profile_name: str, job_uids: list[str]
) -> dict[str, float]:
    if not job_uids:
        return {}
    placeholders = ",".join("?" for _ in job_uids)
    with connect_read_only(database) as db:
        rows = db.execute(
            f"""
            SELECT job_uid, score
            FROM profile_rankings
            WHERE profile_name = ? AND job_uid IN ({placeholders})
              AND score IS NOT NULL
            """,
            (profile_name, *job_uids),
        ).fetchall()
    return {str(row["job_uid"]): float(row["score"]) for row in rows}


def evaluate(
    comparisons: list[tuple[str, dict[str, Any]]],
    ai_scores: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for job_uid, comparison in comparisons:
        ai_score = ai_scores.get(job_uid)
        input_quality = comparison.get("input_quality") or {"status": "valid", "reasons": []}
        input_status = str(input_quality.get("status", "valid"))
        technology = comparison.get("technology")
        capability = comparison.get("capability")
        if input_status == "invalid" or not isinstance(technology, dict):
            rows.append({
                "job_uid": job_uid,
                "ai_score": ai_score,
                "input_status": "invalid",
                "invalid_reasons": ",".join(input_quality.get("reasons", [])),
                "technology_confidence": "unknown",
                "technology_coverage": None,
                "job_technology_count": 0,
                "matched_technology_count": 0,
                "capability_confidence": "unknown",
                "capability_coverage": None,
                "job_capability_count": 0,
                "matched_capability_count": 0,
                "low_coverage_high_ai": False,
                "capability_low_coverage_high_ai": False,
            })
            continue

        coverage_value = technology.get("coverage")
        coverage = float(coverage_value) if coverage_value is not None else None
        job_count = int(technology["job_count"])
        confidence = str(
            technology.get("confidence") or technology_confidence(job_count)
        )
        if not isinstance(capability, dict):
            capability = {
                "coverage": None, "confidence": "unknown",
                "job_count": 0, "matched_count": 0,
            }
        capability_coverage_value = capability.get("coverage")
        capability_coverage = (
            float(capability_coverage_value)
            if capability_coverage_value is not None else None
        )
        capability_job_count = int(capability["job_count"])
        capability_confidence = str(
            capability.get("confidence") or technology_confidence(capability_job_count)
        )
        rows.append({
            "job_uid": job_uid,
            "ai_score": ai_score,
            "input_status": "valid",
            "invalid_reasons": "",
            "technology_confidence": confidence,
            "technology_coverage": coverage,
            "job_technology_count": job_count,
            "matched_technology_count": int(technology["matched_count"]),
            "capability_confidence": capability_confidence,
            "capability_coverage": capability_coverage,
            "job_capability_count": capability_job_count,
            "matched_capability_count": int(capability["matched_count"]),
            "low_coverage_high_ai": (
                ai_score is not None
                and confidence == "high"
                and coverage is not None
                and coverage < LOW_COVERAGE
                and ai_score >= AI_POSITIVE_SCORE
            ),
            "capability_low_coverage_high_ai": (
                ai_score is not None
                and capability_confidence == "high"
                and capability_coverage is not None
                and capability_coverage < LOW_COVERAGE
                and ai_score >= AI_POSITIVE_SCORE
            ),
        })

    comparable = [
        row for row in rows
        if row["ai_score"] is not None
        and row["input_status"] == "valid"
        and row["technology_confidence"] == "high"
        and row["technology_coverage"] is not None
    ]
    correlation = spearman(
        [float(row["technology_coverage"]) for row in comparable],
        [float(row["ai_score"]) for row in comparable],
    )
    capability_comparable = [
        row for row in rows
        if row["ai_score"] is not None
        and row["input_status"] == "valid"
        and row["capability_confidence"] == "high"
        and row["capability_coverage"] is not None
    ]
    capability_correlation = spearman(
        [float(row["capability_coverage"]) for row in capability_comparable],
        [float(row["ai_score"]) for row in capability_comparable],
    )
    summary = {
        "job_count": len(rows),
        "jobs_with_ai_score": sum(row["ai_score"] is not None for row in rows),
        "invalid_job_count": sum(row["input_status"] == "invalid" for row in rows),
        "valid_job_count": sum(row["input_status"] == "valid" for row in rows),
        "technology_confidence": {
            confidence: sum(
                row["input_status"] == "valid"
                and row["technology_confidence"] == confidence
                for row in rows
            )
            for confidence in ("unknown", "low", "high")
        },
        "comparable_job_count": len(comparable),
        "spearman_vs_ai": correlation,
        "capability_confidence": {
            confidence: sum(
                row["input_status"] == "valid"
                and row["capability_confidence"] == confidence
                for row in rows
            )
            for confidence in ("unknown", "low", "high")
        },
        "capability_comparable_job_count": len(capability_comparable),
        "capability_spearman_vs_ai": capability_correlation,
        "low_coverage_threshold": LOW_COVERAGE,
        "ai_positive_threshold": AI_POSITIVE_SCORE,
        "low_coverage_high_ai_count": sum(
            bool(row["low_coverage_high_ai"]) for row in rows
        ),
        "capability_low_coverage_high_ai_count": sum(
            bool(row["capability_low_coverage_high_ai"]) for row in rows
        ),
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare deterministic technology coverage with backend AI scores"
    )
    parser.add_argument("--state", "--status", dest="status")
    parser.add_argument("--limit", type=_positive_integer)
    parser.add_argument("--profile", default="backend")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--as-of", help="Employment calculation month in YYYY-MM format")
    args = parser.parse_args()

    output = args.output or DEFAULT_OUTPUT_ROOT / (args.status or "all")
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "experiments.structured_matching.run_local_comparison",
        "--profile",
        args.profile,
        "--database",
        str(args.database),
        "--output",
        str(output),
    ]
    if args.status:
        command.extend(("--state", args.status))
    if args.limit:
        command.extend(("--limit", str(args.limit)))
    if args.as_of:
        command.extend(("--as-of", args.as_of))
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)

    manifest_file = output / "selected_job_uids.json"
    job_uids = json.loads(manifest_file.read_text(encoding="utf-8"))
    comparisons = [
        (
            job_uid,
            json.loads(
                (output / f"{job_uid}.comparison.json").read_text(encoding="utf-8")
            ),
        )
        for job_uid in job_uids
    ]
    rows, summary = evaluate(
        comparisons,
        load_ai_scores(args.database, args.profile, job_uids),
    )

    csv_file = output / "technology_vs_ai.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "job_uid", "ai_score", "input_status", "invalid_reasons",
            "technology_confidence", "technology_coverage",
            "job_technology_count", "matched_technology_count",
            "capability_confidence", "capability_coverage",
            "job_capability_count", "matched_capability_count",
            "low_coverage_high_ai", "capability_low_coverage_high_ai",
        ))
        writer.writeheader()
        writer.writerows(rows)
    summary_file = output / "technology_vs_ai_summary.json"
    summary_file.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    print(f"Saved {csv_file}")
    print(f"Saved {summary_file}")


if __name__ == "__main__":
    main()
