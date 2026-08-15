"""PostgreSQL slide storyboards derived from teacher-confirmed lesson plans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import psycopg
from athena_audit import AuditEvent, AuditResult
from athena_domain import (
    SLIDE_STORYBOARD_SCHEMA_VERSION,
    LessonPlanStatus,
    SlideStoryboardContent,
    SlideStoryboardRevisionSource,
    SlideStoryboardStatus,
    build_deterministic_storyboard,
    require_supported_task,
    validate_storyboard_against_lesson,
)
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.lesson_plan_service import LessonPlanRecord
from app.postgres_lesson_plan_service import PostgresLessonPlanCatalog
from app.postgres_workspace_service import PostgresWorkspaceCatalog
from app.slide_storyboard_service import (
    SlideStoryboardConfirmationError,
    SlideStoryboardConflictError,
    SlideStoryboardMutationResult,
    SlideStoryboardNotFoundError,
    SlideStoryboardRecord,
    SlideStoryboardRevision,
    SlideStoryboardSourceChangedError,
)

SOURCE_LESSON_NOT_CURRENT_DETAIL = (
    "源教案必须保持为当前且已由教师确认；请基于最新确认教案重新生成故事板。"
)

_STORYBOARD_SELECT_SQL = """
SELECT
    storyboard_id,
    workspace_id,
    owner_school_id,
    lesson_plan_id,
    source_lesson_revision,
    source_lesson_content_sha256,
    created_by,
    created_at,
    updated_at,
    status,
    current_revision_number,
    confirmed_revision_number,
    confirmed_by,
    confirmed_at,
    EXISTS (
        SELECT 1
        FROM lesson_plans lp
        JOIN lesson_plan_revisions lpr
          ON lpr.plan_id = lp.plan_id
         AND lpr.revision_number = lp.current_revision_number
        WHERE lp.plan_id = slide_storyboards.lesson_plan_id
          AND lp.owner_school_id = slide_storyboards.owner_school_id
          AND lp.status = 'teacher_confirmed'
          AND lp.current_revision_number = slide_storyboards.source_lesson_revision
          AND lp.confirmed_revision_number = slide_storyboards.source_lesson_revision
          AND lpr.content_sha256 = slide_storyboards.source_lesson_content_sha256
    ) AS source_current
FROM slide_storyboards
WHERE workspace_id = %(workspace_id)s
  AND owner_school_id = %(school_id)s
"""

_REVISION_SELECT_SQL = """
SELECT
    revision_number,
    source,
    restored_from_revision,
    created_by,
    created_at,
    change_summary,
    content,
    content_sha256,
    evidence_fingerprint,
    schema_version
FROM slide_storyboard_revisions
WHERE storyboard_id = %(storyboard_id)s
  AND revision_number = %(revision_number)s
