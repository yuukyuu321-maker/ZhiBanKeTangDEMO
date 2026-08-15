"""Human review gate for textbook import bundles."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .storage import read_json, write_json


REQUIRED_REVIEW_CATEGORIES = frozenset(
    {"cover", "contents", "chapter_start", "body", "experiment", "formula_or_figure", "appendix"}
)


def _page_records(bundle: Path) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    with (bundle / "pages.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                record = json.loads(line)
                records[int(record["pdf_page_index"])] = record
    return records


def record_review(bundle_path: Path, decision_path: Path) -> dict[str, Any]:
    bundle = bundle_path.resolve(strict=True)
    decision = read_json(decision_path.resolve(strict=True))
    manifest = read_json(bundle / "manifest.json")
    report = read_json(bundle / "import-report.json")
    if manifest.get("status") != "needs_review":
        raise ValueError("only needs_review bundles can receive an import review")

    reviewer = str(decision.get("reviewer", "")).strip()
    outcome = str(decision.get("decision", "")).strip()
    categories = {str(value) for value in decision.get("checked_categories", [])}
    sampled_pages = {int(value) for value in decision.get("sampled_pages", [])}
    issues = [str(value).strip() for value in decision.get("issues", []) if str(value).strip()]
    notes = str(decision.get("notes", "")).strip()
    if not reviewer:
        raise ValueError("reviewer must not be blank")
    if outcome not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    if not sampled_pages:
        raise ValueError("at least one sampled page is required")

    pages = _page_records(bundle)
    missing_pages = sampled_pages - pages.keys()
    if missing_pages:
        raise ValueError(f"sampled pages are missing: {sorted(missing_pages)}")
    for index in sampled_pages:
        render_uri = pages[index].get("render_uri")
        if not isinstance(render_uri, str) or not render_uri:
            raise ValueError(f"sampled page {index} has no render")
        render_path = (bundle / render_uri).resolve(strict=True)
        if not render_path.is_relative_to(bundle) or render_path.suffix.lower() != ".png":
            raise ValueError(f"sampled page {index} has an invalid render reference")

    if outcome == "approve":
        missing_categories = REQUIRED_REVIEW_CATEGORIES - categories
        if missing_categories:
            raise ValueError(
                f"required review categories are missing: {sorted(missing_categories)}"
            )
        if issues:
            raise ValueError("an approved review cannot contain unresolved issues")
    elif not issues:
        raise ValueError("a rejected review must describe at least one issue")

    reviewed_at = datetime.now(UTC).isoformat()
    source = manifest.get("source", {})
    source_sha256 = str(source.get("sha256", "")) if isinstance(source, dict) else ""
    review_record = {
        "schema_version": "athena.textbook-review.v1",
        "reviewer": reviewer,
        "decision": outcome,
        "reviewed_at": reviewed_at,
        "source_sha256": source_sha256,
        "checked_categories": sorted(categories),
        "sampled_pages": sorted(sampled_pages),
        "issues": issues,
        "notes": notes,
    }
    review_hash = sha256(
        json.dumps(review_record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    review_record["review_id"] = f"review_{review_hash[:24]}"
    review_path = bundle / "reviews" / f"{review_record['review_id']}.json"
    if review_path.exists():
        raise ValueError("this review decision is already recorded")
    write_json(review_path, review_record)

    history = list(manifest.get("review_history", []))
    history.append(
        {
            "review_id": review_record["review_id"],
            "decision": outcome,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
        }
    )
    manifest["review_history"] = history
    if outcome == "approve":
        manifest["status"] = "approved"
        report["status"] = "approved"
        report["manual_review_required"] = False
    write_json(bundle / "manifest.json", manifest)
    write_json(bundle / "import-report.json", report)
    return review_record
