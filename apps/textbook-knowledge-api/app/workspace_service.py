"""Workspace textbook pin persistence contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from athena_domain import TeachingScope

_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class WorkspaceCatalogNotConfiguredError(RuntimeError):
    pass


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceConflictError(RuntimeError):
    pass


class WorkspaceUnauthorizedError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceTextbook:
    workspace_id: str
    owner_school_id: str
    assignment_id: str
    edition_id: str
    source_sha256: str
    pinned_by: str
    pinned_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspacePinResult:
    workspace: WorkspaceTextbook
    reused: bool


class WorkspaceCatalogBackend(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def pin(
        self,
        workspace_id: str,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> WorkspacePinResult: ...

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> WorkspaceTextbook: ...


class DisabledWorkspaceCatalog:
    @property
    def configured(self) -> bool:
        return False

    @property
    def backend(self) -> str:
        return "disabled"

    def pin(
        self,
        workspace_id: str,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> WorkspacePinResult:
        del workspace_id, principal_id, scope, on_date
        raise WorkspaceCatalogNotConfiguredError("workspace textbook catalog requires PostgreSQL")

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> WorkspaceTextbook:
        del workspace_id, principal_id, school_id
        raise WorkspaceCatalogNotConfiguredError("workspace textbook catalog requires PostgreSQL")


def validate_workspace_id(workspace_id: str) -> str:
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ValueError(
            "workspace_id must be 1-128 characters using letters, digits, '.', '_', ':', or '-'"
        )
    return workspace_id


def build_workspace_catalog(database_url: str | None) -> WorkspaceCatalogBackend:
    if database_url is not None and database_url.strip():
        from app.postgres_workspace_service import PostgresWorkspaceCatalog

        return PostgresWorkspaceCatalog(database_url)
    return DisabledWorkspaceCatalog()


def serialize_workspace(workspace: WorkspaceTextbook) -> dict[str, Any]:
    return {
        "workspace_id": workspace.workspace_id,
        "owner_school_id": workspace.owner_school_id,
        "assignment_id": workspace.assignment_id,
        "textbook": {
            "edition_id": workspace.edition_id,
            "source_sha256": workspace.source_sha256,
        },
        "pinned_by": workspace.pinned_by,
        "pinned_at": workspace.pinned_at.isoformat(),
        "immutable_textbook_pin": True,
    }
