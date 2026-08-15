"""Transactional PostgreSQL registration for promoted textbook bundles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .promotion import bundle_content_sha256, validate_approved_bundle
from .storage import read_json

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RegistrationConflictError(RuntimeError):
    """Raised when database state differs from the promoted bundle."""


@dataclass(frozen=True)
class RegistrationResult:
    edition_id: str
    source_sha256: str
    school_id: str
    page_count: int
    evidence_count: int
    reused: bool


def _required_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label} must be a nonblank safe identifier")
    return normalized


def _jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path.name} must contain JSON objects")
                records.append(value)
    return records


def _validate_bbox(record: dict[str, Any]) -> tuple[float, float, float, float]:
    bbox = record.get("bbox")
    if not isinstance(bbox, dict):
        raise ValueError("evidence bbox is missing")
    coordinates = tuple(float(bbox[name]) for name in ("x0", "y0", "x1", "y1"))
    x0, y0, x1, y1 = coordinates
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        raise ValueError("evidence bbox is invalid")
    return coordinates


def _edition_values(manifest: dict[str, Any], school_id: str) -> dict[str, object]:
    edition = manifest["edition"]
    return {
        "edition_id": str(edition["edition_id"]),
        "owner_school_id": school_id,
        "subject": str(edition["subject"]),
        "grade": str(edition["grade"]),
        "volume": str(edition["volume"]),
        "publisher": str(edition["publisher"]),
        "edition_label": str(edition["edition_label"]),
        "lifecycle_status": "approved",
    }


def _source_values(
    manifest: dict[str, Any],
    promotion: dict[str, Any],
    manifest_uri: str,
    registered_by: str,
) -> dict[str, object]:
    source = manifest["source"]
    review = manifest["review_history"][-1]
    return {
        "edition_id": str(manifest["edition"]["edition_id"]),
        "source_sha256": str(source["sha256"]),
        "original_filename": str(source["original_filename"]),
        "byte_size": int(source["byte_size"]),
        "page_count": int(source["page_count"]),
        "import_status": "approved",
        "authorization_scope": str(source["authorization_scope"]),
        "manifest_uri": manifest_uri,
        "approved_by": str(review["reviewer"]),
        "approved_at": review["reviewed_at"],
        "bundle_content_sha256": str(promotion["bundle_content_sha256"]),
        "import_pipeline_version": str(promotion["import_pipeline_version"]),
        "review_id": str(promotion["review_id"]),
        "registered_by": registered_by,
    }


_EDITION_SELECT = """
SELECT
    edition_id,
    owner_school_id,
    subject,
    grade,
    volume,
    publisher,
    edition_label,
    lifecycle_status
FROM textbook_editions
WHERE edition_id = %(edition_id)s
"""

_SOURCE_SELECT = """
SELECT
    edition_id,
    source_sha256,
    original_filename,
    byte_size,
    page_count,
    import_status,
    authorization_scope,
    manifest_uri,
    approved_by,
    approved_at,
    bundle_content_sha256,
    import_pipeline_version,
    review_id,
    registered_by
FROM textbook_sources
WHERE edition_id = %(edition_id)s
  AND source_sha256 = %(source_sha256)s
