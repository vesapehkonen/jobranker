from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .text import target_job_text


# Canonical engineering capability -> explicit wording variants. These are
# practices and architectural competencies, not products or technologies.
CAPABILITY_ALIASES: dict[str, tuple[str, ...]] = {
    "API Development": ("API development", "API design", "develop APIs", "design APIs"),
    "Agile Development": ("Agile development", "Agile methodologies", "Agile environment", "Scrum"),
    "Automation": ("workflow automation", "process automation", "engineering automation", "automating workflows"),
    "CI/CD": ("CI/CD", "CI CD", "continuous integration", "continuous delivery", "continuous deployment"),
    "Cloud Architecture": ("cloud architecture", "cloud-native architecture", "cloud native architecture", "cloud solutions architecture"),
    "Code Review": ("code review", "code reviews", "peer review of code"),
    "Containerization": ("containerization", "containerisation", "containerized", "containerised", "container orchestration"),
    "Data Pipelines": ("data pipeline", "data pipelines", "data ingestion pipeline", "ETL pipeline", "ELT pipeline"),
    "DevOps": ("DevOps", "development and operations"),
    "Distributed Systems": ("distributed system", "distributed systems", "distributed computing"),
    "Event-Driven Architecture": ("event-driven architecture", "event driven architecture", "event-driven systems", "event driven systems"),
    "High Availability": ("high availability", "highly available", "fault tolerant", "fault-tolerant"),
    "Infrastructure as Code": ("infrastructure as code", "infrastructure-as-code", "IaC"),
    "Integration Testing": ("integration testing", "integration tests", "end-to-end testing", "end to end testing", "E2E testing"),
    "Machine Learning": ("machine learning", "ML engineering", "ML models", "predictive modeling"),
    "Microservices": ("microservice", "microservices", "micro-service", "micro-services", "service-oriented architecture", "service oriented architecture"),
    "Observability": ("observability", "distributed tracing", "structured logging", "metrics and alerting", "logging and monitoring"),
    "Performance Optimization": ("performance optimization", "performance tuning", "performance engineering", "optimize performance", "optimise performance"),
    "Production Support": ("production support", "on-call rotation", "on call rotation", "incident response", "operational support"),
    "Release Management": ("release management", "release engineering", "release automation", "deployment automation"),
    "Requirements Analysis": ("requirements analysis", "requirements gathering", "technical requirements", "business requirements analysis"),
    "Root Cause Analysis": ("root cause analysis", "root-cause analysis", "RCA"),
    "Scalability": ("scalability", "highly scalable", "scalable systems", "scalable services", "scale distributed systems"),
    "Security Engineering": ("security engineering", "secure coding", "application security", "security best practices", "threat modeling"),
    "System Design": ("system design", "systems design", "software architecture", "solution design", "technical design"),
    "Test Automation": ("test automation", "automated testing", "automated tests", "automating tests"),
    "Troubleshooting": ("troubleshooting", "troubleshoot", "debugging", "defect triage", "problem diagnosis"),
    "Unit Testing": ("unit testing", "unit tests", "unit test"),
}


@lru_cache(maxsize=None)
def _pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.I)


def _context(text: str, start: int, end: int) -> str:
    left = max(text.rfind("\n", 0, start), text.rfind(".", 0, start))
    right_candidates = [position for position in (text.find("\n", end), text.find(".", end)) if position >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return re.sub(r"\s+", " ", text[left + 1:right].strip())


def extract_capabilities(text: str) -> list[dict[str, Any]]:
    text = target_job_text(text)
    found = []
    for canonical, aliases in CAPABILITY_ALIASES.items():
        matches = [
            match
            for alias in aliases
            for match in _pattern(alias).finditer(text)
        ]
        if not matches:
            continue
        matches.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
        distinct = []
        for match in matches:
            if any(match.start() < existing.end() and match.end() > existing.start() for existing in distinct):
                continue
            distinct.append(match)
        found.append({
            "name": canonical,
            "aliases_found": list(dict.fromkeys(match.group(0) for match in distinct)),
            "occurrences": len(distinct),
            "contexts": list(dict.fromkeys(
                _context(text, match.start(), match.end()) for match in distinct
            ))[:3],
        })
    return sorted(found, key=lambda item: item["name"].casefold())
