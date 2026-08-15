"""Textbook edition assignment, authorization, resolution, and pinning rules."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TextbookEditionStatus(StrEnum):
    APPROVED = "approved"
    ACTIVE = "active"
    INACTIVE = "inactive"


class AssignmentNotFoundError(LookupError):
    """Raised when no assignment covers the requested teaching scope."""


class AssignmentConflictError(RuntimeError):
    """Raised when multiple assignments have the same winning specificity."""


class TextbookEditionInactiveError(PermissionError):
    """Raised when a new workspace tries to use a non-active edition."""


class TeachingScopeUnauthorizedError(PermissionError):
    """Raised when a principal is outside the requested teaching scope."""


@dataclass(frozen=True, slots=True)
class TeachingScope:
    school_id: str
    academic_year: str
    grade: str
    subject: str
    campus_id: str | None = None
    class_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("school_id", self.school_id),
            ("academic_year", self.academic_year),
            ("grade", self.grade),
            ("subject", self.subject),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        for name, value in (("campus_id", self.campus_id), ("class_id", self.class_id)):
            if value is not None and not value.strip():
                raise ValueError(f"{name} must be absent or non-blank")


@dataclass(frozen=True, slots=True)
class TeachingAuthorization:
    principal_id: str
    scope: TeachingScope

    def __post_init__(self) -> None:
        if not self.principal_id.strip():
            raise ValueError("principal_id must not be blank")

    def covers(self, requested: TeachingScope) -> bool:
        allowed = self.scope
        return (
            allowed.school_id == requested.school_id
            and allowed.academic_year == requested.academic_year
            and allowed.grade == requested.grade
            and allowed.subject == requested.subject
            and (allowed.campus_id is None or allowed.campus_id == requested.campus_id)
            and (allowed.class_id is None or allowed.class_id == requested.class_id)
        )


@dataclass(frozen=True, slots=True)
class EditionRegistration:
    edition_id: str
    source_sha256: str
    status: TextbookEditionStatus

    def __post_init__(self) -> None:
        if not self.edition_id.strip():
            raise ValueError("edition_id must not be blank")
        if not _SHA256.fullmatch(self.source_sha256.lower()):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")


@dataclass(frozen=True, slots=True)
class TextbookAssignment:
    assignment_id: str
    scope: TeachingScope
    edition_id: str
    source_sha256: str
    valid_from: date
    assigned_by: str
    valid_until: date | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("assignment_id", self.assignment_id),
            ("edition_id", self.edition_id),
            ("assigned_by", self.assigned_by),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if not _SHA256.fullmatch(self.source_sha256.lower()):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be earlier than valid_from")

    def is_effective(self, on_date: date) -> bool:
        return self.valid_from <= on_date and (
            self.valid_until is None or on_date <= self.valid_until
        )

    def matches(self, requested: TeachingScope) -> bool:
        assigned = self.scope
        return (
            assigned.school_id == requested.school_id
            and assigned.academic_year == requested.academic_year
            and assigned.grade == requested.grade
            and assigned.subject == requested.subject
            and (assigned.campus_id is None or assigned.campus_id == requested.campus_id)
            and (assigned.class_id is None or assigned.class_id == requested.class_id)
        )

    @property
    def specificity(self) -> int:
        return (2 if self.scope.class_id is not None else 0) + (
            1 if self.scope.campus_id is not None else 0
        )


@dataclass(frozen=True, slots=True)
class ResolvedTextbook:
    assignment: TextbookAssignment
    registration: EditionRegistration


@dataclass(frozen=True, slots=True)
class WorkspaceTextbookPin:
    workspace_id: str
    assignment_id: str
    edition_id: str
    source_sha256: str
    pinned_at: datetime

    def __post_init__(self) -> None:
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must not be blank")
        if self.pinned_at.tzinfo is None:
            raise ValueError("pinned_at must include a timezone")


class AssignmentResolver:
    def __init__(
        self,
        registrations: Iterable[EditionRegistration],
        assignments: Iterable[TextbookAssignment],
        authorizations: Iterable[TeachingAuthorization],
    ) -> None:
        registration_list = tuple(registrations)
        self._registrations = {
            (item.edition_id, item.source_sha256.lower()): item
            for item in registration_list
        }
        if len(self._registrations) != len(registration_list):
            raise ValueError("edition registrations must be unique by edition and source")
        self._assignments = tuple(assignments)
        self._authorizations = tuple(authorizations)

    def resolve(
        self,
        principal_id: str,
        requested: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> ResolvedTextbook:
        self._require_authorized(principal_id, requested)
        effective_date = on_date or date.today()
        candidates = [
            assignment
            for assignment in self._assignments
            if assignment.matches(requested) and assignment.is_effective(effective_date)
        ]
        if not candidates:
            raise AssignmentNotFoundError("no textbook assignment covers the requested scope")

        highest_specificity = max(item.specificity for item in candidates)
        winners = [item for item in candidates if item.specificity == highest_specificity]
        if len(winners) != 1:
            assignment_ids = ", ".join(sorted(item.assignment_id for item in winners))
            raise AssignmentConflictError(
                f"conflicting textbook assignments at equal priority: {assignment_ids}"
            )
        assignment = winners[0]
        registration = self._registrations.get(
            (assignment.edition_id, assignment.source_sha256.lower())
        )
        if registration is None:
            raise AssignmentNotFoundError("assigned textbook edition or source is not registered")
        if registration.status is not TextbookEditionStatus.ACTIVE:
            raise TextbookEditionInactiveError(
                f"assigned textbook edition is not active: {registration.status}"
            )
        return ResolvedTextbook(assignment=assignment, registration=registration)

    def _require_authorized(self, principal_id: str, requested: TeachingScope) -> None:
        if not any(
            authorization.principal_id == principal_id and authorization.covers(requested)
            for authorization in self._authorizations
        ):
            raise TeachingScopeUnauthorizedError(
                "principal is not authorized for the requested teaching scope"
            )


def pin_workspace(
    workspace_id: str,
    resolved: ResolvedTextbook,
    *,
    pinned_at: datetime | None = None,
) -> WorkspaceTextbookPin:
    return WorkspaceTextbookPin(
        workspace_id=workspace_id,
        assignment_id=resolved.assignment.assignment_id,
        edition_id=resolved.registration.edition_id,
        source_sha256=resolved.registration.source_sha256,
        pinned_at=pinned_at or datetime.now(UTC),
    )
