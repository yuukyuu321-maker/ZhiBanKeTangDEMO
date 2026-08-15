import json
import tempfile
import unittest
from pathlib import Path

from athena_domain import TextbookEdition
from athena_ingestion import ImportRequest, RenderMode, TextbookImporter
from reportlab.pdfgen import canvas


class TextbookImportIntegrationTests(unittest.TestCase):
    def _make_pdf(self, path: Path) -> None:
        document = canvas.Canvas(str(path), pagesize=(300, 400))
        document.drawString(30, 360, "Synthetic Science Textbook")
        document.drawString(30, 330, "Chapter 1 Magnetism")
        document.showPage()
        document.drawString(30, 360, "A magnetic field acts on an electric current.")
        document.drawString(30, 330, "Experiment steps and observations.")
        document.showPage()
        document.save()

    def test_import_is_idempotent_and_does_not_copy_source_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "synthetic.pdf"
            output = root / "imports"
            self._make_pdf(source)
            request = ImportRequest(
                pdf_path=source,
                output_root=output,
                edition=TextbookEdition(
                    edition_id="synthetic-science-8b-v1",
                    subject="science",
                    grade="8",
                    volume="2",
                    publisher="synthetic",
                    edition_label="v1",
                ),
                source_origin="generated test fixture",
                authorization_scope="synthetic test only",
                uploader="automated-test",
                render_mode=RenderMode.NONE,
            )

            first = TextbookImporter().import_pdf(request)
            second = TextbookImporter().import_pdf(request)

            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(first.bundle_path, second.bundle_path)
            self.assertEqual(first.report["page_count"], 2)
            self.assertEqual(first.report["pages_with_text"], 2)
            self.assertGreater(first.report["evidence_count"], 0)
            self.assertEqual(list(first.bundle_path.rglob("*.pdf")), [])
            self.assertTrue((first.bundle_path / "manifest.json").exists())
            self.assertTrue((first.bundle_path / "pages.jsonl").exists())
            self.assertTrue((first.bundle_path / "evidence.jsonl").exists())
            self.assertTrue((first.bundle_path / "import-report.json").exists())
            manifest_path = first.bundle_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["import_pipeline"]["version"] = "legacy"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "different pipeline version",
            ):
                TextbookImporter().import_pdf(request)
