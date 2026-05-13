import json
import sys
from pathlib import Path
from openai import OpenAI

from config import OPENAI_MODEL

PROFILE_DIR = Path("data/profile")

WEIGHTS = {
    "technical_skill_fit": 0.35,
    "role_experience_fit": 0.30,
    "domain_fit": 0.15,
    "seniority_fit": 0.10,
    "resume_evidence_strength": 0.10,
}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "recommendation": {
            "type": "string",
            "enum": ["strong", "good", "weak", "no"],
        },
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "technical_skill_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                "role_experience_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                "domain_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                "seniority_fit": {"type": "integer", "minimum": 0, "maximum": 100},
                "resume_evidence_strength": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": [
                "technical_skill_fit",
                "role_experience_fit",
                "domain_fit",
                "seniority_fit",
                "resume_evidence_strength",
            ],
        },
        "matched_strengths": {"type": "array", "items": {"type": "string"}},
        "missing_or_weak_areas": {"type": "array", "items": {"type": "string"}},
        "transferable_experience": {"type": "array", "items": {"type": "string"}},
        "interview_risk": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": [
        "overall_fit_score",
        "recommendation",
        "scores",
        "matched_strengths",
        "missing_or_weak_areas",
        "transferable_experience",
        "interview_risk",
        "reasoning",
    ],
}


def build_output_path(job_file: Path, output_dir: Path) -> Path:
    name = job_file.name

    if name.endswith(".structured.json"):
        name = name.replace(".structured.json", ".ranked.json")
    else:
        name = job_file.stem + ".ranked.json"

    return output_dir / name


def calculate_weighted_score(scores: dict) -> int:
    total = 0.0

    for key, weight in WEIGHTS.items():
        total += scores[key] * weight

    return round(total)


def recommendation_from_score(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "good"
    if score >= 45:
        return "weak"
    return "no"


def load_profiles(profile_dir: Path) -> dict[str, dict]:
    profiles = {}

    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile directory not found: {profile_dir}")

    for profile_file in sorted(profile_dir.glob("*/profile.json")):
        profile_name = profile_file.parent.name
        profiles[profile_name] = json.loads(profile_file.read_text(encoding="utf-8"))

    if not profiles:
        raise FileNotFoundError(
            f"No profiles found in {profile_dir}. Expected files like data/profile/backend/profile.json"
        )

    return profiles


def rank_profile(
    client: OpenAI,
    profile_name: str,
    resume_profile: dict,
    job: dict,
) -> dict:
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You evaluate how well a specific candidate resume profile matches a software engineering job. "
                    "Do not rank based on location, salary, or visa sponsorship. "
                    "Use evidence from the resume profile and the job only. "
                    "Score each dimension from 0 to 100. "
                    "Be realistic and do not over-score weak evidence. "
                    "The profile name is only a label; score from the resume content, not the label."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "profile_name": profile_name,
                        "weights": WEIGHTS,
                        "resume_profile": resume_profile,
                        "job": job,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "job_fit_ranking",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    )

    ranking = json.loads(response.output_text)

    weighted_score = calculate_weighted_score(ranking["scores"])
    ranking["overall_fit_score"] = weighted_score
    ranking["recommendation"] = recommendation_from_score(weighted_score)

    return ranking


def main() -> None:
    if len(sys.argv) == 3:
        profile_dir = PROFILE_DIR
        job_file = Path(sys.argv[1])
        output_dir = Path(sys.argv[2])
    elif len(sys.argv) == 4:
        profile_dir = Path(sys.argv[1])
        job_file = Path(sys.argv[2])
        output_dir = Path(sys.argv[3])
    else:
        print("Usage:")
        print("  python rank_job_ai.py data/structured/job.structured.json data/ranked")
        print("  python rank_job_ai.py data/profile data/structured/job.structured.json data/ranked")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = build_output_path(job_file, output_dir)

    profiles = load_profiles(profile_dir)
    job = json.loads(job_file.read_text(encoding="utf-8"))

    client = OpenAI()

    profile_rankings = {}

    for profile_name, resume_profile in profiles.items():
        print(f"Ranking {job_file.name} against profile: {profile_name}")
        profile_rankings[profile_name] = rank_profile(
            client=client,
            profile_name=profile_name,
            resume_profile=resume_profile,
            job=job,
        )

    recommended_profile = max(
        profile_rankings,
        key=lambda name: profile_rankings[name]["overall_fit_score"],
    )

    selected_ranking = profile_rankings[recommended_profile]

    profile_scores = {
        profile_name: ranking["overall_fit_score"]
        for profile_name, ranking in sorted(
            profile_rankings.items(),
            key=lambda item: item[1]["overall_fit_score"],
            reverse=True,
        )
    }

    result = {
        "job": {
            "job_id": job.get("job_id"),
            "job_source": job.get("job_source"),
            "job_url": job.get("job_url"),
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "workplace_type": job.get("workplace_type"),
            "employment_type": job.get("employment_type"),
            "main_skill": job.get("main_skill"),
        },
        "recommended_profile": recommended_profile,
        "profile_scores": profile_scores,
        "profile_rankings": profile_rankings,
        "selected_profile": recommended_profile,
        "selected_ranking": selected_ranking,
        "ranking": selected_ranking,
    }

    output_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Recommended profile: {recommended_profile}")
    print(f"Profile scores: {profile_scores}")
    print(f"Saved {output_file}")


if __name__ == "__main__":
    main()
