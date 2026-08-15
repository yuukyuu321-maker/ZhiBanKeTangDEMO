"""Textbook identity and page-aware evidence models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceType(StrEnum):
    BODY = "body"
    DEFINITION = "definition"
    EXPERIMENT = "experiment"
    EXERCISE = "exercise"
    FORMULA = "formula"
    FIGURE = "figure"
    TABLE = "table"


@dataclass(frozen=True, slots=True)
class TextbookEdition:
    edition_id: str
    subject: str
    grade: str
    volume: str
    publisher: str
    edition_label: str

    def __post_init__(self) -> None:
        for name, value in (
            ("edition_id", self.edition_id),
            ("subject", self.subject),
            ("grade", self.grade),
            ("volume", self.volume),
            ("publisher", self.publisher),
            ("edition_label", self.edition_label),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if min(self.x0, self.y0, self.x1, self.y1) < 0:
            raise ValueError("bounding box coordinates must be non-negative")
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bounding box must have positive width and height")


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    evidence_id: str
    textbook_edition_id: str
    source_sha256: str
    pdf_page_index: int
    page_label: str
    bbox: BoundingBox
    evidence_type: EvidenceType
    quote: str
    content_hash: str
    chapter_id: str | None = None
    section_id: str | None = None
    printed_page: int | None = None

    def __post_init__(self) -> None:
        if self.pdf_page_index < 1:
            raise ValueError("pdf_page_index is one-based and must be positive")
        if self.printed_page is not None and self.printed_page < 1:
            raise ValueError("printed_page must be positive when present")
        if not self.page_label.strip():
            raise ValueError("page_label must not be blank")
        if not self.quote.strip():
            raise ValueError("quote must not be blank")
        if not _SHA256.fullmatch(self.source_sha256.lower()):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
        if not _SHA256.fullmatch(self.content_hash.lower()):
            raise ValueError("content_hash must be a 64-character hexadecimal digest")
