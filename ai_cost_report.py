from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from database import DEFAULT_DATABASE_FILE, apply_migrations, connect


DETAIL_COLUMNS = (
    ("Time (UTC)", "created_at"),
    ("Operation", "operation"),
    ("Model", "model"),
    ("Job", "job_uid"),
    ("Profile", "profile_name"),
    ("Input", "input_tokens"),
    ("Cached", "cached_input_tokens"),
    ("Output", "output_tokens"),
    ("Reasoning", "reasoning_output_tokens"),
    ("Total", "total_tokens"),
    ("Cost USD", "total_cost_usd"),
)


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return "unknown" if key == "total_cost_usd" else "-"
    if key == "created_at":
        return str(value).replace("T", " ")[:19]
    if key.endswith("_tokens"):
        return f"{int(value):,}"
    if key.endswith("_cost_usd") or key == "total_cost_usd":
        return f"${float(value):.6f}"
    return str(value)


def _print_table(
    columns: Sequence[tuple[str, str]], rows: Sequence[dict[str, Any]]
) -> None:
    if not rows:
        print("(none)")
        return

    formatted = [
        [_format_value(key, row.get(key)) for _, key in columns]
        for row in rows
    ]
    widths = [
        max(len(label), *(len(row[index]) for row in formatted))
        for index, (label, _) in enumerate(columns)
    ]
    print("  ".join(label.ljust(widths[index]) for index, (label, _) in enumerate(columns)))
    print("  ".join("-" * width for width in widths))
    for row in formatted:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _load_rows(database_file: Path | str) -> list[dict[str, Any]]:
    apply_migrations(database_file)
    with connect(database_file) as db:
        rows = db.execute(
            """
            SELECT created_at, operation, model, job_uid, profile_name,
                   input_tokens, cached_input_tokens, output_tokens,
                   reasoning_output_tokens, total_tokens, total_cost_usd
            FROM ai_costs
            ORDER BY created_at, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _summaries(
    rows: Sequence[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row[key])
        summary = grouped.setdefault(
            label,
            {
                key: label,
                "calls": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "unknown_costs": 0,
            },
        )
        summary["calls"] += 1
        for token_key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            summary[token_key] += int(row[token_key] or 0)
        if row["total_cost_usd"] is None:
            summary["unknown_costs"] += 1
        else:
            summary["total_cost_usd"] += float(row["total_cost_usd"])
    return sorted(grouped.values(), key=lambda row: row["total_cost_usd"], reverse=True)


def print_report(database_file: Path | str = DEFAULT_DATABASE_FILE) -> None:
    rows = _load_rows(database_file)
    print(f"AI cost report: {Path(database_file)}")
    print()
    print("All AI calls")
    _print_table(DETAIL_COLUMNS, rows)

    summary_columns = (
        ("Name", "name"),
        ("Calls", "calls"),
        ("Input", "input_tokens"),
        ("Cached", "cached_input_tokens"),
        ("Output", "output_tokens"),
        ("Total", "total_tokens"),
        ("Cost USD", "total_cost_usd"),
        ("Unknown", "unknown_costs"),
    )
    for title, key in (("By operation", "operation"), ("By model", "model")):
        print()
        print(title)
        summaries = _summaries(rows, key)
        for summary in summaries:
            summary["name"] = summary[key]
        _print_table(summary_columns, summaries)

    known_cost = sum(
        float(row["total_cost_usd"])
        for row in rows
        if row["total_cost_usd"] is not None
    )
    unknown_calls = sum(row["total_cost_usd"] is None for row in rows)
    print()
    print(
        f"Grand total: {len(rows)} calls, "
        f"{sum(int(row['total_tokens'] or 0) for row in rows):,} tokens, "
        f"${known_cost:.6f}"
    )
    if unknown_calls:
        print(
            f"Warning: {unknown_calls} call(s) use models without configured pricing "
            "and are excluded from the dollar total."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print all recorded AI calls and cost summaries."
    )
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=DEFAULT_DATABASE_FILE,
        help=f"SQLite database (default: {DEFAULT_DATABASE_FILE})",
    )
    args = parser.parse_args()
    try:
        print_report(args.database)
    except sqlite3.Error as error:
        raise SystemExit(f"Could not read AI costs: {error}") from error


if __name__ == "__main__":
    main()
