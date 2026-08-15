"""File-backed development adapter for textbook assignment resolution."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from athena_domain import (
    AssignmentResolver,
    EditionRegistration,
    ResolvedTextbook,
    TeachingAuthorization,
    TeachingScope,
    TextbookAssignment,
    TextbookEditionStatus,
)

_SCHEMA_VERSION = "athena.textbook-assignment-catalog.v1"


class AssignmentCatalogNotConfiguredError(RuntimeError):
    pass


class AssignmentCatalogBackend(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def resolve(
        self,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> ResolvedTextbook: ...


def _scope(value: dict[str, Any]) -> TeachingScope:
    return TeachingScope(
        school_id=str(value["school_id"]),
        academic_year=str(value["academic_year"]),
        grade=str(value["grade"]),
        subject=str(value["subject"]),
        campus_id=str(value["campus_id"]) if value.get("campus_id") is not None else None,
        class_id=str(value["class_id"]) if value.get("class_id") is not None else None,
    )


def _scope_payload(scope: TeachingScope) -> dict[str, str | None]:
    return {
        "school_id": scope.school_id,
        "academic_year": scope.academic_year,
        "grade": scope.grade,
        "subject": scope.subject,
        "campus_id": scope.campus_id,
        "class_id": scope.class_id,
    }


class AssignmentCatalog:
    def __init__(self, resolver: AssignmentResolver | None) -> None:
        self._resolver = resolver

    @classmethod
    def disabled(cls) -> AssignmentCatalog:
        return cls(None)

    @classmethod
    def from_optional_path(cls, path: str | None) -> AssignmentCatalog:
        if path is None or not path.strip():
            return cls.disabled()
        return cls.from_file(Path(path))

    @classmethod
    def from_file(cls, path: Path) -> AssignmentCatalog:
        resolved = path.resolve(strict=True)
        with resolved.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("assignment catalog must be a JSON object")
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AssignmentCatalog:
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported assignment catalog schema version")

        registrations = tuple(
            EditionRegistration(
                edition_id=str(item["edition_id"]),
                source_sha256=str(item["source_sha256"]).lower(),
                status=TextbookEditionStatus(str(item["status"])),
            )
            for item in payload.get("editions", [])
        )
        assignments = tuple(
            TextbookAssignment(
                assignment_id=str(item["assignment_id"]),
                scope=_scope(item["scope"]),
                edition_id=str(item["edition_id"]),
                source_sha256=str(item["source_sha256"]).lower(),
                valid_from=date.fromisoformat(str(item["valid_from"])),
                valid_until=(
                    date.fromisoformat(str(item["valid_until"]))
                    if item.get("valid_until") is not None
                    else None
                ),
                assigned_by=str(item["assigned_by"]),
            )
            for item in payload.get("assignments", [])
        )
        authorizations = tuple(
            TeachingAuthorization(
                principal_id=str(item["principal_id"]),
                scope=_scope(item["scope"]),
            )
            for item in payload.get("authorizations", [])
        )
        return cls(AssignmentResolver(registrations, assignments, authorizations))

    @property
    def configured(self) -> bool:
        return self._resolver is not None

    @property
    def backend(self) -> str:
        return "file" if self.configured else "disabled"

    def resolve(
        self,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> ResolvedTextbook:
        if self._resolver is None:
            raise AssignmentCatalogNotConfiguredError(
                "textbook assignment catalog is not configured"
            )
        return self._resolver.resolve(principal_id, scope, on_date=on_date)

    @staticmethod
    def serialize(resolved: ResolvedTextbook) -> dict[str, Any]:
        assignment = resolved.assignment
        registration = resolved.registration
        return {
            "assignment": {
                "assignment_id": assignment.assignment_id,
                "scope": _scope_payload(assignment.scope),
                "valid_from": assignment.valid_from.isoformat(),
                "valid_until": (
                    assignment.valid_until.isoformat()
                    if assignment.valid_until is not None
                    else None
                ),
                "assigned_by": assignment.assigned_by,
            },
            "textbook": {
                "edition_id": registration.edition_id,
                "source_sha256": registration.source_sha256,
                "status": str(registration.status),
            },
            "workspace_pin_required": True,
        }


def build_assignment_catalog(
    database_url: str | None,
    assignment_file: str | None,
) -> AssignmentCatalogBackend:
    if database_url is not None and database_url.strip():
        from app.postgres_assignment_service import PostgresAssignmentCatalog

        return PostgresAssignmentCatalog(database_url)
    return AssignmentCatalog.from_optional_path(assignment_file)


def serialize_resolution(resolved: ResolvedTextbook) -> dict[str, Any]:
    return AssignmentCatalog.serialize(resolved)
