from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import load_evaluation_references, load_matching_inputs
from .evaluate import write_evaluation
from .lexical import LexicalMatcher
from .semantic import SemanticMatcher, load_sentence_transformer


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare local job/profile matchers")
    parser.add_argument("--database", type=Path, default=Path("data/jobranker.db"))
    parser.add_argument("--output", type=Path, default=Path("experiments/local_matching/output"))
    parser.add_argument("--method", choices=("lexical", "semantic", "all"), default="all")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--status", help="Only include jobs with this application status")
    parser.add_argument("--profile", help="Only compare against this original resume profile")
    parser.add_argument("--limit", type=int, help="Limit jobs for a quick test")
    args = parser.parse_args()

    jobs, profiles = load_matching_inputs(
        args.database, status=args.status, profile_name=args.profile
    )
    if args.limit:
        jobs = jobs[:args.limit]
    if not jobs or not profiles:
        raise SystemExit("No cleaned jobs or enabled profiles with resume text were found")

    lexical = LexicalMatcher(jobs, profiles) if args.method in {"lexical", "all"} else None
    semantic = None
    if args.method in {"semantic", "all"}:
        semantic = SemanticMatcher(load_sentence_transformer(args.model))
        semantic.prime([job.text for job in jobs] + [profile.text for profile in profiles])

    rows: list[dict[str, object]] = []
    for job in jobs:
        for profile in profiles:
            lexical_result = lexical.compare(job.text, profile.text) if lexical else None
            semantic_score = semantic.compare(job.text, profile.text) if semantic else None
            lexical_score = lexical_result.score if lexical_result else None
            hybrid_score = (
                0.4 * lexical_score + 0.6 * semantic_score
                if lexical_score is not None and semantic_score is not None else None
            )
            rows.append({
                "job_uid": job.job_uid, "title": job.title, "status": job.status,
                "profile_name": profile.profile_name,
                "lexical_score": round(lexical_score, 3) if lexical_score is not None else None,
                "semantic_score": round(semantic_score, 3) if semantic_score is not None else None,
                "hybrid_score": round(hybrid_score, 3) if hybrid_score is not None else None,
                "shared_terms": ", ".join(lexical_result.shared_terms) if lexical_result else "",
            })

    references = load_evaluation_references(args.database)
    summary = write_evaluation(rows, references, args.output)
    print(json.dumps(summary, indent=2))
    print(f"Wrote results to {args.output}")


if __name__ == "__main__":
    main()
