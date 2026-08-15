import unittest

from athena_domain import EvidenceType
from athena_ingestion.extract import classify_evidence, group_words, make_page_evidence


class IngestionExtractTests(unittest.TestCase):
    def test_groups_words_and_creates_stable_page_anchor(self) -> None:
        words = [
            {"text": "Alpha", "x0": 10, "x1": 40, "top": 20, "bottom": 30},
            {"text": "Beta", "x0": 45, "x1": 70, "top": 20, "bottom": 30},
            {"text": "Gamma", "x0": 10, "x1": 50, "top": 34, "bottom": 44},
        ]
        blocks = group_words(words)
        anchors, _, _ = make_page_evidence(
            blocks=blocks,
            edition_id="synthetic-edition",
            source_sha256="a" * 64,
            pdf_page_index=2,
            page_label="1",
            printed_page=1,
            page_width=100,
            page_height=200,
            chapter_id=None,
            section_id=None,
        )
        repeated, _, _ = make_page_evidence(
            blocks=blocks,
            edition_id="synthetic-edition",
            source_sha256="a" * 64,
            pdf_page_index=2,
            page_label="1",
            printed_page=1,
            page_width=100,
            page_height=200,
            chapter_id=None,
            section_id=None,
        )
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].quote, "Alpha Beta\nGamma")
        self.assertEqual(anchors[0].evidence_id, repeated[0].evidence_id)
        self.assertLessEqual(anchors[0].bbox.x1, 100)

    def test_classifies_chinese_instructional_elements(self) -> None:
        self.assertEqual(classify_evidence("\u5b9e\u9a8c\u6b65\u9aa4"), EvidenceType.EXPERIMENT)
        self.assertEqual(classify_evidence("\u601d\u8003\u4e0e\u8ba8\u8bba"), EvidenceType.EXERCISE)
        self.assertEqual(
            classify_evidence("\u5316\u5b66\u65b9\u7a0b\u5f0f ="), EvidenceType.FORMULA
        )