"""


class PostgresSlideStoryboardCatalog:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self._database_url = database_url
        self._workspaces = PostgresWorkspaceCatalog(database_url)
        self._lesson_plans = PostgresLessonPlanCatalog(database_url)

    @property
    def configured(self) -> bool:
        return True

    @property
    def backend(self) -> str:
        return "postgresql"

    def generate(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        *,
        template_id: str,
        request_id: str,
    ) -> SlideStoryboardMutationResult:
        require_supported_task("slide_storyboard")
        _require_request_id(request_id)
        source = self._lesson_plans.export(workspace_id, principal_id, school_id)
        content = build_deterministic_storyboard(
            lesson_plan_id=source.plan_id,
            lesson_revision=source.current_revision_number,
            lesson_content_sha256=source.revision.content_sha256,
            lesson=source.revision.content,
            template_id=template_id,
        )
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                self._assert_source_current(connection, source)
                existing = self._load_storyboard(
                    connection,
                    workspace_id,
                    school_id,
                    for_update=True,
                    required=False,
                )
                if existing is not None:
                    if existing.revision.content_sha256 == _content_sha256(content):
                        return SlideStoryboardMutationResult(
                            storyboard=existing,
                            reused=True,
                        )
                    raise SlideStoryboardConflictError(
                        "slide storyboard already exists; save a revision instead of regenerating"
                    )
                storyboard_id = _storyboard_id(school_id, workspace_id)
                try:
                    connection.execute(
                        """
                        INSERT INTO slide_storyboards (
                            storyboard_id,
                            owner_school_id,
                            workspace_id,
                            lesson_plan_id,
                            source_lesson_revision,
                            source_lesson_content_sha256,
                            template_id,
                            template_version,
                            created_by,
                            current_revision_number
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                        """,
                        (
                            storyboard_id,
                            school_id,
                            workspace_id,
                            source.plan_id,
                            source.current_revision_number,
                            source.revision.content_sha256,
                            content.template_id,
                            content.template_version,
                            principal_id,
                        ),
                    )
                except errors.UniqueViolation as error:
                    raise SlideStoryboardConflictError(
                        "slide storyboard was created concurrently; reload before editing"
                    ) from error
                self._insert_revision(
                    connection,
                    storyboard_id=storyboard_id,
                    school_id=school_id,
                    revision_number=1,
                    source=SlideStoryboardRevisionSource.GENERATED,
                    principal_id=principal_id,
                    change_summary="从教师确认教案生成首版幻灯片故事板",
                    content=content,
                )
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    storyboard_id=storyboard_id,
                    revision_number=1,
                    action="slide_storyboard.generated",
                    request_id=request_id,
                    details={
                        "source_lesson_revision": str(source.current_revision_number),
                        "template_version": content.template_version,
                    },
                )
                result = self._load_storyboard(
                    connection, workspace_id, school_id, required=True
                )
                assert result is not None
                return SlideStoryboardMutationResult(storyboard=result)

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> SlideStoryboardRecord:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                result = self._load_storyboard(
                    connection, workspace_id, school_id, required=True
                )
                assert result is not None
                return result

    def save(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        content: SlideStoryboardContent,
        *,
        base_revision_number: int,
        change_summary: str,
        request_id: str,
    ) -> SlideStoryboardMutationResult:
        _require_request_id(request_id)
        _require_summary(change_summary)
        source = self._lesson_plans.get(workspace_id, principal_id, school_id)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                storyboard = self._load_storyboard(
                    connection,
                    workspace_id,
                    school_id,
                    for_update=True,
                    required=True,
                )
                assert storyboard is not None
                if storyboard.current_revision_number != base_revision_number:
                    raise SlideStoryboardConflictError(
                        "slide storyboard revision changed; reload before saving"
                    )
                self._validate_content_metadata(storyboard, content)
                self._assert_source_current(connection, source, storyboard=storyboard)
                validate_storyboard_against_lesson(content, source.revision.content)
                content_sha = _content_sha256(content)
                if content_sha == storyboard.revision.content_sha256:
                    return SlideStoryboardMutationResult(storyboard=storyboard, reused=True)
                revision_number = storyboard.current_revision_number + 1
                self._insert_revision(
                    connection,
                    storyboard_id=storyboard.storyboard_id,
                    school_id=school_id,
                    revision_number=revision_number,
                    source=SlideStoryboardRevisionSource.TEACHER_EDIT,
                    principal_id=principal_id,
                    change_summary=change_summary,
                    content=content,
                )
                connection.execute(
                    """
                    UPDATE slide_storyboards
                    SET
                        current_revision_number = %s,
                        status = 'draft',
                        confirmed_revision_number = NULL,
                        confirmed_by = NULL,
                        confirmed_at = NULL,
                        updated_at = now()
                    WHERE storyboard_id = %s
                    """,
                    (revision_number, storyboard.storyboard_id),
                )
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    storyboard_id=storyboard.storyboard_id,
                    revision_number=revision_number,
                    action="slide_storyboard.revision_saved",
                    request_id=request_id,
                    details={"base_revision": str(base_revision_number)},
                )
                result = self._load_storyboard(
                    connection, workspace_id, school_id, required=True
                )
                assert result is not None
                return SlideStoryboardMutationResult(storyboard=result)

    def confirm(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        revision_number: int,
        *,
        request_id: str,
    ) -> SlideStoryboardMutationResult:
        _require_request_id(request_id)
        source = self._lesson_plans.get(workspace_id, principal_id, school_id)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                storyboard = self._load_storyboard(
                    connection,
                    workspace_id,
                    school_id,
                    for_update=True,
                    required=True,
                )
                assert storyboard is not None
                if storyboard.current_revision_number != revision_number:
                    raise SlideStoryboardConflictError(
                        "only the current slide storyboard revision can be confirmed"
                    )
                self._assert_source_current(connection, source, storyboard=storyboard)
                validate_storyboard_against_lesson(
                    storyboard.revision.content,
                    source.revision.content,
                )
                if (
                    storyboard.status is SlideStoryboardStatus.TEACHER_CONFIRMED
                    and storyboard.confirmed_revision_number == revision_number
                ):
                    return SlideStoryboardMutationResult(
                        storyboard=storyboard,
                        reused=True,
                    )
                connection.execute(
                    """
                    UPDATE slide_storyboards
                    SET
                        status = 'teacher_confirmed',
                        confirmed_revision_number = %s,
                        confirmed_by = %s,
                        confirmed_at = now(),
                        updated_at = now()
                    WHERE storyboard_id = %s
                    """,
                    (revision_number, principal_id, storyboard.storyboard_id),
                )
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    storyboard_id=storyboard.storyboard_id,
                    revision_number=revision_number,
                    action="slide_storyboard.teacher_confirmed",
                    request_id=request_id,
                    details={"export_ready": "true"},
                )
                result = self._load_storyboard(
                    connection, workspace_id, school_id, required=True
                )
                assert result is not None
                return SlideStoryboardMutationResult(storyboard=result)

    def export(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> SlideStoryboardRecord:
        storyboard = self.get(workspace_id, principal_id, school_id)
        if storyboard.status is not SlideStoryboardStatus.TEACHER_CONFIRMED:
            raise SlideStoryboardConfirmationError(
                "slide storyboard must be teacher-confirmed before export"
            )
        if not storyboard.source_current:
            raise SlideStoryboardSourceChangedError(SOURCE_LESSON_NOT_CURRENT_DETAIL)
        return storyboard

    @staticmethod
    def _validate_content_metadata(
        storyboard: SlideStoryboardRecord,
        content: SlideStoryboardContent,
    ) -> None:
        if (
            content.source_lesson_plan_id != storyboard.lesson_plan_id
            or content.source_lesson_revision != storyboard.source_lesson_revision
            or content.source_lesson_content_sha256
            != storyboard.source_lesson_content_sha256
        ):
            raise SlideStoryboardSourceChangedError(
                "编辑故事板时不得更改源教案元数据。"
            )
        current = storyboard.revision.content
        if (
            content.template_id != current.template_id
            or content.template_version != current.template_version
        ):
            raise SlideStoryboardConflictError(
                "content edits cannot change the storyboard design version"
            )

    @staticmethod
    def _assert_source_current(
        connection: psycopg.Connection,
        source: LessonPlanRecord,
        *,
        storyboard: SlideStoryboardRecord | None = None,
    ) -> None:
        row = connection.execute(
            """
            SELECT lp.status, lp.current_revision_number, lp.confirmed_revision_number,
                   lpr.content_sha256
            FROM lesson_plans lp
            JOIN lesson_plan_revisions lpr
              ON lpr.plan_id = lp.plan_id
             AND lpr.revision_number = lp.current_revision_number
            WHERE lp.plan_id = %s AND lp.owner_school_id = %s
            FOR SHARE OF lp
            """,
            (source.plan_id, source.owner_school_id),
        ).fetchone()
        expected_revision = (
            storyboard.source_lesson_revision
            if storyboard is not None
            else source.current_revision_number
        )
        expected_sha = (
            storyboard.source_lesson_content_sha256
            if storyboard is not None
            else source.revision.content_sha256
        )
        if (
            row is None
            or str(row["status"]) != str(LessonPlanStatus.TEACHER_CONFIRMED)
            or int(row["current_revision_number"]) != expected_revision
            or int(row["confirmed_revision_number"]) != expected_revision
            or str(row["content_sha256"]) != expected_sha
        ):
            raise SlideStoryboardSourceChangedError(SOURCE_LESSON_NOT_CURRENT_DETAIL)

    @staticmethod
    def _insert_revision(
        connection: psycopg.Connection,
        *,
        storyboard_id: str,
        school_id: str,
        revision_number: int,
        source: SlideStoryboardRevisionSource,
        principal_id: str,
        change_summary: str,
        content: SlideStoryboardContent,
    ) -> None:
        connection.execute(
            """
            INSERT INTO slide_storyboard_revisions (
                storyboard_id,
                owner_school_id,
                revision_number,
                source,
                restored_from_revision,
                created_by,
                change_summary,
                content,
                content_sha256,
                evidence_fingerprint,
                schema_version
            )
            VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s)
            """,
            (
                storyboard_id,
                school_id,
                revision_number,
                str(source),
                principal_id,
                change_summary.strip(),
                Jsonb(content.to_payload()),
                _content_sha256(content),
                _evidence_fingerprint(content),
                SLIDE_STORYBOARD_SCHEMA_VERSION,
            ),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO slide_storyboard_revision_evidence (
                    storyboard_id,
                    revision_number,
                    owner_school_id,
                    evidence_id,
                    lesson_plan_id,
                    source_lesson_revision
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        storyboard_id,
                        revision_number,
                        school_id,
                        evidence_id,
                        content.source_lesson_plan_id,
                        content.source_lesson_revision,
                    )
                    for evidence_id in content.evidence_ids
                ],
            )

    @staticmethod
    def _insert_event(
        connection: psycopg.Connection,
        *,
        school_id: str,
        principal_id: str,
        storyboard_id: str,
        revision_number: int,
        action: str,
        request_id: str,
        details: dict[str, str],
    ) -> None:
        event = AuditEvent(
            tenant_id=school_id,
            subject_id=principal_id,
            action=action,
            resource_type="slide_storyboard",
            resource_id=storyboard_id,
            result=AuditResult.ALLOWED,
            request_id=request_id,
            details=details,
        )
        connection.execute(
            """
            INSERT INTO slide_storyboard_events (
                event_id,
                owner_school_id,
                storyboard_id,
                revision_number,
                subject_id,
                action,
                result,
                request_id,
                details,
                occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                school_id,
                storyboard_id,
                revision_number,
                principal_id,
                action,
                str(event.result),
                request_id,
                Jsonb(dict(event.details)),
                event.occurred_at,
            ),
        )

    def _load_storyboard(
        self,
        connection: psycopg.Connection,
        workspace_id: str,
        school_id: str,
        *,
        for_update: bool = False,
        required: bool,
    ) -> SlideStoryboardRecord | None:
        sql = _STORYBOARD_SELECT_SQL + (" FOR UPDATE" if for_update else "")
        row = connection.execute(
            sql,
            {"workspace_id": workspace_id, "school_id": school_id},
        ).fetchone()
        if row is None:
            if required:
                raise SlideStoryboardNotFoundError("slide storyboard was not found")
            return None
        revision = self._load_revision(
            connection,
            str(row["storyboard_id"]),
            int(row["current_revision_number"]),
        )
        return _storyboard_record(row, revision)

    @staticmethod
    def _load_revision(
        connection: psycopg.Connection,
        storyboard_id: str,
        revision_number: int,
    ) -> SlideStoryboardRevision:
        row = connection.execute(
            _REVISION_SELECT_SQL,
            {"storyboard_id": storyboard_id, "revision_number": revision_number},
        ).fetchone()
        if row is None:
            raise SlideStoryboardNotFoundError("slide storyboard revision was not found")
        content_value = row["content"]
        created_at = row["created_at"]
        if not isinstance(content_value, dict) or not isinstance(created_at, datetime):
            raise RuntimeError("slide storyboard revision is invalid")
        return SlideStoryboardRevision(
            revision_number=int(row["revision_number"]),
            source=str(row["source"]),
            restored_from_revision=(
                int(row["restored_from_revision"])
                if row["restored_from_revision"] is not None
                else None
            ),
            created_by=str(row["created_by"]),
            created_at=created_at,
            change_summary=str(row["change_summary"]),
            content=SlideStoryboardContent.from_payload(content_value),
            content_sha256=str(row["content_sha256"]),
            evidence_fingerprint=str(row["evidence_fingerprint"]),
            schema_version=str(row["schema_version"]),
        )


