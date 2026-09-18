from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from experiments.local_matching.data import connect_read_only


DEFAULT_DATABASE = Path("data/jobranker.db")
DEFAULT_OUTPUT_ROOT = Path("/tmp/jobranker-structured-matching/results")


def _job_status(database: Path, job_uid: str) -> str:
    with connect_read_only(database) as db:
        row = db.execute(
            "SELECT application_status FROM jobs WHERE job_uid = ?",
            (job_uid,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Job not found: {job_uid}")
    return str(row["application_status"])


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and compare database jobs with a deterministic local profile"
    )
    parser.add_argument("job_uid", nargs="?", help="Process only this job UID")
    parser.add_argument(
        "--state", "--status", dest="status",
        help="Process jobs with this application state",
    )
    parser.add_argument("--limit", type=_positive_integer)
    parser.add_argument("--profile", default="backend")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--as-of", help="Employment calculation month in YYYY-MM format")
    args = parser.parse_args()

    if args.job_uid and args.status:
        parser.error("use either job_uid or --state, not both")
    if args.job_uid and args.limit:
        parser.error("--limit cannot be used with an explicit job_uid")

    status = _job_status(args.database, args.job_uid) if args.job_uid else args.status
    output_name = args.job_uid or status or "all"
    output = args.output or DEFAULT_OUTPUT_ROOT / str(output_name)
    output.mkdir(parents=True, exist_ok=True)
    profile_file = output / f"{args.profile}.local.json"

    profile_command = [
        sys.executable,
        "-m",
        "experiments.structured_matching.extract_profile",
        "--database",
        str(args.database),
        "--profile",
        args.profile,
        "--output",
        str(profile_file),
    ]
    if args.as_of:
        profile_command.extend(("--as-of", args.as_of))

    with tempfile.TemporaryDirectory(prefix="jobranker-local-comparison-") as directory:
        temporary_output = Path(directory)
        _run(profile_command)
        extraction_command = [
            sys.executable,
            "-m",
            "experiments.structured_matching.run",
            "--database",
            str(args.database),
            "--profile",
            args.profile,
            "--output",
            str(temporary_output),
        ]
        if args.job_uid:
            extraction_command.extend(("--status", str(status)))
            extraction_command.extend(("--job-uid", args.job_uid))
        elif status:
            extraction_command.extend(("--status", status))
        else:
            extraction_command.append("--all")
        if args.limit:
            extraction_command.extend(("--limit", str(args.limit)))
        _run(extraction_command)

        extracted_jobs = sorted((temporary_output / "jobs").glob("*.local.json"))
        if not extracted_jobs:
            raise RuntimeError("Job extraction did not create any local JSON files")
        job_files = []
        for extracted_job in extracted_jobs:
            job_uid = extracted_job.name.removesuffix(".local.json")
            cleaned_file = output / f"{job_uid}.cleaned.txt"
            job_file = output / f"{job_uid}.local.json"
            comparison_file = output / f"{job_uid}.comparison.json"
            extracted_cleaned = temporary_output / "jobs" / f"{job_uid}.cleaned.txt"
            if not extracted_cleaned.exists():
                raise RuntimeError(f"Job extraction did not create {extracted_cleaned}")
            shutil.copy2(extracted_cleaned, cleaned_file)
            shutil.copy2(extracted_job, job_file)
            _run([
                sys.executable,
                "-m",
                "experiments.structured_matching.compare_profile",
                "--job",
                str(job_file),
                "--profile",
                str(profile_file),
                "--output",
                str(comparison_file),
            ])
            job_files.append((cleaned_file, job_file, comparison_file))

    manifest_file = output / "selected_job_uids.json"
    manifest_file.write_text(
        json.dumps(
            [job_file.name.removesuffix(".local.json") for _, job_file, _ in job_files],
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Created job artifacts in {output}:")
    print(profile_file)
    for cleaned_file, job_file, comparison_file in job_files:
        print(cleaned_file)
        print(job_file)
        print(comparison_file)
    print(manifest_file)


if __name__ == "__main__":
    main()
