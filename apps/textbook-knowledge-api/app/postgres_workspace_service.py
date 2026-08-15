"""PostgreSQL-backed immutable textbook pins for teacher workspaces."""

from __future__ import annotations

from datetime import date, datetime

import psycopg
from athena_domain import TeachingScope
from psycopg import errors
from psycopg.rows import dict_row

from app.postgres_assignment_service import PostgresAssignmentCatalog
from app.workspace_service import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePinResult,
    WorkspaceTextbook,
    WorkspaceUnauthorizedError,
    validate_workspace_id,
)

_PIN_SELECT_SQL = """
SELECT
    pin.workspace_id,
    pin.owner_school_id,
    pin.assignment_id,
    pin.edition_id,
    pin.source_sha256,
    pin.pinned_by,
    pin.pinned_at,
    assignment.teaching_group_id
FROM workspace_textbook_pins AS pin
JOIN textbook_assignments AS assignment
  ON assignment.assignment_id = pin.assignment_id
 AND assignment.edition_id = pin.edition_id
 AND assignment.source_sha256 = pin.source_sha256
WHERE pin.workspace_id = %(workspace_id)s
  AND pin.owner_school_id = %(school_id)s
"""

_ACTIVE_GRANT_SQL = """
SELECT 1
FROM principal_teaching_scopes
WHERE principal_id = %(principal_id)s
  AND teaching_group_id = %(teaching_group_id)s
  AND revoked_at IS NULL
LIMIT 1
"""

_PIN_INSERT_SQL = """
INSERT INTO workspace_textbook_pins (
    workspace_id,
    owner_school_id,
    assignment_id,
    edition_id,
    source_sha256,
    pinned_by
)
VALUES (
    %(workspace_id)s,
    %(school_id)s,
    %(assignment_id)s,
    %(edition_id)s,
    %(source_sha256)s,
    %(principal_id)s
)
RETURNING
    workspace_id,
    owner_school_id,
    assignment_id,
    edition_id,
    source_sha256,
    pinned_by,
    pinned_at
"""


def _workspace(row: dict[str, object]) -> WorkspaceTextbook:
    pinned_at = row["pinned_at"]
    if not isinstance(pinned_at, datetime):
        raise RuntimeError("workspace pin timestamp is invalid")
    return WorkspaceTextbook(
        workspace_id=str(row["workspace_id"]),
        owner_school_id=str(row["owner_school_id"]),
        assignment_id=str(row["assignment_id"]),
        edition_id=str(row["edition_id"]),
        source_sha256=str(row["source_sha256"]),
        pinned_by=str(row["pinned_by"]),
        pinned_at=pinned_at,
    )


class PostgresWorkspaceCatalog:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self._database_url = database_url
        self._assignments = PostgresAssignmentCatalog(database_url)

    @property
    def configured(self) -> bool:
        return True

    @property
    def backend(self) -> str:
        return "postgresql"

    def pin(
        self,
        workspace_id: str,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> WorkspacePinResult:
        validate_workspace_id(workspace_id)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                resolved = self._assignments.resolve_in_transaction(
                    connection,
                    principal_id,
                    scope,
                    on_date=on_date,
                )
                parameters = {
                    "workspace_id": workspace_id,
                    "school_id": scope.school_id,
                    "principal_id": principal_id,
                    "assignment_id": resolved.assignment.assignment_id,
                    "edition_id": resolved.registration.edition_id,
                    "source_sha256": resolved.registration.source_sha256,
                }
                existing = connection.execute(_PIN_SELECT_SQL, parameters).fetchone()
                if existing is not None:
                    workspace = _workspace(existing)
                    expected = (
                        principal_id,
                        resolved.assignment.assignment_id,
                        resolved.registration.edition_id,
                        resolved.registration.source_sha256,
                    )
                    actual = (
                        workspace.pinned_by,
                        workspace.assignment_id,
                        workspace.edition_id,
                        workspace.source_sha256,
                    )
                    if actual != expected:
                        raise WorkspaceConflictError(
                            "workspace_id is already pinned and cannot be rebound"
                        )
                    return WorkspacePinResult(workspace=workspace, reused=True)

                try:
                    inserted = connection.execute(_PIN_INSERT_SQL, parameters).fetchone()
                except errors.UniqueViolation as error:
                    raise WorkspaceConflictError("workspace_id is already in use") from error
                if inserted is None:
                    raise RuntimeError("workspace pin insert returned no row")
                return WorkspacePinResult(workspace=_workspace(inserted), reused=False)

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> WorkspaceTextbook:
        validate_workspace_id(workspace_id)
        if not principal_id.strip():
            raise ValueError("principal_id must not be blank")
        if not school_id.strip():
            raise ValueError("school_id must not be blank")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                return self.get_in_transaction(
                    connection,
                    workspace_id,
                    principal_id,
                    school_id,
                )

    def get_in_transaction(
        self,
        connection: psycopg.Connection,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> WorkspaceTextbook:
        """Authorize and read a workspace within the caller's transaction."""
        validate_workspace_id(workspace_id)
        parameters = {
            "workspace_id": workspace_id,
            "school_id": school_id,
            "principal_id": principal_id,
        }
        connection.execute(
            "SELECT set_config('athena.school_id', %s, true)",
            (school_id,),
        )
        row = connection.execute(_PIN_SELECT_SQL, parameters).fetchone()
        if row is None:
            raise WorkspaceNotFoundError("workspace textbook pin was not found")
        if str(row["pinned_by"]) != principal_id:
            raise WorkspaceUnauthorizedError("principal is not authorized to access this workspace")
        grant = connection.execute(
            _ACTIVE_GRANT_SQL,
            {
                **parameters,
                "teaching_group_id": str(row["teaching_group_id"]),
            },
        ).fetchone()
        if grant is None:
            raise WorkspaceUnauthorizedError(
                "principal no longer has an active grant for this workspace"
            )
        return _workspace(row)
