import json
import sys
from pathlib import Path
from openai import OpenAI

from config import JOB_RANK_MODEL
from ai_costs import track_openai_response
from database import load_enabled_profiles


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




def rank_profile(
    client: OpenAI,
    profile_name: str,
    resume_profile: dict,
    job: dict,
    *,
    job_uid: str | None = None,
) -> dict:
    response = client.responses.create(
        model=JOB_RANK_MODEL,
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
    if getattr(response, "usage", None) is not None:
        track_openai_response(
            response,
            "job_rank",
            job_uid=job_uid,
            profile_name=profile_name,
        )

    ranking = json.loads(response.output_text)

    weighted_score = calculate_weighted_score(ranking["scores"])
    ranking["overall_fit_score"] = weighted_score
    ranking["recommendation"] = recommendation_from_score(weighted_score)

    return ranking


def rank_profiles(
    client: OpenAI,
    job: dict,
    profiles: dict[str, dict],
    *,
    job_uid: str | None = None,
) -> dict[str, dict]:
    profile_names = list(profiles)
    batch_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rankings": {
                "type": "array",
                "minItems": len(profile_names),
                "maxItems": len(profile_names),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "profile_name": {
                            "type": "string",
                            "enum": profile_names,
                        },
                        "ranking": SCHEMA,
                    },
                    "required": ["profile_name", "ranking"],
                },
            }
        },
        "required": ["rankings"],
    }
    response = client.responses.create(
        model=JOB_RANK_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Evaluate how well each candidate resume profile matches the "
                    "software engineering job. Return exactly one ranking for every "
                    "profile. Do not rank based on location, salary, or visa "
                    "sponsorship. Use evidence from each resume profile and the job "
                    "only. Score each dimension from 0 to 100. Be realistic and do "
                    "not over-score weak evidence. Profile names are labels only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "weights": WEIGHTS,
                        "job": job,
                        "profiles": profiles,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "job_fit_rankings",
                "schema": batch_schema,
                "strict": True,
            }
        },
    )
    if getattr(response, "usage", None) is not None:
        track_openai_response(response, "job_rank", job_uid=job_uid)

    result = json.loads(response.output_text)
    rankings: dict[str, dict] = {}
    for item in result["rankings"]:
        profile_name = item["profile_name"]
        if profile_name in rankings:
            raise ValueError(f"Duplicate ranking returned for profile {profile_name}")
        ranking = item["ranking"]
        weighted_score = calculate_weighted_score(ranking["scores"])
        ranking["overall_fit_score"] = weighted_score
        ranking["recommendation"] = recommendation_from_score(weighted_score)
        rankings[profile_name] = ranking

    missing = set(profile_names) - rankings.keys()
    if missing:
        raise ValueError(
            f"Missing ranking for profile(s): {', '.join(sorted(missing))}"
        )
    return rankings


def rank_job(
    client: OpenAI,
    job: dict,
    profiles: dict[str, dict],
    *,
    job_uid: str | None = None,
) -> dict:
    if not profiles:
        raise ValueError("At least one resume profile is required")
    profile_rankings = rank_profiles(
        client, job, profiles, job_uid=job_uid
    )
    recommended_profile = max(
        profile_rankings,
        key=lambda name: profile_rankings[name]["overall_fit_score"],
    )
    selected_ranking = profile_rankings[recommended_profile]
    profile_scores = {
        name: ranking["overall_fit_score"]
        for name, ranking in sorted(
            profile_rankings.items(),
            key=lambda item: item[1]["overall_fit_score"],
            reverse=True,
        )
    }
    return {
        "job": {
            key: job.get(key) for key in (
                "job_id", "job_source", "job_url", "company", "title",
                "location", "workplace_type", "employment_type", "main_skill",
            )
        },
        "recommended_profile": recommended_profile,
        "profile_scores": profile_scores,
        "profile_rankings": profile_rankings,
        "selected_profile": recommended_profile,
        "selected_ranking": selected_ranking,
        "ranking": selected_ranking,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python rank_job_ai.py <structured-job.json> <output-dir>")
        raise SystemExit(1)

    job_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = build_output_path(job_file, output_dir)

    profiles = load_enabled_profiles()
    job = json.loads(job_file.read_text(encoding="utf-8"))
    result = rank_job(OpenAI(), job, profiles)
    output_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Recommended profile: {result['recommended_profile']}")
    print(f"Profile scores: {result['profile_scores']}")
    print(f"Saved {output_file}")


if __name__ == "__main__":
    main()