"""


def _normalized_row(row: dict[str, Any]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if key == "approved_at" and value is not None:
            normalized[key] = value.isoformat()
        elif value is not None:
            normalized[key] = (
                str(value)
                if key
                in {
                    "source_sha256",
                    "bundle_content_sha256",
                }
                else value
            )
        else:
            normalized[key] = None
    return normalized


def _assert_existing(
    label: str,
    row: dict[str, Any],
    expected: dict[str, object],
    *,
    ignored: frozenset[str] = frozenset(),
) -> None:
    actual = _normalized_row(row)
    differences = [
        key for key, value in expected.items() if key not in ignored and actual.get(key) != value
    ]
    if differences:
        raise RegistrationConflictError(
            f"existing {label} differs in fields: {', '.join(sorted(differences))}"
        )


_COORDINATE_QUANTUM = Decimal("0.00000001")


def _numeric_signature(value: object) -> Decimal:
    return Decimal(str(value)).quantize(_COORDINATE_QUANTUM).normalize()


def _page_signature(row: dict[str, Any]) -> tuple[object, ...]:
    return (
        int(row["pdf_page_index"]),
        str(row["page_label"]),
        int(row["printed_page"]) if row["printed_page"] is not None else None,
        _numeric_signature(row["width"]),
        _numeric_signature(row["height"]),
        str(row["render_uri"]) if row["render_uri"] is not None else None,
        str(row["quality_status"]),
    )


def _evidence_signature(row: dict[str, Any]) -> tuple[object, ...]:
    return (
        str(row["evidence_id"]),
        int(row["pdf_page_index"]),
        str(row["chapter_id"]) if row["chapter_id"] is not None else None,
        str(row["section_id"]) if row["section_id"] is not None else None,
        str(row["evidence_type"]),
        str(row["quote"]),
        str(row["content_hash"]),
        _numeric_signature(row["bbox_x0"]),
        _numeric_signature(row["bbox_y0"]),
        _numeric_signature(row["bbox_x1"]),
        _numeric_signature(row["bbox_y1"]),
        str(row["bbox_coordinate_system"]),
    )


def _assert_child_rows(
    connection: Any,
    parameters: dict[str, object],
    page_rows: list[dict[str, object]],
    evidence_rows: list[dict[str, object]],
) -> None:
    existing_pages = connection.execute(
        """
        SELECT
            pdf_page_index,
            page_label,
            printed_page,
            width,
            height,
            render_uri,
            quality_status
        FROM textbook_pages
        WHERE edition_id = %(edition_id)s
          AND source_sha256 = %(source_sha256)s
        ORDER BY pdf_page_index
        """,
        parameters,
    ).fetchall()
    existing_evidence = connection.execute(
        """
        SELECT
            evidence_id,
            pdf_page_index,
            chapter_id,
            section_id,
            evidence_type,
            quote,
            content_hash,
            bbox_x0,
            bbox_y0,
            bbox_x1,
            bbox_y1,
            bbox_coordinate_system
        FROM textbook_evidence
        WHERE edition_id = %(edition_id)s
          AND source_sha256 = %(source_sha256)s
        ORDER BY evidence_id
        """,
        parameters,
    ).fetchall()
    expected_pages = sorted((_page_signature(row) for row in page_rows), key=lambda row: row[0])
    expected_evidence = sorted(
        (_evidence_signature(row) for row in evidence_rows), key=lambda row: row[0]
    )
    if [_page_signature(row) for row in existing_pages] != expected_pages:
        raise RegistrationConflictError("existing source page records differ from bundle")
    if [_evidence_signature(row) for row in existing_evidence] != expected_evidence:
        raise RegistrationConflictError("existing source evidence records differ from bundle")


def register_promoted_bundle(
    bundle_path: Path,
    import_root: Path,
    database_url: str,
    school_id: str,
    registered_by: str,
    *,
    require_existing: bool = False,
    allow_active: bool = False,
) -> RegistrationResult:
    """Register one promoted bundle without activating or assigning it."""

    school = _required_identifier(school_id, "school_id")
    actor = _required_identifier(registered_by, "registered_by")
    if not database_url.strip():
        raise ValueError("database_url must not be blank")

    validated = validate_approved_bundle(bundle_path)
    root = import_root.resolve(strict=True)
    bundle = validated.bundle_path
    canonical = (root / validated.edition_id / validated.source_sha256).resolve(strict=True)
    if bundle != canonical or not bundle.is_relative_to(root):
        raise ValueError("only a canonical bundle inside import_root may be registered")

    promotion_path = bundle / "promotion.json"
    if not promotion_path.is_file():
        raise ValueError("canonical bundle has no promotion receipt")
    promotion = read_json(promotion_path)
    content_sha256 = bundle_content_sha256(bundle)
    pipeline = validated.manifest["import_pipeline"]
    if (
        promotion.get("schema_version") != "athena.textbook-promotion.v1"
        or promotion.get("edition_id") != validated.edition_id
        or promotion.get("source_sha256") != validated.source_sha256
        or promotion.get("bundle_content_sha256") != content_sha256
        or promotion.get("import_pipeline_version") != pipeline.get("version")
        or promotion.get("review_id") != validated.review.get("review_id")
    ):
        raise ValueError("promotion receipt does not match canonical bundle")

    artifacts = validated.manifest["artifacts"]
    pages = _jsonl_records(bundle / str(artifacts["pages"]))
    evidence = _jsonl_records(bundle / str(artifacts["evidence"]))
    manifest_uri = (bundle / "manifest.json").relative_to(root).as_posix()
    edition_values = _edition_values(validated.manifest, school)
    source_values = _source_values(
        validated.manifest,
        promotion,
        manifest_uri,
        actor,
    )

    page_rows = [
        {
            "edition_id": validated.edition_id,
            "source_sha256": validated.source_sha256,
            "pdf_page_index": int(record["pdf_page_index"]),
            "page_label": str(record["page_label"]),
            "printed_page": record.get("printed_page"),
            "width": float(record["width"]),
            "height": float(record["height"]),
            "render_uri": record.get("render_uri"),
            "quality_status": str(record["quality_status"]),
        }
        for record in pages
    ]
    evidence_rows: list[dict[str, object]] = []
    for record in evidence:
        x0, y0, x1, y1 = _validate_bbox(record)
        quote = str(record.get("quote", "")).strip()
        if not quote:
            raise ValueError("evidence quote must not be blank")
        evidence_rows.append(
            {
                "evidence_id": str(record["evidence_id"]),
                "edition_id": validated.edition_id,
                "source_sha256": validated.source_sha256,
                "pdf_page_index": int(record["pdf_page_index"]),
                "chapter_id": record.get("chapter_id"),
                "section_id": record.get("section_id"),
                "evidence_type": str(record["evidence_type"]),
                "quote": quote,
                "content_hash": str(record["content_hash"]),
                "bbox_x0": x0,
                "bbox_y0": y0,
                "bbox_x1": x1,
                "bbox_y1": y1,
                "bbox_coordinate_system": str(record.get("bbox_coordinate_system", "")),
            }
        )

    reused = False
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('athena.school_id', %s, true)",
                (school,),
            )
            edition_row = connection.execute(
                _EDITION_SELECT,
                edition_values,
            ).fetchone()
            if edition_row is None:
                if require_existing:
                    raise RegistrationConflictError("registered textbook edition does not exist")
                connection.execute(
                    """
                    INSERT INTO textbook_editions (
                        edition_id,
                        owner_school_id,
                        subject,
                        grade,
                        volume,
                        publisher,
                        edition_label,
                        lifecycle_status
                    ) VALUES (
                        %(edition_id)s,
                        %(owner_school_id)s,
                        %(subject)s,
                        %(grade)s,
                        %(volume)s,
                        %(publisher)s,
                        %(edition_label)s,
                        %(lifecycle_status)s
                    )
                    """,
                    edition_values,
                )
            else:
                expected_edition = dict(edition_values)
                if allow_active and edition_row["lifecycle_status"] == "active":
                    expected_edition["lifecycle_status"] = "active"
                _assert_existing("edition", edition_row, expected_edition)

            source_row = connection.execute(
                _SOURCE_SELECT,
                source_values,
            ).fetchone()
            if source_row is not None:
                expected_source = dict(source_values)
                if allow_active and source_row["import_status"] == "active":
                    expected_source["import_status"] = "active"
                _assert_existing(
                    "source",
                    source_row,
                    expected_source,
                    ignored=frozenset({"registered_by"}),
                )
                _assert_child_rows(
                    connection,
                    source_values,
                    page_rows,
                    evidence_rows,
                )
                reused = True
            else:
                if require_existing:
                    raise RegistrationConflictError("registered textbook source does not exist")
                connection.execute(
                    """
                    INSERT INTO textbook_sources (
                        edition_id,
                        source_sha256,
                        original_filename,
                        byte_size,
                        page_count,
                        import_status,
                        authorization_scope,
                        manifest_uri,
                        approved_by,
                        approved_at,
                        bundle_content_sha256,
                        import_pipeline_version,
                        review_id,
                        registered_by
                    ) VALUES (
                        %(edition_id)s,
                        %(source_sha256)s,
                        %(original_filename)s,
                        %(byte_size)s,
                        %(page_count)s,
                        %(import_status)s,
                        %(authorization_scope)s,
                        %(manifest_uri)s,
                        %(approved_by)s,
                        %(approved_at)s,
                        %(bundle_content_sha256)s,
                        %(import_pipeline_version)s,
                        %(review_id)s,
                        %(registered_by)s
                    )
                    """,
                    source_values,
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO textbook_pages (
                            edition_id,
                            source_sha256,
                            pdf_page_index,
                            page_label,
                            printed_page,
                            width,
                            height,
                            render_uri,
                            quality_status
                        ) VALUES (
                            %(edition_id)s,
                            %(source_sha256)s,
                            %(pdf_page_index)s,
                            %(page_label)s,
                            %(printed_page)s,
                            %(width)s,
                            %(height)s,
                            %(render_uri)s,
                            %(quality_status)s
                        )
                        """,
                        page_rows,
                    )
                    cursor.executemany(
                        """
                        INSERT INTO textbook_evidence (
                            evidence_id,
                            edition_id,
                            source_sha256,
                            pdf_page_index,
                            chapter_id,
                            section_id,
                            evidence_type,
                            quote,
                            content_hash,
                            bbox_x0,
                            bbox_y0,
                            bbox_x1,
                            bbox_y1,
                            bbox_coordinate_system
                        ) VALUES (
                            %(evidence_id)s,
                            %(edition_id)s,
                            %(source_sha256)s,
                            %(pdf_page_index)s,
                            %(chapter_id)s,
                            %(section_id)s,
                            %(evidence_type)s,
                            %(quote)s,
                            %(content_hash)s,
                            %(bbox_x0)s,
                            %(bbox_y0)s,
                            %(bbox_x1)s,
                            %(bbox_y1)s,
                            %(bbox_coordinate_system)s
                        )
                        """,
                        evidence_rows,
                    )

    return RegistrationResult(
        validated.edition_id,
        validated.source_sha256,
        school,
        len(page_rows),
        len(evidence_rows),
        reused,
    )
