"""Idempotent textbook PDF import orchestration."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from athena_domain import TextbookEdition

from .extract import group_words, make_page_evidence
from .fingerprint import sha256_file
from .models import ImportReport, ImportStatus, PageRecord, QualityStatus, RenderMode, SourceRecord
from .render import render_pdf
from .storage import read_json, write_json, write_jsonl

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,127}$")
IMPORT_PIPELINE_VERSION = "2.0-cropbox"


def _visible_page(page: Any) -> tuple[Any, float, float, float, float]:
    page_left, page_top, page_right, page_bottom = (float(value) for value in page.bbox)
    cropbox = page.cropbox or page.bbox
    crop_left, crop_top, crop_right, crop_bottom = (float(value) for value in cropbox)
    left = max(page_left, crop_left)
    top = max(page_top, crop_top)
    right = min(page_right, crop_right)
    bottom = min(page_bottom, crop_bottom)
    if right <= left or bottom <= top:
        raise ValueError("PDF CropBox does not intersect the page MediaBox")
    width = right - left
    height = bottom - top
    if (left, top, right, bottom) == (page_left, page_top, page_right, page_bottom):
        return page, left, top, width, height
    return page.crop((left, top, right, bottom)), left, top, width, height


def _relative_words(
    words: list[dict[str, Any]],
    *,
    left: float,
    top: float,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for word in words:
        item = dict(word)
        item["x0"] = float(item["x0"]) - left
        item["x1"] = float(item["x1"]) - left
        item["top"] = float(item["top"]) - top
        item["bottom"] = float(item["bottom"]) - top
        normalized.append(item)
    return normalized


@dataclass(frozen=True, slots=True)
class ImportRequest:
    pdf_path: Path
    output_root: Path
    edition: TextbookEdition
    source_origin: str
    authorization_scope: str
    uploader: str
    render_mode: RenderMode = RenderMode.ALL
    render_dpi: int = 110

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.edition.edition_id):
            raise ValueError("edition_id must be a filesystem-safe stable identifier")
        for name, value in (
            ("source_origin", self.source_origin),
            ("authorization_scope", self.authorization_scope),
            ("uploader", self.uploader),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if not 72 <= self.render_dpi <= 300:
            raise ValueError("render_dpi must be between 72 and 300")


@dataclass(frozen=True, slots=True)
class ImportResult:
    bundle_path: Path
    report: dict[str, Any]
    reused: bool


class TextbookImporter:
    """Produce a reviewable import bundle without copying the source PDF."""

    def import_pdf(self, request: ImportRequest) -> ImportResult:
        pdf_path = request.pdf_path.resolve(strict=True)
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            raise ValueError("pdf_path must point to a PDF file")

        source_sha256 = sha256_file(pdf_path)
        bundle_path = request.output_root.resolve() / request.edition.edition_id / source_sha256
        report_path = bundle_path / "import-report.json"
        if report_path.exists():
            report = read_json(report_path)
            manifest = read_json(bundle_path / "manifest.json")
            import_pipeline = manifest.get("import_pipeline")
            pipeline_version = (
                import_pipeline.get("version") if isinstance(import_pipeline, dict) else None
            )
            if pipeline_version != IMPORT_PIPELINE_VERSION:
                raise ValueError("existing import bundle uses a different pipeline version")
            if report.get("source_sha256") != source_sha256:
                raise ValueError("existing import bundle has a conflicting source digest")
            if request.render_mode == RenderMode.ALL and report.get(
                "rendered_page_count"
            ) != report.get("page_count"):
                raise ValueError(
                    "existing import bundle has incomplete renders and must be inspected "
                    "before replacement"
                )
            return ImportResult(bundle_path, report, reused=True)
        if bundle_path.exists():
            raise ValueError("incomplete import bundle exists and requires manual inspection")

        temporary = bundle_path.parent / f".{source_sha256}.tmp-{uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            report = self._extract(request, pdf_path, source_sha256, temporary)
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(bundle_path)
            return ImportResult(bundle_path, report, reused=False)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _extract(
        self,
        request: ImportRequest,
        pdf_path: Path,
        source_sha256: str,
        temporary: Path,
    ) -> dict[str, Any]:
        try:
            import pdfplumber
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError("pypdf and pdfplumber are required for textbook import") from error

        generated_at = datetime.now(UTC).isoformat()
        reader = PdfReader(str(pdf_path), strict=False)
        page_count = len(reader.pages)
        page_labels = reader.page_labels
        if len(page_labels) != page_count:
            page_labels = [str(index) for index in range(1, page_count + 1)]

        render_result = render_pdf(
            pdf_path,
            temporary / "renders",
            page_count,
            request.render_mode,
            request.render_dpi,
        )
        source = SourceRecord(
            source_id=f"src_{source_sha256[:24]}",
            original_filename=pdf_path.name,
            sha256=source_sha256,
            byte_size=pdf_path.stat().st_size,
            mime_type="application/pdf",
            page_count=page_count,
            source_origin=request.source_origin.strip(),
            authorization_scope=request.authorization_scope.strip(),
            uploader=request.uploader.strip(),
            registered_at=generated_at,
        )

        pages: list[PageRecord] = []
        evidence_records: list[dict[str, Any]] = []
        active_chapter: str | None = None
        active_section: str | None = None
        chapters: set[str] = set()
        sections: set[str] = set()

        with pdfplumber.open(str(pdf_path)) as document:
            if len(document.pages) != page_count:
                raise ValueError("page count differs between PDF parsers")
            for index, page in enumerate(document.pages, start=1):
                visible_page, left, top, page_width, page_height = _visible_page(page)
                label = str(page_labels[index - 1])
                printed_page = int(label) if label.isdigit() and int(label) > 0 else None
                words = _relative_words(
                    visible_page.extract_words(
                        keep_blank_chars=False,
                        use_text_flow=True,
                        x_tolerance=2,
                        y_tolerance=3,
                    ),
                    left=left,
                    top=top,
                )
                blocks = group_words(words)
                page_evidence, active_chapter, active_section = make_page_evidence(
                    blocks=blocks,
                    edition_id=request.edition.edition_id,
                    source_sha256=source_sha256,
                    pdf_page_index=index,
                    page_label=label,
                    printed_page=printed_page,
                    page_width=page_width,
                    page_height=page_height,
                    chapter_id=active_chapter,
                    section_id=active_section,
                )
                for anchor in page_evidence:
                    if anchor.chapter_id:
                        chapters.add(anchor.chapter_id)
                    if anchor.section_id:
                        sections.add(anchor.section_id)
                    record = asdict(anchor)
                    record["evidence_type"] = str(anchor.evidence_type)
                    record["bbox_coordinate_system"] = "pdf-top-left-points"
                    evidence_records.append(record)

                page_warnings = list(render_result.page_warnings.get(index, ()))
                text = "\n".join(block["text"] for block in blocks)
                if not text.strip():
                    page_warnings.append("no_extractable_text")
                render_uri = render_result.page_uris.get(index)
                if render_uri is None and "page_render_missing" not in page_warnings:
                    page_warnings.append("page_render_missing")
                quality = QualityStatus.WARNING if page_warnings else QualityStatus.PASSED
                pages.append(
                    PageRecord(
                        pdf_page_index=index,
                        page_label=label,
                        printed_page=printed_page,
                        width=round(page_width, 3),
                        height=round(page_height, 3),
                        render_uri=render_uri,
                        text_method="embedded" if text.strip() else "manual",
                        quality_status=quality,
                        warnings=tuple(page_warnings),
                        text_character_count=len(text),
                        image_count=len(visible_page.images),
                        vector_element_count=(
                            len(visible_page.lines)
                            + len(visible_page.rects)
                            + len(visible_page.curves)
                        ),
                        evidence_count=len(page_evidence),
                    )
                )

        warning_pages = [page for page in pages if page.warnings]
        report_record = ImportReport(
            schema_version="athena.textbook-import.v1",
            edition_id=request.edition.edition_id,
            source_sha256=source_sha256,
            status=ImportStatus.NEEDS_REVIEW,
            generated_at=generated_at,
            page_count=page_count,
            pages_with_text=sum(page.text_character_count > 0 for page in pages),
            pages_with_images=sum(page.image_count > 0 for page in pages),
            pages_with_vectors=sum(page.vector_element_count > 0 for page in pages),
            rendered_page_count=len(render_result.page_uris),
            evidence_count=len(evidence_records),
            chapter_count=len(chapters),
            section_count=len(sections),
            warning_page_count=len(warning_pages),
            warnings=render_result.warnings,
            manual_review_required=True,
        )
        manifest = {
            "schema_version": "athena.textbook-manifest.v1",
            "status": str(ImportStatus.NEEDS_REVIEW),
            "edition": asdict(request.edition),
            "import_pipeline": {
                "name": "athena-textbook-ingestion",
                "version": IMPORT_PIPELINE_VERSION,
            },
            "source": asdict(source),
            "artifacts": {
                "pages": "pages.jsonl",
                "evidence": "evidence.jsonl",
                "report": "import-report.json",
                "renders": "renders/",
            },
            "source_pdf_embedded": False,
        }
        write_json(temporary / "manifest.json", manifest)
        write_jsonl(temporary / "pages.jsonl", pages)
        write_jsonl(temporary / "evidence.jsonl", evidence_records)
        write_json(temporary / "import-report.json", report_record)
        return json.loads(json.dumps(asdict(report_record), default=str))
