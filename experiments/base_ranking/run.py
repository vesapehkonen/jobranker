"""Compare nano and mini on a frozen sample without modifying production data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
from types import SimpleNamespace

from ai_costs import prices_for_model
from database import DEFAULT_DATABASE_FILE, utc_now
from experiments.local_matching.data import connect_read_only
from rank_job_ai import rank_profile

DEFAULT_OUTPUT = Path(__file__).parent / "output"


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def prepare(database, output, limit, seed):
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    with connect_read_only(database) as db:
        base = db.execute("SELECT * FROM base_profile WHERE id=1").fetchone()
        if not base or base["status"] != "ready" or not base["profile_json"]:
            raise ValueError("A current merged base profile is required to prepare the sample")
        rows = db.execute("""
            SELECT j.job_uid, j.page_title, j.application_status, a.structured_json,
                   b.evaluation_json, q.phase
            FROM jobs j JOIN job_artifacts a USING(job_uid)
            LEFT JOIN base_rank_evaluations b ON b.id=(
                SELECT MAX(id) FROM base_rank_evaluations WHERE job_uid=j.job_uid)
            LEFT JOIN queue_items q ON q.id=(SELECT MAX(id) FROM queue_items WHERE job_uid=j.job_uid)
            WHERE a.structured_json IS NOT NULL ORDER BY j.job_uid
        """).fetchall()
    groups = {name: [] for name in ("applied", "borderline", "filtered", "other")}
    for row in rows:
        structured = json.loads(row["structured_json"])
        if not isinstance(structured, dict) or not structured:
            continue
        prior = json.loads(row["evaluation_json"] or "{}")
        score = prior.get("score")
        tags = []
        if row["application_status"] == "applied":
            tags.append("applied")
        if isinstance(score, (int, float)) and 65 <= score <= 85:
            tags.append("borderline")
        if row["phase"] in ("filtered_out", "base_filtered"):
            tags.append("filtered")
        if not tags:
            tags.append("other")
        groups[tags[0]].append({"job_uid": row["job_uid"], "title": row["page_title"],
                               "application_status": row["application_status"], "tags": tags,
                               "previous_base_score": score, "structured": structured})
    rng = random.Random(seed)
    for group in groups.values():
        rng.shuffle(group)
    selected = []
    while len(selected) < limit and any(groups.values()):
        for group in groups.values():
            if group and len(selected) < limit:
                selected.append(group.pop())
    if not selected:
        raise ValueError("No jobs with saved AI extraction are available")
    manifest = {"version": 1, "created_at": utc_now(), "seed": seed,
                "requested_limit": limit, "base_profile": json.loads(base["profile_json"]),
                "base_sources": json.loads(base["sources_json"]), "base_merged_at": base["merged_at"],
                "jobs": selected}
    write_json(manifest_path, manifest)
    return manifest


class CachedResponses:
    """Cache the exact request and raw response before parsing or validation."""
    def __init__(self, directory, client_factory):
        self.directory = directory
        self.client_factory = client_factory
        self.client = None
        self.last = None
        self.new_calls = 0
        self.hits = 0

    def create(self, **request):
        key = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.directory / f"{key}.json"
        if path.exists():
            record = json.loads(path.read_text())
            self.hits += 1
        else:
            if self.client is None:
                self.client = self.client_factory()
            response = self.client.responses.create(**request)
            usage = getattr(response, "usage", None)
            usage = usage.model_dump() if usage is not None else {}
            record = {"request": request, "output_text": response.output_text,
                      "model": getattr(response, "model", request["model"]),
                      "response_id": getattr(response, "id", None), "usage": usage,
                      "created_at": utc_now()}
            write_json(path, record)
            self.new_calls += 1
        self.last = record
        return SimpleNamespace(output_text=record["output_text"], usage=None)


def usage_summary(record):
    if not record:
        return {"tokens": 0, "cost_usd": None}
    usage = record["usage"]
    input_tokens, output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cached = min(input_tokens, (usage.get("input_tokens_details") or {}).get("cached_tokens", 0))
    prices = prices_for_model(record["model"])
    cost = (((input_tokens - cached) * prices.input_per_million + cached * prices.cached_input_per_million
             + output_tokens * prices.output_per_million) / 1_000_000) if prices and usage else None
    return {"tokens": usage.get("total_tokens", input_tokens + output_tokens), "cost_usd": cost}


def reports(output, rows, nano_model, mini_model, responses):
    columns = ["job_uid", "title", "application_status", "tags", "nano_score", "mini_score",
               "nano_passes", "mini_passes", "nano_tokens", "mini_tokens", "nano_cost_usd", "mini_cost_usd", "error"]
    valid = [r for r in rows if r["nano_score"] is not None and r["mini_score"] is not None]
    disagreements = [r for r in valid if r["nano_passes"] != r["mini_passes"]]
    disagreements.sort(key=lambda r: (not (r["mini_passes"] and not r["nano_passes"]),
                                      r["application_status"] != "applied", -abs(r["mini_score"] - r["nano_score"])))
    for filename, values in (("scores.csv", rows), ("disagreements.csv", disagreements)):
        with (output / filename).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(values)
    summary = {"nano_model": nano_model, "mini_model": mini_model, "mini_threshold": 75,
               "completed_pairs": len(valid), "disagreements": len(disagreements),
               "new_calls_this_run": responses.new_calls, "cache_hits_this_run": responses.hits,
               "thresholds": []}
    for threshold in (65, 70, 75):
        rejected = [r for r in valid if r["nano_score"] < threshold]
        summary["thresholds"].append({"nano_threshold": threshold, "nano_rejected": len(rejected),
                                      "mini_pass_nano_reject": sum(r["mini_score"] >= 75 for r in rejected),
                                      "applied_jobs_rejected": sum(r["application_status"] == "applied" for r in rejected)})
    for model in ("nano", "mini"):
        costs = [r[f"{model}_cost_usd"] for r in rows]
        summary[model] = {"tokens": sum(r[f"{model}_tokens"] for r in rows),
                          "known_cost_usd": sum(c for c in costs if c is not None),
                          "unpriced_results": sum(c is None for c in costs)}
    write_json(output / "summary.json", summary)
    return summary


def run_comparison(manifest, output, nano_model, mini_model, client_factory):
    cache = output / "cache"
    cache.mkdir(exist_ok=True)
    responses = CachedResponses(cache, client_factory)
    client = SimpleNamespace(responses=responses)
    rows = []
    results = []
    for job in manifest["jobs"]:
        row = {key: job[key] for key in ("job_uid", "title", "application_status")}
        row.update(tags=",".join(job["tags"]), error="")
        details = {"job_uid": job["job_uid"]}
        for label, model in (("nano", nano_model), ("mini", mini_model)):
            responses.last = None
            try:
                ranking = rank_profile(client, "merged_base", manifest["base_profile"], job["structured"],
                                       model=model, track_usage=False)
                row[f"{label}_score"] = ranking["overall_fit_score"]
                row[f"{label}_passes"] = ranking["overall_fit_score"] >= 75
                details[label] = ranking
            except Exception as exc:
                row[f"{label}_score"] = None
                row[f"{label}_passes"] = None
                row["error"] += f"{label}: {exc}; "
            usage = usage_summary(responses.last)
            row[f"{label}_tokens"] = usage["tokens"]
            row[f"{label}_cost_usd"] = usage["cost_usd"]
        rows.append(row)
        results.append(details)
        write_json(output / "rankings.json", results)
        summary = reports(output, rows, nano_model, mini_model, responses)
        print(f"[{len(rows)}/{len(manifest['jobs'])}] {job['job_uid']}: nano={row['nano_score']} mini={row['mini_score']} {row['error']}", flush=True)
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--nano-model", default="gpt-5.4-nano")
    parser.add_argument("--mini-model", default="gpt-5.4-mini")
    parser.add_argument("--run", action="store_true", help="Make paid ranking calls for uncached inputs")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        manifest = prepare(args.database, args.output, args.limit, args.seed)
        print(f"Frozen sample: {len(manifest['jobs'])} jobs; manifest: {args.output / 'manifest.json'}")
        if not args.run:
            print("Prepared only. Add --run to compare models (up to two paid calls per job). Existing manifests are reused.")
            return
        from openai import OpenAI
        rows, summary = run_comparison(manifest, args.output, args.nano_model, args.mini_model, OpenAI)
        print(json.dumps(summary, indent=2))
        if any(row["error"] for row in rows):
            raise SystemExit(1)
    except Exception as exc:
        parser.exit(1, f"Comparison failed: {exc}\n")


if __name__ == "__main__":
    main()
