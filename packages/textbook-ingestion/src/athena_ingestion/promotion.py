"""Controlled promotion of approved textbook import candidates."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .review import REQUIRED_REVIEW_CATEGORIES
from .storage import read_json, write_json

PROMOTION_SCHEMA_VERSION = "1.0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_ID_PATTERN = re.compile(r"^review_[0-9a-f]{24}$")


class PromotionValidationError(ValueError):
    """Raised when an import bundle cannot cross the approval boundary."""


class PromotionConflictError(RuntimeError):
    """Raised when the canonical import path already contains different content."""


@dataclass(frozen=True)
class ValidatedBundle:
    bundle_path: Path
    manifest: dict[str, Any]
    report: dict[str, Any]
    review: dict[str, Any]
    page_count: int
    evidence_count: int

    @property
    def edition_id(self) -> str:
        return str(self.manifest["edition"]["edition_id"])

    @property
    def source_sha256(self) -> str:
        return str(self.manifest["source"]["sha256"])


@dataclass(frozen=True)
class PromotionResult:
    destination: Path
    content_sha256: str
    review_id: str
    reused: bool
    archived_path: Path | None


def _jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise PromotionValidationError(
                    f"{path.name}:{line_number} must contain a JSON object"
                )
            records.append(value)
    return records


def _artifact(bundle: Path, reference: object, label: str) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        raise PromotionValidationError(f"manifest artifact {label} is missing")
    candidate = (bundle / reference).resolve(strict=True)
    if not candidate.is_relative_to(bundle) or not candidate.is_file():
        raise PromotionValidationError(f"manifest artifact {label} escapes the bundle")
    return candidate


def _approved_review(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    history = manifest.get("review_history")
    if not isinstance(history, list):
        raise PromotionValidationError("approved manifest has no review history")
    approvals = [
        item for item in history if isinstance(item, dict) and item.get("decision") == "approve"
    ]
    if len(approvals) != 1:
        raise PromotionValidationError("exactly one approved review is required")
    review_id = str(approvals[0].get("review_id", ""))
    if not _REVIEW_ID_PATTERN.fullmatch(review_id):
        raise PromotionValidationError("approved review id is invalid")
    review_path = (bundle / "reviews" / f"{review_id}.json").resolve(strict=True)
    if not review_path.is_relative_to(bundle):
        raise PromotionValidationError("approved review path escapes the bundle")
    review = read_json(review_path)
    if (
        review.get("schema_version") != "athena.textbook-review.v1"
        or review.get("review_id") != review_id
        or review.get("decision") != "approve"
    ):
        raise PromotionValidationError("approved review record does not match manifest history")
    review_without_id = {key: value for key, value in review.items() if key != "review_id"}
    review_hash = hashlib.sha256(
        json.dumps(review_without_id, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if review_id != f"review_{review_hash[:24]}":
        raise PromotionValidationError("approved review id does not match review content")
    if approvals[0].get("reviewer") != review.get("reviewer") or approvals[0].get(
        "reviewed_at"
    ) != review.get("reviewed_at"):
        raise PromotionValidationError("approved review metadata differs from manifest history")
    if review.get("issues"):
        raise PromotionValidationError("approved review contains unresolved issues")
    if not str(review.get("reviewer", "")).strip():
        raise PromotionValidationError("approved review has no reviewer")
    sampled_pages = review.get("sampled_pages")
    if not isinstance(sampled_pages, list) or not sampled_pages:
        raise PromotionValidationError("approved review has no sampled pages")
    categories = {str(value) for value in review.get("checked_categories", [])}
    if not REQUIRED_REVIEW_CATEGORIES.issubset(categories):
        raise PromotionValidationError("approved review does not cover required categories")
    return review


def validate_approved_bundle(bundle_path: Path) -> ValidatedBundle:
    """Validate the complete approval, identity, evidence and render boundary."""

    bundle = bundle_path.resolve(strict=True)
    if not bundle.is_dir() or bundle.is_symlink():
        raise PromotionValidationError("bundle must be a real directory")
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise PromotionValidationError("bundle must not contain symbolic links")

    manifest = read_json(bundle / "manifest.json")
    report = read_json(bundle / "import-report.json")
    if manifest.get("status") != "approved" or report.get("status") != "approved":
        raise PromotionValidationError("manifest and import report must both be approved")
    if report.get("manual_review_required") is not False:
        raise PromotionValidationError("approved import report still requires manual review")

    edition = manifest.get("edition")
    source = manifest.get("source")
    pipeline = manifest.get("import_pipeline")
    artifacts = manifest.get("artifacts")
    if not all(isinstance(value, dict) for value in (edition, source, pipeline, artifacts)):
        raise PromotionValidationError("manifest identity, pipeline or artifacts are malformed")
    edition_id = str(edition.get("edition_id", ""))
    source_sha256 = str(source.get("sha256", ""))
    if not edition_id or "/" in edition_id or "\\" in edition_id or edition_id in {".", ".."}:
        raise PromotionValidationError("edition id is invalid")
    if not _SHA256_PATTERN.fullmatch(source_sha256):
        raise PromotionValidationError("source SHA-256 is invalid")
    if report.get("edition_id") != edition_id or report.get("source_sha256") != source_sha256:
        raise PromotionValidationError("manifest and import report identities differ")
    if not str(pipeline.get("version", "")).strip():
        raise PromotionValidationError("import pipeline version is missing")

    pages_path = _artifact(bundle, artifacts.get("pages"), "pages")
    evidence_path = _artifact(bundle, artifacts.get("evidence"), "evidence")
    report_path = _artifact(bundle, artifacts.get("report"), "report")
    if report_path != (bundle / "import-report.json").resolve():
        raise PromotionValidationError("report artifact must reference import-report.json")
    pages = _jsonl_records(pages_path)
    evidence = _jsonl_records(evidence_path)
    expected_pages = int(source.get("page_count", 0))
    if expected_pages <= 0 or len(pages) != expected_pages:
        raise PromotionValidationError("page records do not match source page count")
    if int(report.get("page_count", -1)) != len(pages):
        raise PromotionValidationError("page records do not match report page count")
    if int(report.get("evidence_count", -1)) != len(evidence):
        raise PromotionValidationError("evidence records do not match report evidence count")

    indices = [int(page.get("pdf_page_index", 0)) for page in pages]
    if sorted(indices) != list(range(1, expected_pages + 1)):
        raise PromotionValidationError("PDF page indices must be complete and unique")
    page_set = set(indices)
    renders = (bundle / str(artifacts.get("renders", ""))).resolve(strict=True)
    if not renders.is_relative_to(bundle) or not renders.is_dir():
        raise PromotionValidationError("render artifact directory is invalid")
    for page in pages:
        render_path = _artifact(bundle, page.get("render_uri"), "page render")
        if not render_path.is_relative_to(renders) or render_path.suffix.lower() != ".png":
            raise PromotionValidationError("page render must be a PNG inside the render directory")
    if int(report.get("rendered_page_count", -1)) != expected_pages:
        raise PromotionValidationError("all approved pages must have renders")

    for record in evidence:
        if record.get("textbook_edition_id") != edition_id:
            raise PromotionValidationError("evidence edition id differs from manifest")
        if record.get("source_sha256") != source_sha256:
            raise PromotionValidationError("evidence source SHA-256 differs from manifest")
        if int(record.get("pdf_page_index", 0)) not in page_set:
            raise PromotionValidationError("evidence references a missing PDF page")
    review = _approved_review(bundle, manifest)
    if review.get("source_sha256") != source_sha256:
        raise PromotionValidationError("approved review source SHA-256 differs from manifest")
    if not {int(value) for value in review["sampled_pages"]}.issubset(page_set):
        raise PromotionValidationError("approved review references a missing PDF page")
    return ValidatedBundle(bundle, manifest, report, review, len(pages), len(evidence))


def bundle_content_sha256(bundle_path: Path) -> str:
    """Hash every bundle file except the promotion receipt itself."""

    bundle = bundle_path.resolve(strict=True)
    digest = hashlib.sha256()
    files = sorted(
        (
            path
            for path in bundle.rglob("*")
            if path.is_file() and path.relative_to(bundle).as_posix() != "promotion.json"
        ),
        key=lambda path: path.relative_to(bundle).as_posix(),
    )
    if not files:
        raise PromotionValidationError("bundle contains no hashable files")
    for path in files:
        if path.is_symlink():
            raise PromotionValidationError("bundle must not contain symbolic links")
        relative = path.relative_to(bundle).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _existing_identity(bundle: Path) -> tuple[str, str, str]:
    manifest = read_json(bundle / "manifest.json")
    edition = manifest.get("edition")
    source = manifest.get("source")
    if not isinstance(edition, dict) or not isinstance(source, dict):
        raise PromotionConflictError("existing canonical bundle has malformed identity")
    return (
        str(edition.get("edition_id", "")),
        str(source.get("sha256", "")),
        str(manifest.get("status", "")),
    )


def _promotion_receipt(
    validated: ValidatedBundle,
    content_sha256: str,
    promoted_by: str,
    archived_path: Path | None,
) -> dict[str, Any]:
    pipeline = validated.manifest["import_pipeline"]
    return {
        "schema_version": "athena.textbook-promotion.v1",
        "promotion_schema_version": PROMOTION_SCHEMA_VERSION,
        "edition_id": validated.edition_id,
        "source_sha256": validated.source_sha256,
        "bundle_content_sha256": content_sha256,
        "import_pipeline_version": str(pipeline["version"]),
        "review_id": str(validated.review["review_id"]),
        "promoted_by": promoted_by,
        "promoted_at": datetime.now(UTC).isoformat(),
        "archived_existing_bundle": archived_path is not None,
        "archived_existing_path": str(archived_path) if archived_path else None,
    }


def promote_bundle(
    candidate_path: Path,
    import_root: Path,
    promoted_by: str,
    archive_root: Path | None = None,
) -> PromotionResult:
    """Copy an approved candidate into its canonical, immutable import location."""

    actor = promoted_by.strip()
    if not actor:
        raise PromotionValidationError("promoted_by must not be blank")
    validated = validate_approved_bundle(candidate_path)
    content_sha256 = bundle_content_sha256(validated.bundle_path)
    root = import_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / validated.edition_id / validated.source_sha256).resolve()
    if not destination.is_relative_to(root):
        raise PromotionValidationError("canonical destination escapes the import root")

    archived_path: Path | None = None
    if destination.exists():
        receipt_path = destination / "promotion.json"
        if receipt_path.is_file():
            existing = validate_approved_bundle(destination)
            receipt = read_json(receipt_path)
            existing_content = bundle_content_sha256(destination)
            if (
                receipt.get("schema_version") == "athena.textbook-promotion.v1"
                and receipt.get("edition_id") == validated.edition_id
                and receipt.get("source_sha256") == validated.source_sha256
                and existing.edition_id == validated.edition_id
                and existing.source_sha256 == validated.source_sha256
                and existing_content == content_sha256
                and receipt.get("bundle_content_sha256") == content_sha256
                and receipt.get("import_pipeline_version")
                == validated.manifest["import_pipeline"]["version"]
                and receipt.get("review_id") == validated.review["review_id"]
            ):
                return PromotionResult(
                    destination,
                    content_sha256,
                    str(validated.review["review_id"]),
                    True,
                    None,
                )
            raise PromotionConflictError(
                "canonical destination already contains a different promoted bundle"
            )
        if archive_root is None:
            raise PromotionConflictError(
                "canonical destination exists; provide archive_root to preserve a legacy bundle"
            )
        existing_edition, existing_source, existing_status = _existing_identity(destination)
        if existing_edition != validated.edition_id or existing_source != validated.source_sha256:
            raise PromotionConflictError(
                "existing canonical bundle has a different edition or source identity"
            )
        if existing_status != "needs_review":
            raise PromotionConflictError(
                "only an unpromoted needs_review legacy bundle may be archived"
            )
        legacy_content_sha256 = bundle_content_sha256(destination)
        archive = archive_root.resolve()
        if archive == root or archive.is_relative_to(destination):
            raise PromotionValidationError(
                "archive root must be separate from the canonical destination"
            )
        archived_path = (
            archive / validated.edition_id / validated.source_sha256 / legacy_content_sha256
        ).resolve()
        if not archived_path.is_relative_to(archive):
            raise PromotionValidationError("archive destination escapes the archive root")
        if archived_path.exists():
            raise PromotionConflictError("deterministic legacy archive path already exists")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".athena-promote-", dir=root))
    shutil.rmtree(staging)
    try:
        shutil.copytree(validated.bundle_path, staging, copy_function=shutil.copy2)
        write_json(
            staging / "promotion.json",
            _promotion_receipt(validated, content_sha256, actor, archived_path),
        )
        staged = validate_approved_bundle(staging)
        if (
            staged.edition_id != validated.edition_id
            or staged.source_sha256 != validated.source_sha256
            or bundle_content_sha256(staging) != content_sha256
        ):
            raise PromotionValidationError("staged promotion differs from approved candidate")

        if destination.exists():
            assert archived_path is not None
            archived_path.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(archived_path)
        try:
            staging.replace(destination)
        except Exception:
            if archived_path is not None and archived_path.exists() and not destination.exists():
                archived_path.replace(destination)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return PromotionResult(
        destination,
        content_sha256,
        str(validated.review["review_id"]),
        False,
        archived_path,
    )
