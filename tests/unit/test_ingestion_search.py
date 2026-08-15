import unittest

from athena_ingestion import EvidenceIndex


class IngestionSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = EvidenceIndex(
            [
                {
                    "evidence_id": "ev_magnetic",
                    "pdf_page_index": 9,
                    "page_label": "2",
                    "quote": (
                        "\u78c1\u573a\u5bf9\u901a\u7535\u5bfc\u7ebf"
                        "\u4f1a\u4ea7\u751f\u529b\u7684\u4f5c\u7528"
                    ),
                },
                {
                    "evidence_id": "ev_plant",
                    "pdf_page_index": 88,
                    "page_label": "81",
                    "quote": "\u690d\u7269\u7684\u6839\u5438\u6536\u6c34\u5206",
                },
            ]
        )

    def test_ranks_exact_chinese_phrase_and_preserves_anchor(self) -> None:
        results = self.index.search("\u901a\u7535\u5bfc\u7ebf", limit=5)
        self.assertEqual(results[0].evidence["evidence_id"], "ev_magnetic")
        self.assertEqual(results[0].evidence["page_label"], "2")

    def test_rejects_blank_query_and_invalid_limit(self) -> None:
        with self.assertRaises(ValueError):
            self.index.search(" ")
        with self.assertRaises(ValueError):
            self.index.search("plant", limit=0)
