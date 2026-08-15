from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))

from athena_domain import BoundingBox, EvidenceAnchor, EvidenceType  # noqa: E402


class EvidenceAnchorTests(unittest.TestCase):
    def test_accepts_page_aware_anchor(self) -> None:
        anchor = EvidenceAnchor(
            evidence_id="ev-1",
            textbook_edition_id="science-8b-synthetic",
            source_sha256="a" * 64,
            pdf_page_index=9,
            page_label="2",
            printed_page=2,
            bbox=BoundingBox(10, 20, 300, 500),
            evidence_type=EvidenceType.BODY,
            quote="合成教材证据。",
            content_hash="b" * 64,
        )
        self.assertEqual(anchor.page_label, "2")
        self.assertEqual(anchor.printed_page, 2)

    def test_rejects_forged_or_invalid_source_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            EvidenceAnchor(
                evidence_id="ev-2",
                textbook_edition_id="science-8b-synthetic",
                source_sha256="not-a-digest",
                pdf_page_index=1,
                page_label="1",
                bbox=BoundingBox(0, 0, 10, 10),
                evidence_type=EvidenceType.BODY,
                quote="合成证据。",
                content_hash="b" * 64,
            )


if __name__ == "__main__":
    unittest.main()
