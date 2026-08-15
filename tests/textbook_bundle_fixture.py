"""Small approved textbook bundle fixture shared by unit and integration tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "a" * 64


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def build_approved_candidate(root: Path, *, status: str = "approved") -> Path:
    bundle = root / "candidate"
    bundle.mkdir(parents=True)
    pages = [
        {
            "pdf_page_index": index,
            "page_label": str(index),
            "printed_page": index,
            "width": 100.0,
            "height": 200.0,
            "render_uri": f"renders/page-{index:04d}.png",
            "quality_status": "passed",
        }
        for index in (1, 2)
    ]
    evidence = [
        {
            "evidence_id": "ev_" + "c" * 24,
            "textbook_edition_id": "edition-test",
            "source_sha256": SOURCE_SHA256,
            "pdf_page_index": 1,
            "chapter_id": None,
            "section_id": None,
            "evidence_type": "body",
            "quote": "测试证据",
            "content_hash": "d" * 64,
            "bbox": {"x0": 1.0, "y0": 2.0, "x1": 10.0, "y1": 12.0},
            "bbox_coordinate_system": "pdf-top-left-points",
        }
    ]
    _write_jsonl(bundle / "pages.jsonl", pages)
    _write_jsonl(bundle / "evidence.jsonl", evidence)
    for index in (1, 2):
        render = bundle / "renders" / f"page-{index:04d}.png"
        render.parent.mkdir(parents=True, exist_ok=True)
        render.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    review = {
        "schema_version": "athena.textbook-review.v1",
        "reviewer": "fixture-owner",
        "decision": "approve",
        "reviewed_at": "2026-08-13T00:00:00+00:00",
        "source_sha256": SOURCE_SHA256,
        "checked_categories": [
            "appendix",
            "body",
            "chapter_start",
            "contents",
            "cover",
            "experiment",
            "formula_or_figure",
        ],
        "sampled_pages": [1, 2],
        "issues": [],
        "notes": "fixture approval",
    }
    review_hash = hashlib.sha256(
        json.dumps(review, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    review_id = f"review_{review_hash[:24]}"
    review["review_id"] = review_id

    _write_json(
        bundle / "manifest.json",
        {
            "schema_version": "athena.textbook-manifest.v1",
            "status": status,
            "edition": {
                "edition_id": "edition-test",
                "subject": "科学",
                "grade": "八年级",
                "volume": "下册",
                "publisher": "测试出版社",
                "edition_label": "测试版",
            },
            "import_pipeline": {"name": "fixture", "version": "2.0-test"},
            "source": {
                "sha256": SOURCE_SHA256,
                "original_filename": "textbook.pdf",
                "byte_size": 1024,
                "page_count": 2,
                "authorization_scope": "仅限测试",
            },
            "artifacts": {
                "pages": "pages.jsonl",
                "evidence": "evidence.jsonl",
                "report": "import-report.json",
                "renders": "renders/",
            },
            "review_history": [
                {
                    "review_id": review_id,
                    "decision": "approve",
                    "reviewer": "fixture-owner",
                    "reviewed_at": "2026-08-13T00:00:00+00:00",
                }
            ],
        },
    )
    _write_json(
        bundle / "import-report.json",
        {
            "edition_id": "edition-test",
            "source_sha256": SOURCE_SHA256,
            "status": status,
            "page_count": 2,
            "rendered_page_count": 2,
            "evidence_count": 1,
            "manual_review_required": status != "approved",
        },
    )
    _write_json(
        bundle / "reviews" / f"{review_id}.json",
        review,
    )
    return bundle
