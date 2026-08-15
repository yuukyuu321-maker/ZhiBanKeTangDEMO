"""Controlled textbook activation, assignment and teaching-scope grants."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .postgres_registration import RegistrationConflictError, register_promoted_bundle
from .promotion import bundle_content_sha256, validate_approved_bundle
from .storage import read_json

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACADEMIC_YEAR_PATTERN = re.compile(r"^(\d{4})-(\d{4})$")


class ActivationValidationError(ValueError):
    """Raised when an activation request is incomplete or inconsistent."""


class ActivationConflictError(RuntimeError):
    """Raised when existing state prevents an unambiguous activation."""


@dataclass(frozen=True)
class ActivationResult:
    edition_id: str
    source_sha256: str
    school_id: str
    teaching_group_id: str
    assignment_id: str
    lifecycle_status: str
    import_status: str
    reused: bool


@dataclass(frozen=True)
class TeachingGrantResult:
    principal_id: str
    teaching_group_id: str
    school_id: str
    reused: bool


def _required_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID_PATTERN.fullmatch(normalized):
        raise ActivationValidationError(f"{label} must be a nonblank safe identifier")
    return normalized


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ActivationValidationError(f"{label} must not be blank")
    return normalized


def _academic_year(value: str) -> str:
    normalized = value.strip()
    match = _ACADEMIC_YEAR_PATTERN.fullmatch(normalized)
    if match is None or int(match.group(2)) != int(match.group(1)) + 1:
        raise ActivationValidationError("academic_year must use consecutive YYYY-YYYY years")
    return normalized


def _optional_identifier(value: str | None, label: str) -> str | None:
    return _required_identifier(value, label) if value is not None else None


def _stable_id(prefix: str, payload: dict[str, object]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _scope_values(
    school_id: str,
    academic_year: str,
    grade: str,
    subject: str,
    campus_id: str | None,
    class_id: str | None,
) -> dict[str, object]:
    return {
        "school_id": _required_identifier(school_id, "school_id"),
        "academic_year": _academic_year(academic_year),
        "grade": _required_text(grade, "grade"),
        "subject": _required_text(subject, "subject"),
        "campus_id": _optional_identifier(campus_id, "campus_id"),
        "class_id": _optional_identifier(class_id, "class_id"),
    }


def _canonical_bundle(bundle_path: Path, import_root: Path) -> tuple[Any, dict[str, Any], str]:
    validated = validate_approved_bundle(bundle_path)
    root = import_root.resolve(strict=True)
    bundle = validated.bundle_path
    expected = (root / validated.edition_id / validated.source_sha256).resolve(strict=True)
    if bundle != expected or not bundle.is_relative_to(root):
        raise ActivationValidationError(
            "only a canonical bundle inside import_root may be activated"
        )
    promotion_path = bundle / "promotion.json"
    if not promotion_path.is_file():
        raise ActivationValidationError("canonical bundle has no promotion receipt")
    promotion = read_json(promotion_path)
    content_sha256 = bundle_content_sha256(bundle)
    if (
        promotion.get("schema_version") != "athena.textbook-promotion.v1"
        or promotion.get("edition_id") != validated.edition_id
        or promotion.get("source_sha256") != validated.source_sha256
        or promotion.get("bundle_content_sha256") != content_sha256
        or promotion.get("import_pipeline_version")
        != validated.manifest["import_pipeline"]["version"]
        or promotion.get("review_id") != validated.review["review_id"]
    ):
        raise ActivationValidationError("promotion receipt does not match canonical bundle")
    return validated, promotion, content_sha256


_REGISTERED_SOURCE_SQL = """
SELECT
    edition.owner_school_id,
    edition.grade,
    edition.subject,
    edition.lifecycle_status,
    edition.activated_by AS edition_activated_by,
    edition.activated_at AS edition_activated_at,
    edition.activation_reason AS edition_activation_reason,
    source.import_status,
    source.bundle_content_sha256,
    source.import_pipeline_version,
    source.review_id,
    source.activated_by AS source_activated_by,
    source.activated_at AS source_activated_at,
    source.activation_reason AS source_activation_reason,
    (
        SELECT count(*)
        FROM textbook_pages AS page
        WHERE page.edition_id = source.edition_id
          AND page.source_sha256 = source.source_sha256
    ) AS page_count,
    (
        SELECT count(*)
        FROM textbook_evidence AS evidence
        WHERE evidence.edition_id = source.edition_id
          AND evidence.source_sha256 = source.source_sha256
    ) AS evidence_count
