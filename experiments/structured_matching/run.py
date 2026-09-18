from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .capabilities import extract_capabilities
from .data import load_inputs
from .quality import technology_confidence, validate_job_text
from .qualifications import extract_education, extract_experience
from .technologies import extract_technologies, flatten_profile_text


CSV_FIELDS = [
    "job_uid", "title", "ai_score", "input_quality_status", "input_quality_reasons",
    "extraction_status", "technology_confidence", "technology_overlap_percent",
    "job_technology_count", "matched_technologies", "job_only_technologies",
    "profile_technology_count", "capability_confidence", "capability_overlap_percent",
    "job_capability_count", "matched_capabilities", "job_only_capabilities",
    "profile_capability_count", "minimum_education", "education_levels_found",
    "equivalent_experience_allowed", "minimum_years_experience",
    "experience_mention_count", "error",
]


def _names(items: list[dict]) -> set[str]:
    return {str(item["name"]) for item in items}


def write_review_files(
    directory: Path, job, job_technologies: list[dict],
    profile_technologies: list[dict], job_capabilities: list[dict],
    profile_capabilities: list[dict], education: dict, experience: dict,
    input_quality: dict,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{job.job_uid}.cleaned.txt").write_text(
        job.description + "\n", encoding="utf-8"
    )
    job_names = _names(job_technologies)
    profile_names = _names(profile_technologies)
    job_capability_names = _names(job_capabilities)
    profile_capability_names = _names(profile_capabilities)
    extracted = {
        "input_quality": input_quality,
        "extraction_status": "completed",
        "technology_confidence": technology_confidence(len(job_names)),
        "technologies": job_technologies,
        "matched_profile_technologies": sorted(job_names & profile_names),
        "job_only_technologies": sorted(job_names - profile_names),
        "capability_confidence": technology_confidence(len(job_capability_names)),
        "capabilities": job_capabilities,
        "matched_profile_capabilities": sorted(job_capability_names & profile_capability_names),
        "job_only_capabilities": sorted(job_capability_names - profile_capability_names),
        "education": education,
        "experience": experience,
    }
    (directory / f"{job.job_uid}.local.json").write_text(
        json.dumps(extracted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        f"# {job.title or job.job_uid}", "",
        "## Input quality", "",
        f"- Status: {input_quality['status']}",
        f"- Characters: {input_quality['character_count']}", "",
        "## Technologies found by word search", "",
    ]
    if not job_technologies:
        lines.extend(["_None found_", ""])
    for technology in job_technologies:
        match = "profile match" if technology["name"] in profile_names else "not in profile"
        aliases = ", ".join(technology["aliases_found"])
        lines.extend([
            f"### {technology['name']} ({match})", "",
            f"- Matched text: {aliases}",
            f"- Occurrences: {technology['occurrences']}",
        ])
        lines.extend(f"- Context: {context}" for context in technology["contexts"])
        lines.append("")
    lines.extend(["## Capabilities found by word search", ""])
    if not job_capabilities:
        lines.extend(["_None found_", ""])
    for capability in job_capabilities:
        match = "profile match" if capability["name"] in profile_capability_names else "not in profile"
        aliases = ", ".join(capability["aliases_found"])
        lines.extend([
            f"### {capability['name']} ({match})", "",
            f"- Matched text: {aliases}",
            f"- Occurrences: {capability['occurrences']}",
        ])
        lines.extend(f"- Context: {context}" for context in capability["contexts"])
        lines.append("")
    lines.extend(["## Education found by Python", ""])
    if education["mentions"]:
        lines.extend([
            f"- Minimum level: {education['minimum_level'] or 'not determined'}",
            f"- Equivalent experience allowed: {'yes' if education['equivalent_experience_allowed'] else 'no'}",
            "",
        ])
        for mention in education["mentions"]:
            lines.append(
                f"- **{mention['level']}** ({mention['classification']}): "
                f"{mention['matched_text']} — {mention['context']}"
            )
    else:
        lines.append("_No education requirement found_")
    lines.extend(["", "## Experience years found by Python", ""])
    if experience["mentions"]:
        lines.append(f"- Minimum required years: {experience['minimum_years'] if experience['minimum_years'] is not None else 'not determined'}")
        lines.append("")
        for mention in experience["mentions"]:
            maximum = f"–{mention['maximum_years']}" if mention["maximum_years"] is not None else ""
            lines.append(
                f"- **{mention['minimum_years']}{maximum} years** ({mention['classification']}): "
                f"{mention['context']}"
            )
    else:
        lines.append("_No experience-years requirement found_")
    lines.extend(["",
        "## Profile technology inventory", "",
        ", ".join(sorted(profile_names)) or "_None found_", "",
        "## Original cleaned description", "", job.description, "",
    ])
    (directory / f"{job.job_uid}.comparison.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def write_invalid_review_files(directory: Path, job, input_quality: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{job.job_uid}.cleaned.txt").write_text(
        job.description + "\n", encoding="utf-8"
    )
    extracted = {
        "input_quality": input_quality,
        "extraction_status": "skipped_invalid_input",
        "technology_confidence": "unknown",
        "technologies": [],
        "matched_profile_technologies": [],
        "job_only_technologies": [],
        "capability_confidence": "unknown",
        "capabilities": [],
        "matched_profile_capabilities": [],
        "job_only_capabilities": [],
        "education": None,
        "experience": None,
    }
    (directory / f"{job.job_uid}.local.json").write_text(
        json.dumps(extracted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    reasons = ", ".join(input_quality["reasons"]) or "unknown"
    (directory / f"{job.job_uid}.comparison.md").write_text(
        "\n".join((
            f"# {job.title or job.job_uid}", "", "## Input quality", "",
            "- Status: invalid", f"- Reasons: {reasons}",
            f"- Characters: {input_quality['character_count']}", "",
            "Field extraction was skipped.", "", "## Original cleaned description",
            "", job.description, "",
        )),
        encoding="utf-8",
    )


def run(args) -> dict:
    jobs, profile = load_inputs(args.database, status=args.status, profile_name=args.profile)
    job_uid = getattr(args, "job_uid", None)
    if job_uid:
        jobs = [job for job in jobs if job.job_uid == job_uid]
    if args.limit:
        jobs = jobs[:args.limit]
    if not jobs:
        selection = "any status" if args.status is None else f"status {args.status!r}"
        raise SystemExit(f"No cleaned jobs found with {selection}")

    profile_technologies = extract_technologies(flatten_profile_text(profile))
    profile_names = _names(profile_technologies)
    profile_capabilities = extract_capabilities(flatten_profile_text(profile))
    profile_capability_names = _names(profile_capabilities)
    output = args.output
    review_directory = output / "jobs"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with (output / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for index, job in enumerate(jobs, start=1):
            row = {field: "" for field in CSV_FIELDS}
            row.update({"job_uid": job.job_uid, "title": job.title, "ai_score": job.ai_score})
            try:
                input_quality = validate_job_text(job.description)
                row.update({
                    "input_quality_status": input_quality["status"],
                    "input_quality_reasons": json.dumps(input_quality["reasons"]),
                })
                if input_quality["status"] == "invalid":
                    row.update({
                        "extraction_status": "skipped_invalid_input",
                        "technology_confidence": "unknown",
                        "job_technology_count": 0,
                        "matched_technologies": "[]",
                        "job_only_technologies": "[]",
                        "profile_technology_count": len(profile_names),
                        "capability_confidence": "unknown",
                        "job_capability_count": 0,
                        "matched_capabilities": "[]",
                        "job_only_capabilities": "[]",
                        "profile_capability_count": len(profile_capability_names),
                    })
                    write_invalid_review_files(review_directory, job, input_quality)
                    print(
                        f"[{index}/{len(jobs)}] INVALID {job.title or job.job_uid}: "
                        f"{', '.join(input_quality['reasons'])}",
                        flush=True,
                    )
                    writer.writerow(row)
                    handle.flush()
                    rows.append(row)
                    continue
                job_technologies = extract_technologies(job.description)
                job_capabilities = extract_capabilities(job.description)
                education = extract_education(job.description)
                experience = extract_experience(job.description)
                job_names = _names(job_technologies)
                matched = sorted(job_names & profile_names)
                job_only = sorted(job_names - profile_names)
                overlap = 100 * len(matched) / len(job_names) if job_names else None
                job_capability_names = _names(job_capabilities)
                matched_capabilities = sorted(job_capability_names & profile_capability_names)
                job_only_capabilities = sorted(job_capability_names - profile_capability_names)
                capability_overlap = (
                    100 * len(matched_capabilities) / len(job_capability_names)
                    if job_capability_names else None
                )
                row.update({
                    "extraction_status": "completed",
                    "technology_confidence": technology_confidence(len(job_names)),
                    "technology_overlap_percent": round(overlap, 3) if overlap is not None else "",
                    "job_technology_count": len(job_names),
                    "matched_technologies": json.dumps(matched, ensure_ascii=False),
                    "job_only_technologies": json.dumps(job_only, ensure_ascii=False),
                    "profile_technology_count": len(profile_names),
                    "capability_confidence": technology_confidence(len(job_capability_names)),
                    "capability_overlap_percent": round(capability_overlap, 3) if capability_overlap is not None else "",
                    "job_capability_count": len(job_capability_names),
                    "matched_capabilities": json.dumps(matched_capabilities, ensure_ascii=False),
                    "job_only_capabilities": json.dumps(job_only_capabilities, ensure_ascii=False),
                    "profile_capability_count": len(profile_capability_names),
                    "minimum_education": education["minimum_level"] or "",
                    "education_levels_found": json.dumps(education["levels_found"]),
                    "equivalent_experience_allowed": education["equivalent_experience_allowed"],
                    "minimum_years_experience": (
                        experience["minimum_years"] if experience["minimum_years"] is not None else ""
                    ),
                    "experience_mention_count": len(experience["mentions"]),
                })
                write_review_files(
                    review_directory, job, job_technologies, profile_technologies,
                    job_capabilities, profile_capabilities, education, experience,
                    input_quality,
                )
                display = f"{row['technology_overlap_percent']}%" if overlap is not None else "no technologies"
                print(f"[{index}/{len(jobs)}] {job.title or job.job_uid}: {display}", flush=True)
            except Exception as error:
                row["error"] = f"{type(error).__name__}: {error}"
                print(f"[{index}/{len(jobs)}] ERROR {job.title or job.job_uid}: {error}", flush=True)
            writer.writerow(row)
            handle.flush()
            rows.append(row)

    valid_rows = [row for row in rows if row["extraction_status"] == "completed"]
    detected_counts = [int(row["job_technology_count"]) for row in valid_rows]
    capability_counts = [int(row["job_capability_count"]) for row in valid_rows]
    summary = {
        "mode": "deterministic_python_extraction",
        "llm_enabled": False,
        "embeddings_enabled": False,
        "job_count": len(jobs),
        "successful_extractions": len(valid_rows),
        "invalid_input_count": sum(
            row["extraction_status"] == "skipped_invalid_input" for row in rows
        ),
        "profile_technology_count": len(profile_names),
        "profile_capability_count": len(profile_capability_names),
        "average_job_technology_count": (
            round(sum(detected_counts) / len(detected_counts), 3) if detected_counts else None
        ),
        "average_job_capability_count": (
            round(sum(capability_counts) / len(capability_counts), 3)
            if capability_counts else None
        ),
        "jobs_with_education": sum(bool(row["minimum_education"]) for row in valid_rows),
        "jobs_with_minimum_years": sum(
            row["minimum_years_experience"] != "" for row in valid_rows
        ),
        "profile": args.profile,
        "status": args.status if args.status is not None else "all",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Python job extraction experiment")
    parser.add_argument("--database", type=Path, default=Path("data/jobranker.db"))
    parser.add_argument("--status", default="experiment")
    parser.add_argument("--all", action="store_true", help="Process jobs from every status")
    parser.add_argument("--profile", default="backend")
    parser.add_argument("--job-uid", help="Process only this job UID")
    parser.add_argument("--output", type=Path, default=Path("/tmp/jobranker-structured-matching"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.all:
        args.status = None
    run(args)


if __name__ == "__main__":
    main()