def _storyboard_record(
    row: dict[str, object],
    revision: SlideStoryboardRevision,
) -> SlideStoryboardRecord:
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    confirmed_at = row["confirmed_at"]
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        raise RuntimeError("slide storyboard timestamp is invalid")
    if confirmed_at is not None and not isinstance(confirmed_at, datetime):
        raise RuntimeError("slide storyboard confirmation timestamp is invalid")
    return SlideStoryboardRecord(
        storyboard_id=str(row["storyboard_id"]),
        workspace_id=str(row["workspace_id"]),
        owner_school_id=str(row["owner_school_id"]),
        lesson_plan_id=str(row["lesson_plan_id"]),
        source_lesson_revision=int(row["source_lesson_revision"]),
        source_lesson_content_sha256=str(row["source_lesson_content_sha256"]),
        created_by=str(row["created_by"]),
        created_at=created_at,
        updated_at=updated_at,
        status=SlideStoryboardStatus(str(row["status"])),
        current_revision_number=int(row["current_revision_number"]),
        confirmed_revision_number=(
            int(row["confirmed_revision_number"])
            if row["confirmed_revision_number"] is not None
            else None
        ),
        confirmed_by=str(row["confirmed_by"]) if row["confirmed_by"] else None,
        confirmed_at=confirmed_at,
        source_current=bool(row["source_current"]),
        revision=revision,
    )


def _storyboard_id(school_id: str, workspace_id: str) -> str:
    digest = hashlib.sha256(f"{school_id}\0{workspace_id}".encode()).hexdigest()[:24]
    return f"slide-storyboard-{digest}"


def _content_sha256(content: SlideStoryboardContent) -> str:
    canonical = json.dumps(
        content.to_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _evidence_fingerprint(content: SlideStoryboardContent) -> str:
    canonical = json.dumps(
        {
            "lesson_plan_id": content.source_lesson_plan_id,
            "lesson_revision": content.source_lesson_revision,
            "lesson_content_sha256": content.source_lesson_content_sha256,
            "evidence_ids": list(content.evidence_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _require_request_id(request_id: str) -> None:
    if not request_id.strip():
        raise ValueError("request_id must not be blank")


def _require_summary(change_summary: str) -> None:
    if not change_summary.strip():
        raise ValueError("change_summary must not be blank")