FROM textbook_editions AS edition
JOIN textbook_sources AS source
  ON source.edition_id = edition.edition_id
WHERE edition.edition_id = %(edition_id)s
  AND edition.owner_school_id = %(school_id)s
  AND source.source_sha256 = %(source_sha256)s
"""


def _find_or_create_group(
    connection: Any,
    scope: dict[str, object],
) -> tuple[str, bool]:
    row = connection.execute(
        """
        SELECT teaching_group_id
        FROM teaching_groups
        WHERE owner_school_id = %(school_id)s
          AND academic_year = %(academic_year)s
          AND grade = %(grade)s
          AND subject = %(subject)s
          AND campus_id IS NOT DISTINCT FROM %(campus_id)s
          AND class_id IS NOT DISTINCT FROM %(class_id)s
        """,
        scope,
    ).fetchone()
    if row is not None:
        return str(row["teaching_group_id"]), True
    teaching_group_id = _stable_id("group", scope)
    connection.execute(
        """
        INSERT INTO teaching_groups (
            teaching_group_id,
            owner_school_id,
            campus_id,
            academic_year,
            grade,
            class_id,
            subject
        ) VALUES (
            %(teaching_group_id)s,
            %(school_id)s,
            %(campus_id)s,
            %(academic_year)s,
            %(grade)s,
            %(class_id)s,
            %(subject)s
        )
        """,
        {**scope, "teaching_group_id": teaching_group_id},
    )
    return teaching_group_id, False


def _assignment_values(
    teaching_group_id: str,
    edition_id: str,
    source_sha256: str,
    valid_from: date,
    valid_until: date | None,
    decided_by: str,
) -> dict[str, object]:
    identity = {
        "teaching_group_id": teaching_group_id,
        "edition_id": edition_id,
        "source_sha256": source_sha256,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until is not None else None,
    }
    return {
        **identity,
        "assignment_id": _stable_id("assignment", identity),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "assigned_by": decided_by,
    }


def _find_or_create_assignment(
    connection: Any,
    values: dict[str, object],
) -> tuple[str, bool]:
    overlaps = connection.execute(
        """
        SELECT
            assignment_id,
            edition_id,
            source_sha256,
            valid_from,
            valid_until,
            assigned_by
        FROM textbook_assignments
        WHERE teaching_group_id = %(teaching_group_id)s
          AND valid_from <= COALESCE(%(valid_until)s, 'infinity'::date)
          AND COALESCE(valid_until, 'infinity'::date) >= %(valid_from)s
        ORDER BY assignment_id
        """,
        values,
    ).fetchall()
    if overlaps:
        if len(overlaps) == 1:
            existing = overlaps[0]
            exact = (
                str(existing["assignment_id"]) == values["assignment_id"]
                and str(existing["edition_id"]) == values["edition_id"]
                and str(existing["source_sha256"]) == values["source_sha256"]
                and existing["valid_from"] == values["valid_from"]
                and existing["valid_until"] == values["valid_until"]
                and str(existing["assigned_by"]) == values["assigned_by"]
            )
            if exact:
                return str(existing["assignment_id"]), True
        identifiers = ", ".join(str(row["assignment_id"]) for row in overlaps)
        raise ActivationConflictError(
            f"overlapping assignment exists at the same scope: {identifiers}"
        )
    connection.execute(
        """
        INSERT INTO textbook_assignments (
            assignment_id,
            teaching_group_id,
            edition_id,
            source_sha256,
            valid_from,
            valid_until,
            assigned_by
        ) VALUES (
            %(assignment_id)s,
            %(teaching_group_id)s,
            %(edition_id)s,
            %(source_sha256)s,
            %(valid_from)s,
            %(valid_until)s,
            %(assigned_by)s
        )
        """,
        values,
    )
    return str(values["assignment_id"]), False


def activate_and_assign_bundle(
    bundle_path: Path,
    import_root: Path,
    database_url: str,
    school_id: str,
    academic_year: str,
    grade: str,
    subject: str,
    valid_from: date,
    decided_by: str,
    reason: str,
    *,
    valid_until: date | None = None,
    campus_id: str | None = None,
    class_id: str | None = None,
) -> ActivationResult:
    """Atomically activate a registered source and assign it to one exact scope."""

    if not database_url.strip():
        raise ActivationValidationError("database_url must not be blank")
    if valid_until is not None and valid_until < valid_from:
        raise ActivationValidationError("valid_until must not be earlier than valid_from")
    actor = _required_identifier(decided_by, "decided_by")
    activation_reason = _required_text(reason, "reason")
    scope = _scope_values(
        school_id,
        academic_year,
        grade,
        subject,
        campus_id,
        class_id,
    )
    validated, promotion, content_sha256 = _canonical_bundle(bundle_path, import_root)
    edition = validated.manifest["edition"]
    if edition["grade"] != scope["grade"] or edition["subject"] != scope["subject"]:
        raise ActivationValidationError(
            "assignment grade and subject must match the registered textbook edition"
        )
    identity = {
        "edition_id": validated.edition_id,
        "source_sha256": validated.source_sha256,
        "school_id": scope["school_id"],
    }
    activation_time = datetime.now(UTC)
    reused = False

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('athena.school_id', %s, true)",
                (scope["school_id"],),
            )
            registered = connection.execute(
                _REGISTERED_SOURCE_SQL,
                identity,
            ).fetchone()
            if registered is None:
                raise ActivationValidationError(
                    "registered textbook source is not visible in the requested school"
                )
            try:
                verification = register_promoted_bundle(
                    bundle_path,
                    import_root,
                    database_url,
                    str(scope["school_id"]),
                    actor,
                    require_existing=True,
                    allow_active=True,
                )
            except RegistrationConflictError as error:
                raise ActivationValidationError(
                    "registered textbook content differs from the promoted bundle"
                ) from error
            if not verification.reused:
                raise ActivationValidationError("textbook must be registered before activation")
            if (
                registered["owner_school_id"] != scope["school_id"]
                or registered["grade"] != scope["grade"]
                or registered["subject"] != scope["subject"]
            ):
                raise ActivationValidationError(
                    "registered textbook ownership or metadata differs from requested scope"
                )
            if (
                str(registered["bundle_content_sha256"]) != content_sha256
                or registered["import_pipeline_version"] != promotion["import_pipeline_version"]
                or registered["review_id"] != promotion["review_id"]
            ):
                raise ActivationValidationError(
                    "registered source provenance differs from the promoted bundle"
                )
            if (
                int(registered["page_count"]) != validated.page_count
                or int(registered["evidence_count"]) != validated.evidence_count
            ):
                raise ActivationValidationError(
                    "registered source page or evidence counts differ from the bundle"
                )

            lifecycle_status = str(registered["lifecycle_status"])
            import_status = str(registered["import_status"])
            if lifecycle_status == "inactive" or import_status == "inactive":
                raise ActivationConflictError(
                    "inactive textbook cannot be reactivated by the initial activation command"
                )
            if (lifecycle_status == "active") != (import_status == "active"):
                raise ActivationConflictError(
                    "edition and source activation statuses are inconsistent"
                )
            if lifecycle_status not in {"approved", "active"} or import_status not in {
                "approved",
                "active",
            }:
                raise ActivationValidationError("only approved textbooks may be activated")

            other_active = connection.execute(
                """
                SELECT source_sha256
                FROM textbook_sources
                WHERE edition_id = %(edition_id)s
                  AND source_sha256 <> %(source_sha256)s
                  AND import_status = 'active'
                ORDER BY source_sha256
                """,
                identity,
            ).fetchall()
            if other_active:
                digests = ", ".join(str(row["source_sha256"]) for row in other_active)
                raise ActivationConflictError(
                    f"another source is already active for this edition: {digests}"
                )

            teaching_group_id, group_reused = _find_or_create_group(connection, scope)
            assignment_values = _assignment_values(
                teaching_group_id,
                validated.edition_id,
                validated.source_sha256,
                valid_from,
                valid_until,
                actor,
            )
            assignment_id, assignment_reused = _find_or_create_assignment(
                connection,
                assignment_values,
            )

            if lifecycle_status == "approved":
                activation_values = {
                    **identity,
                    "activated_by": actor,
                    "activated_at": activation_time,
                    "activation_reason": activation_reason,
                }
                connection.execute(
                    """
                    UPDATE textbook_editions
                    SET lifecycle_status = 'active',
                        activated_by = %(activated_by)s,
                        activated_at = %(activated_at)s,
                        activation_reason = %(activation_reason)s,
                        updated_at = %(activated_at)s
                    WHERE edition_id = %(edition_id)s
                    """,
                    activation_values,
                )
                connection.execute(
                    """
                    UPDATE textbook_sources
                    SET import_status = 'active',
                        activated_by = %(activated_by)s,
                        activated_at = %(activated_at)s,
                        activation_reason = %(activation_reason)s
                    WHERE edition_id = %(edition_id)s
                      AND source_sha256 = %(source_sha256)s
                    """,
                    activation_values,
                )
            else:
                for field in (
                    "edition_activated_by",
                    "edition_activated_at",
                    "edition_activation_reason",
                    "source_activated_by",
                    "source_activated_at",
                    "source_activation_reason",
                ):
                    if registered[field] is None:
                        raise ActivationConflictError(
                            "active textbook is missing required activation audit metadata"
                        )
                reused = group_reused and assignment_reused

    return ActivationResult(
        validated.edition_id,
        validated.source_sha256,
        str(scope["school_id"]),
        teaching_group_id,
        assignment_id,
        "active",
        "active",
        reused,
    )


def grant_principal_teaching_scope(
    database_url: str,
    school_id: str,
    academic_year: str,
    grade: str,
    subject: str,
    principal_id: str,
    granted_by: str,
    *,
    campus_id: str | None = None,
    class_id: str | None = None,
) -> TeachingGrantResult:
    """Grant one principal access to an existing active textbook scope."""

    if not database_url.strip():
        raise ActivationValidationError("database_url must not be blank")
    principal = _required_identifier(principal_id, "principal_id")
    actor = _required_identifier(granted_by, "granted_by")
    scope = _scope_values(
        school_id,
        academic_year,
        grade,
        subject,
        campus_id,
        class_id,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('athena.school_id', %s, true)",
                (scope["school_id"],),
            )
            groups = connection.execute(
                """
                SELECT DISTINCT target.teaching_group_id
                FROM teaching_groups AS target
                JOIN textbook_assignments AS assignment
                  ON assignment.teaching_group_id = target.teaching_group_id
                JOIN textbook_editions AS edition
                  ON edition.edition_id = assignment.edition_id
                JOIN textbook_sources AS source
                  ON source.edition_id = assignment.edition_id
                 AND source.source_sha256 = assignment.source_sha256
                WHERE target.owner_school_id = %(school_id)s
                  AND target.academic_year = %(academic_year)s
                  AND target.grade = %(grade)s
                  AND target.subject = %(subject)s
                  AND target.campus_id IS NOT DISTINCT FROM %(campus_id)s
                  AND target.class_id IS NOT DISTINCT FROM %(class_id)s
                  AND edition.lifecycle_status = 'active'
                  AND source.import_status = 'active'
                ORDER BY target.teaching_group_id
                """,
                scope,
            ).fetchall()
            if len(groups) != 1:
                raise ActivationValidationError(
                    "exactly one active textbook teaching scope is required before granting access"
                )
            teaching_group_id = str(groups[0]["teaching_group_id"])
            existing = connection.execute(
                """
                SELECT granted_by
                FROM principal_teaching_scopes
                WHERE principal_id = %(principal_id)s
                  AND teaching_group_id = %(teaching_group_id)s
                  AND revoked_at IS NULL
                ORDER BY granted_at
                """,
                {
                    "principal_id": principal,
                    "teaching_group_id": teaching_group_id,
                },
            ).fetchall()
            if len(existing) > 1:
                raise ActivationConflictError(
                    "principal has multiple active grants for the same teaching scope"
                )
            if existing:
                return TeachingGrantResult(
                    principal,
                    teaching_group_id,
                    str(scope["school_id"]),
                    True,
                )
            connection.execute(
                """
                INSERT INTO principal_teaching_scopes (
                    principal_id,
                    teaching_group_id,
                    granted_by,
                    granted_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (principal, teaching_group_id, actor, datetime.now(UTC)),
            )
    return TeachingGrantResult(
        principal,
        teaching_group_id,
        str(scope["school_id"]),
        False,
    )
