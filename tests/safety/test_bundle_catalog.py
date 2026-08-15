from pathlib import Path
import tempfile
import unittest

from app.service import BundleCatalog, BundleNotReadableError
from athena_ingestion.storage import write_json, write_jsonl


class BundleCatalogSafetyTests(unittest.TestCase):
    def _bundle(self, root: Path, status: str = "needs_review") -> tuple[str, str]:
        edition_id = "synthetic-edition"
        digest = "a" * 64
        bundle = root / edition_id / digest
        write_json(
            bundle / "manifest.json",
            {"status": status, "source": {"sha256": digest}},
        )
        write_json(bundle / "import-report.json", {"status": status})
        write_jsonl(
            bundle / "pages.jsonl",
            [{"pdf_page_index": 1, "render_uri": None}],
        )
        write_jsonl(
            bundle / "evidence.jsonl",
            [
                {
                    "evidence_id": "ev_1",
                    "pdf_page_index": 1,
                    "page_label": "1",
                    "quote": "authorized evidence only",
                }
            ],
        )
        return edition_id, digest

    def test_needs_review_is_denied_by_default_and_explicitly_allowed_locally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            edition_id, digest = self._bundle(root)
            with self.assertRaises(BundleNotReadableError):
                BundleCatalog(root).search(edition_id, digest, "evidence")
            results = BundleCatalog(root, allow_needs_review=True).search(
                edition_id, digest, "evidence"
            )
            self.assertEqual(results[0]["evidence"]["evidence_id"], "ev_1")

    def test_rejects_path_traversal_and_forged_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            edition_id, digest = self._bundle(root, status="approved")
            catalog = BundleCatalog(root)
            with self.assertRaises(ValueError):
                catalog.describe("../outside", digest)
            with self.assertRaises(ValueError):
                catalog.describe(edition_id, "not-a-digest")
