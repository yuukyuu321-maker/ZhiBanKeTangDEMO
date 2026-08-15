import json
from pathlib import Path
import tempfile
import unittest

from athena_ingestion import REQUIRED_REVIEW_CATEGORIES, record_review
from athena_ingestion.storage import read_json, write_json, write_jsonl


class IngestionReviewTests(unittest.TestCase):
    def _bundle(self, root: Path) -> Path:
        bundle = root / "edition" / ("a" * 64)
        write_json(
            bundle / "manifest.json",
            {"status": "needs_review", "source": {"sha256": "a" * 64}},
        )
        write_json(
            bundle / "import-report.json",
            {"status": "needs_review", "manual_review_required": True},
        )
        pages = []
        for index in range(1, 8):
            render = bundle / "renders" / f"page-{index}.png"
            render.parent.mkdir(parents=True, exist_ok=True)
            render.write_bytes(b"\x89PNG\r\n\x1a\n")
            pages.append(
                {
                    "pdf_page_index": index,
                    "render_uri": f"renders/page-{index}.png",
                }
            )
        write_jsonl(bundle / "pages.jsonl", pages)
        return bundle

    def test_requires_complete_human_sample_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            decision = root / "decision.json"
            decision.write_text(
                json.dumps(
                    {
                        "reviewer": "teacher-reviewer",
                        "decision": "approve",
                        "checked_categories": ["cover"],
                        "sampled_pages": [1],
                        "issues": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                record_review(bundle, decision)

    def test_approval_updates_status_and_writes_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            decision = root / "decision.json"
            decision.write_text(
                json.dumps(
                    {
                        "reviewer": "teacher-reviewer",
                        "decision": "approve",
                        "checked_categories": sorted(REQUIRED_REVIEW_CATEGORIES),
                        "sampled_pages": list(range(1, 8)),
                        "issues": [],
                        "notes": "synthetic review",
                    }
                ),
                encoding="utf-8",
            )
            review = record_review(bundle, decision)
            self.assertTrue((bundle / "reviews" / f"{review['review_id']}.json").exists())
            self.assertEqual(read_json(bundle / "manifest.json")["status"], "approved")
            self.assertFalse(read_json(bundle / "import-report.json")["manual_review_required"])
