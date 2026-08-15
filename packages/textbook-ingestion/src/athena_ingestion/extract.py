"""Layout-aware page text extraction and deterministic evidence creation."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import re
from statistics import median
from typing import Any, Iterable

from athena_domain import BoundingBox, EvidenceAnchor, EvidenceType


_CHINESE_NUMBER = (
    r"[\u4e00\u4e8c\u4e09\u56db\u4e94"
    r"\u516d\u4e03\u516b\u4e5d\u5341\u767e0-9]+"
)
_CHAPTER = re.compile(rf"\u7b2c\s*({_CHINESE_NUMBER})\s*\u7ae0")
_SECTION = re.compile(rf"\u7b2c\s*({_CHINESE_NUMBER})\s*\u8282")
_EXPERIMENT_WORDS = (
    "\u5b9e\u9a8c",
    "\u5668\u6750",
    "\u6b65\u9aa4",
    "\u64cd\u4f5c",
)
_EXERCISE_WORDS = (
    "\u7ec3\u4e60",
    "\u601d\u8003\u4e0e\u8ba8\u8bba",
    "\u4f8b\u9898",
    "\u4e60\u9898",
)
_FORMULA_WORDS = (
    "\u516c\u5f0f",
    "\u65b9\u7a0b\u5f0f",
    "\u5316\u5b66\u5f0f",
)


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _heading_id(prefix: str, text: str) -> str:
    return f"{prefix}_{sha256(text.encode('utf-8')).hexdigest()[:16]}"


def classify_evidence(quote: str) -> EvidenceType:
    compact = quote.replace(" ", "")
    if any(word in compact for word in _EXPERIMENT_WORDS):
        return EvidenceType.EXPERIMENT
    if any(word in compact for word in _EXERCISE_WORDS):
        return EvidenceType.EXERCISE
    if any(word in compact for word in _FORMULA_WORDS) or "=" in compact:
        return EvidenceType.FORMULA
    if compact.startswith("\u56fe") or "\u5982\u56fe" in compact:
        return EvidenceType.FIGURE
    if compact.startswith("\u8868"):
        return EvidenceType.TABLE
    if any(word in compact for word in ("\u53eb\u505a", "\u5b9a\u4e49\u4e3a", "\u662f\u6307")):
        return EvidenceType.DEFINITION
    return EvidenceType.BODY


def group_words(words: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group pdfplumber words into stable page blocks using top-left coordinates."""

    sorted_words = sorted(words, key=lambda word: (round(float(word["top"]), 1), word["x0"]))
    if not sorted_words:
        return []
    lines: list[list[dict[str, Any]]] = []
    for word in sorted_words:
        if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 3.5:
            lines.append([word])
        else:
            lines[-1].append(word)

    normalized_lines: list[dict[str, Any]] = []
    for line in lines:
        ordered = sorted(line, key=lambda word: word["x0"])
        normalized_lines.append(
            {
                "text": " ".join(str(word["text"]) for word in ordered).strip(),
                "x0": min(float(word["x0"]) for word in ordered),
                "top": min(float(word["top"]) for word in ordered),
                "x1": max(float(word["x1"]) for word in ordered),
                "bottom": max(float(word["bottom"]) for word in ordered),
            }
        )

    heights = [line["bottom"] - line["top"] for line in normalized_lines]
    normal_height = median(heights) if heights else 10.0
    max_gap = max(10.0, normal_height * 1.35)
    blocks: list[dict[str, Any]] = []
    for line in normalized_lines:
        previous = blocks[-1] if blocks else None
        gap = line["top"] - previous["bottom"] if previous else None
        should_join = previous is not None and gap is not None and gap <= max_gap
        if should_join and len(previous["text"]) < 900:
            previous["text"] = f'{previous["text"]}\n{line["text"]}'
            previous["x0"] = min(previous["x0"], line["x0"])
            previous["top"] = min(previous["top"], line["top"])
            previous["x1"] = max(previous["x1"], line["x1"])
            previous["bottom"] = max(previous["bottom"], line["bottom"])
        else:
            blocks.append(dict(line))
    return [block for block in blocks if block["text"].strip()]


def make_page_evidence(
    *,
    blocks: Iterable[dict[str, Any]],
    edition_id: str,
    source_sha256: str,
    pdf_page_index: int,
    page_label: str,
    printed_page: int | None,
    page_width: float,
    page_height: float,
    chapter_id: str | None,
    section_id: str | None,
) -> tuple[list[EvidenceAnchor], str | None, str | None]:
    evidence: list[EvidenceAnchor] = []
    active_chapter = chapter_id
    active_section = section_id
    for block in blocks:
        quote = str(block["text"]).strip()
        chapter_match = _CHAPTER.search(quote[:120])
        section_match = _SECTION.search(quote[:120])
        if chapter_match:
            active_chapter = _heading_id("chapter", chapter_match.group(0).replace(" ", ""))
            active_section = None
        if section_match:
            section_title = section_match.group(0).replace(" ", "")
            section_key = f"{active_chapter or 'unassigned'}:{section_title}"
            active_section = _heading_id("section", section_key)

        x0 = max(0.0, min(float(block["x0"]), page_width - 0.02))
        y0 = max(0.0, min(float(block["top"]), page_height - 0.02))
        x1 = max(x0 + 0.01, min(float(block["x1"]), page_width))
        y1 = max(y0 + 0.01, min(float(block["bottom"]), page_height))
        bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
        evidence_type = classify_evidence(quote)
        hash_payload = {
            "edition_id": edition_id,
            "source_sha256": source_sha256,
            "pdf_page_index": pdf_page_index,
            "page_label": page_label,
            "bbox": asdict(bbox),
            "evidence_type": str(evidence_type),
            "quote": quote,
        }
        content_hash = _content_hash(hash_payload)
        evidence.append(
            EvidenceAnchor(
                evidence_id=f"ev_{content_hash[:24]}",
                textbook_edition_id=edition_id,
                source_sha256=source_sha256,
                pdf_page_index=pdf_page_index,
                page_label=page_label,
                printed_page=printed_page,
                bbox=bbox,
                evidence_type=evidence_type,
                quote=quote,
                content_hash=content_hash,
                chapter_id=active_chapter,
                section_id=active_section,
            )
        )
    return evidence, active_chapter, active_section
