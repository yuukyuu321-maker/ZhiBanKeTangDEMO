import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "textbook-ingestion" / "src"))

from athena_ingestion.promotion import (  # noqa: E402
    PromotionConflictError,
    PromotionValidationError,
    bundle_content_sha256,
    promote_bundle,
    validate_approved_bundle,
)

from tests.textbook_bundle_fixture import (  # noqa: E402
    SOURCE_SHA256,
    build_approved_candidate,
)


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidate = build_approved_candidate(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validates_and_hashes_complete_approved_bundle(self) -> None:
        validated = validate_approved_bundle(self.candidate)

        self.assertEqual(validated.page_count, 2)
        self.assertEqual(validated.evidence_count, 1)
        self.assertEqual(len(bundle_content_sha256(self.candidate)), 64)

    def test_rejects_status_only_approval_without_matching_report(self) -> None:
        report_path = self.candidate / "import-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["status"] = "needs_review"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        with self.assertRaises(PromotionValidationError):
            validate_approved_bundle(self.candidate)

    def test_rejects_tampered_approved_review_content(self) -> None:
        review_path = next((self.candidate / "reviews").glob("review_*.json"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["notes"] = "tampered after approval"
        review_path.write_text(json.dumps(review), encoding="utf-8")

        with self.assertRaisesRegex(PromotionValidationError, "does not match review content"):
            validate_approved_bundle(self.candidate)

    def test_promotes_to_canonical_path_and_exact_rerun_is_idempotent(self) -> None:
        import_root = self.root / "imports"
        result = promote_bundle(self.candidate, import_root, "release-owner")
        rerun = promote_bundle(self.candidate, import_root, "release-owner")

        self.assertEqual(
            result.destination,
            (import_root / "edition-test" / SOURCE_SHA256).resolve(),
        )
        self.assertTrue((result.destination / "promotion.json").is_file())
        self.assertFalse(result.reused)
        self.assertTrue(rerun.reused)
        self.assertEqual(result.content_sha256, rerun.content_sha256)

    def test_legacy_collision_requires_explicit_archive_root(self) -> None:
        import_root = self.root / "imports"
        legacy = build_approved_candidate(self.root / "legacy", status="needs_review")
        destination = import_root / "edition-test" / SOURCE_SHA256
        destination.parent.mkdir(parents=True)
        legacy.replace(destination)

        with self.assertRaises(PromotionConflictError):
            promote_bundle(self.candidate, import_root, "release-owner")

        result = promote_bundle(
            self.candidate,
            import_root,
            "release-owner",
            self.root / "archive",
        )
        self.assertIsNotNone(result.archived_path)
        self.assertTrue(result.archived_path.is_dir())
        self.assertEqual(validate_approved_bundle(result.destination).page_count, 2)


if __name__ == "__main__":
    unittest.main()
