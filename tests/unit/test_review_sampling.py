import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "textbook-ingestion" / "src"))

from athena_ingestion.review_sampling import (  # noqa: E402
    build_review_plan,
    warning_signature,
    write_review_plan,
)
from athena_ingestion.storage import read_json, write_json, write_jsonl  # noqa: E402


class ReviewSamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.temp.name) / "bundle"
        write_json(
            self.bundle / "manifest.json",
            {
                "status": "needs_review",
                "edition": {
                    "edition_id": "edition-test",
                    "subject": "science",
                    "grade": "8",
                    "volume": "2",
                    "publisher": "publisher",
                    "edition_label": "2026",
                },
                "source": {"sha256": "a" * 64},
            },
        )
        write_json(
            self.bundle / "import-report.json",
            {
                "status": "needs_review",
                "source_sha256": "a" * 64,
                "manual_review_required": True,
            },
        )
        pages = []
        evidence = []
        for index in range(1, 31):
            warnings = []
            quality = "passed"
            text_count = 100
            if index % 2 == 0:
                warnings = ["renderer_warning:Syntax Error: Malformed JP2 file format"]
                quality = "warning"
            if index == 3:
                warnings = ["no_extractable_text"]
                quality = "warning"
                text_count = 0
            if index == 7:
                warnings = ["renderer_warning:Couldn't find a font for Symbol"]
                quality = "warning"
                text_count = 0
            pages.append(
                {
                    "pdf_page_index": index,
                    "page_label": str(index),
                    "printed_page": index,
                    "width": 100,
                    "height": 200,
                    "render_uri": f"renders/page-{index:04d}.png",
                    "text_method": "embedded",
                    "quality_status": quality,
                    "warnings": warnings,
                    "text_character_count": text_count,
                    "image_count": 1 if index % 2 == 0 else 0,
                    "vector_element_count": 5,
                    "evidence_count": 1 if text_count else 0,
                }
            )
            if text_count:
                quote = "ordinary body"
                if index == 4:
                    quote = "目录 第一章 第二章"
                elif index == 6:
                    quote = "探究实验活动"
                elif index == 28:
                    quote = "附录 元素周期表"
                evidence.append(
                    {
                        "pdf_page_index": index,
                        "quote": quote,
                    }
                )
        write_jsonl(self.bundle / "pages.jsonl", pages)
        write_jsonl(self.bundle / "evidence.jsonl", evidence)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_warning_signatures_are_stable(self) -> None:
        self.assertEqual(
            warning_signature("renderer_warning:Malformed JP2 data"),
            "renderer_malformed_jp2",
        )
        self.assertEqual(
            warning_signature("renderer_warning:missing font"),
            "renderer_font_warning",
        )

    def test_plan_is_deterministic_and_keeps_status_unchanged(self) -> None:
        first = build_review_plan(
            self.bundle,
            minimum_warning_pages=5,
            warning_ratio=0.10,
        )
        second = build_review_plan(
            self.bundle,
            minimum_warning_pages=5,
            warning_ratio=0.10,
        )

        self.assertEqual(first, second)
        indexes = {item["pdf_page_index"] for item in first["selected_pages"]}
        self.assertTrue({3, 7}.issubset(indexes))
        self.assertEqual(
            set(first["required_categories"]),
            {
                "appendix",
                "body",
                "chapter_start",
                "contents",
                "cover",
                "experiment",
                "formula_or_figure",
            },
        )
        self.assertEqual(read_json(self.bundle / "manifest.json")["status"], "needs_review")

    def test_writes_json_plan_and_chinese_checklist_outside_bundle(self) -> None:
        output = Path(self.temp.name) / "output"
        write_review_plan(self.bundle, output, minimum_warning_pages=5)

        self.assertTrue((output / "review-plan.json").is_file())
        checklist = (output / "review-checklist.md").read_text(encoding="utf-8")
        self.assertIn("教材导入人工复核清单", checklist)
        self.assertFalse((self.bundle / "review-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
