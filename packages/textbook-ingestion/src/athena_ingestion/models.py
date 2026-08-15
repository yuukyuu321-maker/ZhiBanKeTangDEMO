"""Serializable records produced by the textbook import pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ImportStatus(StrEnum):
    REGISTERED = "registered"
    EXTRACTING = "extracting"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    ACTIVE = "active"
    INACTIVE = "inactive"


class QualityStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class RenderMode(StrEnum):
    ALL = "all"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    original_filename: str
    sha256: str
    byte_size: int
    mime_type: str
    page_count: int
    source_origin: str
    authorization_scope: str
    uploader: str
    registered_at: str
    storage_reference: str = "external-local-source"


@dataclass(frozen=True, slots=True)
class PageRecord:
    pdf_page_index: int
    page_label: str
    printed_page: int | None
    width: float
    height: float
    render_uri: str | None
    text_method: str
    quality_status: QualityStatus
    warnings: tuple[str, ...]
    text_character_count: int
    image_count: int
    vector_element_count: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class ImportReport:
    schema_version: str
    edition_id: str
    source_sha256: str
    status: ImportStatus
    generated_at: str
    page_count: int
    pages_with_text: int
    pages_with_images: int
    pages_with_vectors: int
    rendered_page_count: int
    evidence_count: int
    chapter_count: int
    section_count: int
    warning_page_count: int
    warnings: tuple[str, ...]
    manual_review_required: bool


def to_jsonable(value: Any) -> Any:
    """Convert nested import dataclasses and enums into JSON values."""

    if hasattr(value, "__dataclass_fields__"):
        return to_jsonable(asdict(value))
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
