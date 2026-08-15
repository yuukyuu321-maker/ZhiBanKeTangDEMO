"""PostgreSQL assignment resolution with explicit school context."""

from __future__ import annotations

from datetime import date

import psycopg
from athena_domain import (
    AssignmentResolver,
    EditionRegistration,
    ResolvedTextbook,
    TeachingAuthorization,
    TeachingScope,
    TeachingScopeUnauthorizedError,
    TextbookAssignment,
    TextbookEditionStatus,
)
from psycopg.rows import dict_row

_AUTHORIZATION_SQL = """
SELECT 1
FROM principal_teaching_scopes AS grant_scope
JOIN teaching_groups AS allowed
  ON allowed.teaching_group_id = grant_scope.teaching_group_id
WHERE grant_scope.principal_id = %(principal_id)s
  AND grant_scope.revoked_at IS NULL
  AND allowed.owner_school_id = %(school_id)s
  AND allowed.academic_year = %(academic_year)s
  AND allowed.grade = %(grade)s
  AND allowed.subject = %(subject)s
  AND (allowed.campus_id IS NULL OR allowed.campus_id = %(campus_id)s)
  AND (allowed.class_id IS NULL OR allowed.class_id = %(class_id)s)
LIMIT 1
"""

_ASSIGNMENTS_SQL = """
SELECT
    assignment.assignment_id,
    assignment.edition_id,
    assignment.source_sha256,
    assignment.valid_from,
    assignment.valid_until,
    assignment.assigned_by,
    target.owner_school_id,
    target.academic_year,
    target.grade,
    target.subject,
    target.campus_id,
    target.class_id,
    edition.lifecycle_status,
    source.import_status
FROM textbook_assignments AS assignment
JOIN teaching_groups AS target
  ON target.teaching_group_id = assignment.teaching_group_id
JOIN textbook_editions AS edition
  ON edition.edition_id = assignment.edition_id
JOIN textbook_sources AS source
  ON source.edition_id = assignment.edition_id
 AND source.source_sha256 = assignment.source_sha256
WHERE target.owner_school_id = %(school_id)s
  AND target.academic_year = %(academic_year)s
  AND target.grade = %(grade)s
  AND target.subject = %(subject)s
  AND (target.campus_id IS NULL OR target.campus_id = %(campus_id)s)
  AND (target.class_id IS NULL OR target.class_id = %(class_id)s)
  AND assignment.valid_from <= %(on_date)s
  AND (assignment.valid_until IS NULL OR assignment.valid_until >= %(on_date)s)
ORDER BY assignment.assignment_id
"""


def _effective_status(lifecycle_status: str, import_status: str) -> TextbookEditionStatus:
    if lifecycle_status == "active" and import_status == "active":
        return TextbookEditionStatus.ACTIVE
    if lifecycle_status == "inactive" or import_status == "inactive":
        return TextbookEditionStatus.INACTIVE
    return TextbookEditionStatus.APPROVED


def _parameters(
    principal_id: str,
    scope: TeachingScope,
    on_date: date,
) -> dict[str, object]:
    return {
        "principal_id": principal_id,
        "school_id": scope.school_id,
        "academic_year": scope.academic_year,
        "grade": scope.grade,
        "subject": scope.subject,
        "campus_id": scope.campus_id,
        "class_id": scope.class_id,
        "on_date": on_date,
    }


class PostgresAssignmentCatalog:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self._database_url = database_url

    @property
    def configured(self) -> bool:
        return True

    @property
    def backend(self) -> str:
        return "postgresql"

    def resolve(
        self,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> ResolvedTextbook:
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.transaction():
                return self.resolve_in_transaction(
                    connection,
                    principal_id,
                    scope,
                    on_date=on_date,
                )

    def resolve_in_transaction(
        self,
        connection: psycopg.Connection,
        principal_id: str,
        scope: TeachingScope,
        *,
        on_date: date | None = None,
    ) -> ResolvedTextbook:
        """Resolve an assignment inside the caller's transaction.

        Workspace pinning uses this entry point so assignment resolution and the
        immutable pin insert observe one PostgreSQL snapshot.
        """
        effective_date = on_date or date.today()
        parameters = _parameters(principal_id, scope, effective_date)
        connection.execute(
            "SELECT set_config('athena.school_id', %s, true)",
            (scope.school_id,),
        )
        authorized = connection.execute(
            _AUTHORIZATION_SQL,
            parameters,
        ).fetchone()
        if authorized is None:
            raise TeachingScopeUnauthorizedError(
                "principal is not authorized for the requested teaching scope"
            )
        rows = connection.execute(
            _ASSIGNMENTS_SQL,
            parameters,
        ).fetchall()
        return _resolve_rows(rows, principal_id, scope, effective_date)


def _resolve_rows(
    rows: list[dict[str, object]],
    principal_id: str,
    scope: TeachingScope,
    effective_date: date,
) -> ResolvedTextbook:
    registrations: dict[tuple[str, str], EditionRegistration] = {}
    assignments: list[TextbookAssignment] = []
    for row in rows:
        edition_id = str(row["edition_id"])
        source_sha256 = str(row["source_sha256"])
        key = (edition_id, source_sha256)
        registrations[key] = EditionRegistration(
            edition_id=edition_id,
            source_sha256=source_sha256,
            status=_effective_status(
                str(row["lifecycle_status"]),
                str(row["import_status"]),
            ),
        )
        assignments.append(
            TextbookAssignment(
                assignment_id=str(row["assignment_id"]),
                scope=TeachingScope(
                    school_id=str(row["owner_school_id"]),
                    academic_year=str(row["academic_year"]),
                    grade=str(row["grade"]),
                    subject=str(row["subject"]),
                    campus_id=(str(row["campus_id"]) if row["campus_id"] is not None else None),
                    class_id=(str(row["class_id"]) if row["class_id"] is not None else None),
                ),
                edition_id=edition_id,
                source_sha256=source_sha256,
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
                assigned_by=str(row["assigned_by"]),
            )
        )

    resolver = AssignmentResolver(
        registrations=registrations.values(),
        assignments=assignments,
        authorizations=(TeachingAuthorization(principal_id, scope),),
    )
    return resolver.resolve(principal_id, scope, on_date=effective_date)
