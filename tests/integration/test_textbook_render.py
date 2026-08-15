import json
import tempfile
import unittest
from pathlib import Path

from athena_domain import TextbookEdition
from athena_ingestion import ImportRequest, RenderMode, TextbookImporter
from athena_ingestion.render import _renderer_path
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


class TextbookRenderIntegrationTests(unittest.TestCase):
    def test_render_uses_short_scratch_path_for_long_bundle_path(self) -> None:
        if _renderer_path() is None:
            self.skipTest("pdftoppm is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "synthetic.pdf"
            document = canvas.Canvas(str(source), pagesize=(300, 400))
            document.drawString(30, 360, "Synthetic rendered page")
            document.showPage()
            document.save()
            output = root / ("long-output-segment-" * 7) / "imports"
            result = TextbookImporter().import_pdf(
                ImportRequest(
                    pdf_path=source,
                    output_root=output,
                    edition=TextbookEdition(
                        edition_id="synthetic-render-v1",
                        subject="science",
                        grade="8",
                        volume="2",
                        publisher="synthetic",
                        edition_label="v1",
                    ),
                    source_origin="generated test fixture",
                    authorization_scope="synthetic test only",
                    uploader="automated-test",
                    render_mode=RenderMode.ALL,
                    render_dpi=72,
                )
            )
            self.assertEqual(result.report["rendered_page_count"], 1)
            self.assertEqual(len(list((result.bundle_path / "renders").glob("*.png"))), 1)

    def test_import_respects_cropbox_for_render_dimensions_and_evidence(self) -> None:
        if _renderer_path() is None:
            self.skipTest("pdftoppm is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media_source = root / "media.pdf"
            source = root / "cropped.pdf"
            document = canvas.Canvas(str(media_source), pagesize=(600, 400))
            document.drawString(30, 360, "HIDDEN OUTSIDE CROP")
            document.drawString(330, 360, "VISIBLE INSIDE CROP")
            document.showPage()
            document.save()

            reader = PdfReader(str(media_source))
            page = reader.pages[0]
            page.cropbox.lower_left = (300, 0)
            page.cropbox.upper_right = (600, 400)
            writer = PdfWriter()
            writer.add_page(page)
            with source.open("wb") as stream:
                writer.write(stream)

            result = TextbookImporter().import_pdf(
                ImportRequest(
                    pdf_path=source,
                    output_root=root / "imports",
                    edition=TextbookEdition(
                        edition_id="synthetic-cropbox-v2",
                        subject="science",
                        grade="8",
                        volume="2",
                        publisher="synthetic",
                        edition_label="v2",
                    ),
                    source_origin="generated cropbox fixture",
                    authorization_scope="synthetic test only",
                    uploader="automated-test",
                    render_mode=RenderMode.ALL,
                    render_dpi=72,
                )
            )

            page_record = json.loads(
                (result.bundle_path / "pages.jsonl").read_text(encoding="utf-8")
            )
            evidence = [
                json.loads(line)
                for line in (result.bundle_path / "evidence.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            manifest = json.loads(
                (result.bundle_path / "manifest.json").read_text(encoding="utf-8")
            )
            render = result.bundle_path / page_record["render_uri"]
            with Image.open(render) as image:
                self.assertEqual(image.size, (300, 400))

            quotes = "\n".join(item["quote"] for item in evidence)
            self.assertEqual(page_record["width"], 300)
            self.assertEqual(page_record["height"], 400)
            self.assertIn("VISIBLE INSIDE CROP", quotes)
            self.assertNotIn("HIDDEN OUTSIDE CROP", quotes)
            self.assertTrue(all(0 <= item["bbox"]["x0"] < 300 for item in evidence))
            self.assertTrue(all(item["bbox"]["x1"] <= 300 for item in evidence))
            self.assertEqual(manifest["import_pipeline"]["version"], "2.0-cropbox")
