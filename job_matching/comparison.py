from __future__ import annotations

from typing import Any
from .qualifications import EDUCATION_RANK
from .quality import technology_confidence


def _names(value: object, field: str) -> set[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    names = set()
    for item in value:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            name = item["name"]
        else:
            raise ValueError(f"{field} entries must be names or objects with a name")
        if name.strip():
            names.add(name.strip())
    return names


def compare(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    input_quality = job.get("input_quality")
    if not isinstance(input_quality, dict):
        input_quality = {"status": "valid", "reasons": []}
    if input_quality.get("status") == "invalid":
        return {
            "comparison_status": "invalid_job_description",
            "input_quality": input_quality,
            "technology": None,
            "capability": None,
            "experience": None,
            "education": None,
        }

    job_technologies = _names(job.get("technologies"), "technologies")
    profile_technologies = _names(profile.get("technologies"), "technologies")
    matched = job_technologies & profile_technologies
    job_only = job_technologies - profile_technologies
    technology_coverage = (
        round(len(matched) / len(job_technologies), 3)
        if job_technologies else None
    )
    job_capabilities = _names(job.get("capabilities", []), "capabilities")
    profile_capabilities = _names(profile.get("capabilities", []), "capabilities")
    matched_capabilities = job_capabilities & profile_capabilities
    job_only_capabilities = job_capabilities - profile_capabilities
    capability_coverage = (
        round(len(matched_capabilities) / len(job_capabilities), 3)
        if job_capabilities else None
    )

    job_experience = job.get("experience")
    profile_experience = profile.get("experience")
    if not isinstance(job_experience, dict) or not isinstance(profile_experience, dict):
        raise ValueError("job and profile must contain experience objects")
    required_years = job_experience.get("minimum_years")
    profile_years = profile_experience.get("total_years")
    if required_years is not None and not isinstance(required_years, (int, float)):
        raise ValueError("job experience.minimum_years must be a number or null")
    if profile_years is not None and not isinstance(profile_years, (int, float)):
        raise ValueError("profile experience.total_years must be a number or null")

    if required_years is None:
        experience_difference = None
        experience_ratio = None
        experience_meets = True
    elif profile_years is None:
        experience_difference = None
        experience_ratio = None
        experience_meets = False
    else:
        experience_difference = round(profile_years - required_years, 3)
        experience_ratio = (
            round(profile_years / required_years, 3)
            if required_years else None
        )
        experience_meets = profile_years >= required_years

    job_education = job.get("education")
    profile_education = profile.get("education")
    if not isinstance(job_education, dict) or not isinstance(profile_education, dict):
        raise ValueError("job and profile must contain education objects")
    required_education = job_education.get("minimum_level")
    profile_education_level = profile_education.get("highest_level")
    if required_education is not None and required_education not in EDUCATION_RANK:
        raise ValueError(f"unknown job education level: {required_education}")
    if profile_education_level is not None and profile_education_level not in EDUCATION_RANK:
        raise ValueError(f"unknown profile education level: {profile_education_level}")
    education_meets = (
        required_education is None
        or (
            profile_education_level is not None
            and EDUCATION_RANK[profile_education_level]
            >= EDUCATION_RANK[required_education]
        )
    )

    return {
        "comparison_status": "completed",
        "input_quality": input_quality,
        "technology": {
            "job_count": len(job_technologies),
            "profile_count": len(profile_technologies),
            "matched_count": len(matched),
            "coverage": technology_coverage,
            "confidence": technology_confidence(len(job_technologies)),
            "matched": sorted(matched, key=str.casefold),
            "job_only": sorted(job_only, key=str.casefold),
        },
        "capability": {
            "job_count": len(job_capabilities),
            "profile_count": len(profile_capabilities),
            "matched_count": len(matched_capabilities),
            "coverage": capability_coverage,
            "confidence": technology_confidence(len(job_capabilities)),
            "matched": sorted(matched_capabilities, key=str.casefold),
            "job_only": sorted(job_only_capabilities, key=str.casefold),
        },
        "experience": {
            "required_years": required_years,
            "profile_years": profile_years,
            "difference": experience_difference,
            "ratio": experience_ratio,
            "meets": experience_meets,
        },
        "education": {
            "required": required_education,
            "profile": profile_education_level,
            "meets": education_meets,
        },
    }
