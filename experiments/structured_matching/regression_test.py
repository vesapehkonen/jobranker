from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from experiments.structured_matching.run import run


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
DATABASE = REPOSITORY / "data" / "jobranker.db"
GOLDEN_RECORDS = HERE / "golden_records_applied.json"
FIELDS = (
    "technologies",
    "education.minimum_level",
    "experience.minimum_years",
)


def _technology_names(extracted: dict) -> list[str]:
    return sorted(
        (str(item["name"]) for item in extracted.get("technologies", [])),
        key=str.casefold,
    )


def _field_values(expected: dict, actual: dict) -> dict[str, tuple[object, object]]:
    actual_education = actual.get("education") or {}
    actual_experience = actual.get("experience") or {}
    return {
        "technologies": (
            sorted(expected["technologies"], key=str.casefold),
            _technology_names(actual),
        ),
        "education.minimum_level": (
            expected["education"]["minimum_level"],
            actual_education.get("minimum_level"),
        ),
        "experience.minimum_years": (
            expected["experience"]["minimum_years"],
            actual_experience.get("minimum_years"),
        ),
    }


def regression() -> tuple[dict, list[dict]]:
    golden = json.loads(GOLDEN_RECORDS.read_text(encoding="utf-8"))
    expected_by_uid = {record["job_uid"]: record for record in golden}
    if len(golden) != 50 or len(expected_by_uid) != 50:
        raise ValueError("Golden dataset must contain exactly 50 unique applied-job UIDs")

    field_passes = dict.fromkeys(FIELDS, 0)
    mismatched_jobs: set[str] = set()
    differences: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="jobranker-applied-regression-") as directory:
        output = Path(directory)
        args = SimpleNamespace(
            database=DATABASE,
            status="applied",
            profile="backend",
            limit=None,
            output=output,
        )
        captured_output = io.StringIO()
        with contextlib.redirect_stdout(captured_output):
            extraction_summary = run(args)

        actual_files = sorted((output / "jobs").glob("*.local.json"))
        actual_by_uid = {
            path.name.removesuffix(".local.json"): json.loads(
                path.read_text(encoding="utf-8")
            )
            for path in actual_files
        }

        for job_uid, expected in expected_by_uid.items():
            actual = actual_by_uid.get(job_uid)
            if actual is None:
                mismatched_jobs.add(job_uid)
                for field in FIELDS:
                    differences.append({
                        "job_uid": job_uid,
                        "field": field,
                        "expected": "golden value",
                        "actual": "missing extraction output",
                    })
                continue

            for field, (expected_value, actual_value) in _field_values(
                expected, actual
            ).items():
                if expected_value == actual_value:
                    field_passes[field] += 1
                else:
                    mismatched_jobs.add(job_uid)
                    differences.append({
                        "job_uid": job_uid,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    })

        extra_uids = sorted(set(actual_by_uid) - set(expected_by_uid))
        for job_uid in extra_uids:
            mismatched_jobs.add(job_uid)
            differences.append({
                "job_uid": job_uid,
                "field": "job_uid",
                "expected": "not present",
                "actual": "unexpected extraction output",
            })

    total_jobs = len(expected_by_uid)
    report = {
        "total_jobs": total_jobs,
        "fully_correct_jobs": total_jobs - len(mismatched_jobs & set(expected_by_uid)),
        "jobs_with_mismatches": len(mismatched_jobs),
        "field_pass_counts": field_passes,
        "total_field_mismatches": len(differences),
        "extraction_job_count": extraction_summary["job_count"],
        "successful_extractions": extraction_summary["successful_extractions"],
        "invalid_input_count": extraction_summary["invalid_input_count"],
    }
    return report, differences


def main() -> int:
    if not DATABASE.exists():
        print(f"ERROR: Local production database not found: {DATABASE}", file=sys.stderr)
        return 1

    try:
        report, differences = regression()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Applied-job extraction regression")
    print(f"Total jobs: {report['total_jobs']}")
    print(f"Fully correct jobs: {report['fully_correct_jobs']}")
    print(f"Jobs with mismatches: {report['jobs_with_mismatches']}")
    print("Per-field pass counts:")
    for field in FIELDS:
        print(f"  {field}: {report['field_pass_counts'][field]}/{report['total_jobs']}")
    print(f"Total field mismatches: {report['total_field_mismatches']}")
    print("Detailed mismatches:")
    print(json.dumps(differences, indent=2, ensure_ascii=False))

    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
