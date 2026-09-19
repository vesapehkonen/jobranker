"""Deterministic pre-AI filtering against the merged base profile."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math

from .capabilities import extract_capabilities
from .comparison import compare
from .qualifications import EDUCATION_RANK, extract_education, extract_experience
from .quality import validate_job_text
from .technologies import TECHNOLOGY_ALIASES, extract_technologies, flatten_profile_text

EXTRACTOR_VERSION = 2
RULE_VERSION = 1
RULES = {"experience_multiplier": 1.15, "minimum_technology_count": 3,
         "minimum_technology_coverage": 0.15}


def extract_job_description(description):
    quality = validate_job_text(description)
    result = {"input_quality": quality}
    if quality["status"] == "valid":
        result.update({
            "technologies": extract_technologies(description),
            "capabilities": extract_capabilities(description),
            "education": extract_education(description),
            "experience": extract_experience(description),
        })
    return result


def adapt_base_profile(profile):
    """Normalize the merged AI schema for the shared comparison function."""
    text = flatten_profile_text(profile)
    education = profile.get("education")
    if not isinstance(education, list):
        raise ValueError("Base profile education must be an array")
    levels = extract_education("\n".join("Education degree: " + flatten_profile_text(item) for item in education))["levels_found"]
    years = profile.get("years_experience")
    if years is not None and (isinstance(years, bool) or not isinstance(years, (int, float))
                              or not math.isfinite(years) or years < 0):
        raise ValueError("Base profile years_experience must be a nonnegative number or null")
    technologies = {item["name"]: item for item in extract_technologies(text)}
    # A named skill is explicit evidence even when an ambiguous name (Go, C)
    # would need contextual wording in ordinary prose.
    aliases = {alias.casefold(): name for name, variants in TECHNOLOGY_ALIASES.items()
               for alias in (name, *variants)}
    for field in ("technical_skills", "strongest_skills", "cloud_infrastructure", "programming_languages", "tools"):
        for value in profile.get(field, []):
            if isinstance(value, str) and value.strip().casefold() in aliases:
                name = aliases[value.strip().casefold()]
                technologies.setdefault(name, {"name": name, "contexts": [f"{field}: {value}"]})
    return {
        "technologies": sorted(technologies.values(), key=lambda item: item["name"]),
        "capabilities": extract_capabilities(text),
        "education": {"highest_level": max(levels, key=EDUCATION_RANK.get) if levels else None},
        "experience": {"total_years": years},
    }


def evaluate_extraction(extracted, profile):
    """Apply all rules; uncertain profile qualifications do not imply a mismatch."""
    comparison = compare(extracted, profile)
    reasons = []
    education = comparison["education"]
    if education["required"] is not None and education["profile"] is not None and not education["meets"]:
        reasons.append({"code": "education_not_met", "required": education["required"],
                        "actual": education["profile"],
                        "message": f"Required education: {education['required']}; profile: {education['profile']}."})
    experience = comparison["experience"]
    required, actual = experience["required_years"], experience["profile_years"]
    if required is not None and actual is not None:
        limit = Decimal(str(actual)) * Decimal(str(RULES["experience_multiplier"]))
        if Decimal(str(required)) > limit:
            reasons.append({"code": "experience_not_met", "required": required,
                            "actual": actual, "maximum_allowed": float(limit),
                            "message": f"Required experience: {required} years; profile: {actual}; allowed maximum: {limit}."})
    technology = comparison["technology"]
    count, matched = technology["job_count"], technology["matched_count"]
    # Use counts, not the comparison's rounded display coverage.
    if count >= RULES["minimum_technology_count"] and Decimal(matched) < Decimal(count) * Decimal(str(RULES["minimum_technology_coverage"])):
        reasons.append({"code": "technology_coverage_low", "matched_count": matched,
                        "job_count": count, "coverage": matched / count,
                        "minimum_coverage": RULES["minimum_technology_coverage"],
                        "message": f"Technology coverage: {matched}/{count} ({matched / count:.1%}); minimum: 15%."})
    return comparison, reasons


def filter_description(description, base):
    if not base or base.get("status") != "ready" or not base.get("profile"):
        raise ValueError("A current merged base profile is required; run merge_resume_profiles.py")
    if not isinstance(description, str):
        raise ValueError("Job description must be text")
    extracted = extract_job_description(description)
    result = {
        "rule_version": RULE_VERSION, "extractor_version": EXTRACTOR_VERSION,
        "rules": dict(RULES), "base_sources": base["sources"],
        "base_merged_at": base["merged_at"],
        "description_hash": hashlib.sha256(description.encode()).hexdigest(),
        "extraction": extracted, "comparison": None, "reasons": [],
    }
    if extracted["input_quality"]["status"] == "invalid":
        code = "missing_description" if not description.strip() else "invalid_description"
        result["reasons"] = [{"code": code, "details": extracted["input_quality"]["reasons"],
                              "message": "Missing job description." if code == "missing_description" else
                              "Invalid job description: " + ", ".join(extracted["input_quality"]["reasons"])}]
    else:
        # Keep the original extraction for review. The experiment's minimums
        # include unspecified mentions; production rejection uses required ones.
        requirements = json.loads(json.dumps(extracted))
        education = requirements["education"]
        required_levels = [m["level"] for m in education["mentions"] if m["classification"] == "required" and m["counts_as_minimum"]]
        education["minimum_level"] = (
            min(required_levels, key=EDUCATION_RANK.get)
            if required_levels else None
        )
        experience = requirements["experience"]
        required_years = [m["minimum_years"] for m in experience["mentions"] if m["classification"] == "required"]
        experience["minimum_years"] = max(required_years) if required_years else None
        normalized_profile = adapt_base_profile(base["profile"])
        result["base_comparison_profile"] = normalized_profile
        result["comparison"], result["reasons"] = evaluate_extraction(requirements, normalized_profile)
    result["outcome"] = "filtered_out" if result["reasons"] else "passed"
    return result
