"""PostgreSQL lesson-plan drafts with append-only revisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import psycopg
from athena_audit import AuditEvent, AuditResult
from athena_domain import (
    LESSON_PLAN_SCHEMA_VERSION,
    LessonPlanContent,
    LessonPlanRevisionSource,
    LessonPlanStatus,
    build_deterministic_lesson_plan,
    require_supported_task,
)
from athena_model_gateway import DeterministicModelGateway, ModelRequest, ModelStatus
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.lesson_plan_service import (
    LessonPlanConfirmationError,
    LessonPlanConflictError,
    LessonPlanEvidenceError,
    LessonPlanGenerationInput,
    LessonPlanMutationResult,
    LessonPlanNotFoundError,
    LessonPlanRecord,
    LessonPlanRevision,
    LessonPlanRevisionSummary,
)
from app.postgres_workspace_service import PostgresWorkspaceCatalog
from app.workspace_service import WorkspaceTextbook

_PROMPT_TEMPLATE_VERSION = "athena.lesson-plan.deterministic.v2"

_PLAN_SELECT_SQL = """
SELECT
    plan_id,
    workspace_id,
    owner_school_id,
    created_by,
    created_at,
    updated_at,
    status,
    current_revision_number,
    confirmed_revision_number,
    confirmed_by,
    confirmed_at
FROM lesson_plans
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
    model_adapter,
    prompt_template_version,
    schema_version
FROM lesson_plan_revisions
WHERE plan_id = %(plan_id)s
  AND revision_number = %(revision_number)s
"""


class PostgresLessonPlanCatalog:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url must not be blank")
        self._database_url = database_url
        self._workspaces = PostgresWorkspaceCatalog(database_url)
        self._gateway = DeterministicModelGateway()

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
        generation: LessonPlanGenerationInput,
        *,
        request_id: str,
    ) -> LessonPlanMutationResult:
        require_supported_task("lesson_plan")
        _require_request_id(request_id)
        content = build_deterministic_lesson_plan(
            title=generation.title,
            objectives=generation.objectives,
            required_topics=generation.required_topics,
            lesson_count=generation.lesson_count,
            minutes_per_lesson=generation.minutes_per_lesson,
            evidence_ids=generation.evidence_ids,
            preserve_experiment=generation.preserve_experiment,
            sessions=generation.sessions,
            topic_coverage=generation.topic_coverage,
            experiments=generation.experiments,
        )
        response = self._gateway.generate(
            ModelRequest(
                request_id=request_id,
                task="lesson_plan",
                instruction=generation.instruction,
                evidence_ids=content.evidence_ids,
            )
        )
        if response.status is not ModelStatus.COMPLETED:
            raise LessonPlanEvidenceError("lesson plan generation requires textbook evidence")

        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                workspace = self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                self._validate_evidence(connection, workspace, content.evidence_ids)
                existing = self._load_plan(
                    connection,
                    workspace_id,
                    school_id,
                    for_update=True,
                    required=False,
                )
                if existing is not None:
                    if existing.revision.content_sha256 == _content_sha256(content):
                        return LessonPlanMutationResult(plan=existing, reused=True)
                    raise LessonPlanConflictError(
                        "lesson plan already exists; save a new revision instead of regenerating"
                    )

                plan_id = _plan_id(school_id, workspace_id)
                try:
                    connection.execute(
                        """
                        INSERT INTO lesson_plans (
                            plan_id,
                            owner_school_id,
                            workspace_id,
                            created_by,
                            current_revision_number
                        )
                        VALUES (%s, %s, %s, %s, 1)
                        """,
                        (plan_id, school_id, workspace_id, principal_id),
                    )
                except errors.UniqueViolation as error:
                    raise LessonPlanConflictError(
                        "lesson plan was created concurrently; reload before editing"
                    ) from error
                self._insert_revision(
                    connection,
                    plan_id=plan_id,
                    school_id=school_id,
                    revision_number=1,
                    source=LessonPlanRevisionSource.GENERATED,
                    restored_from_revision=None,
                    principal_id=principal_id,
                    change_summary="生成首版结构化教案草稿",
                    content=content,
                    workspace=workspace,
                    model_adapter=response.adapter,
                )
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    plan_id=plan_id,
                    revision_number=1,
                    action="lesson_plan.generated",
                    request_id=request_id,
                    details={"workspace_id": workspace_id, "revision": "1"},
                )
                plan = self._load_plan(connection, workspace_id, school_id, required=True)
                assert plan is not None
                return LessonPlanMutationResult(plan=plan)

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> LessonPlanRecord:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(connection, workspace_id, school_id, required=True)
                assert plan is not None
                return plan

    def save(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        content: LessonPlanContent,
        *,
        base_revision_number: int,
        change_summary: str,
        request_id: str,
    ) -> LessonPlanMutationResult:
        _require_request_id(request_id)
        _require_summary(change_summary)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                workspace = self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(
                    connection, workspace_id, school_id, for_update=True, required=True
                )
                assert plan is not None
                if plan.current_revision_number != base_revision_number:
                    raise LessonPlanConflictError(
                        "lesson plan revision changed; reload before saving"
                    )
                self._validate_evidence(connection, workspace, content.evidence_ids)
                content_sha = _content_sha256(content)
                if content_sha == plan.revision.content_sha256:
                    return LessonPlanMutationResult(plan=plan, reused=True)
                revision_number = plan.current_revision_number + 1
                self._insert_revision(
                    connection,
                    plan_id=plan.plan_id,
                    school_id=school_id,
                    revision_number=revision_number,
                    source=LessonPlanRevisionSource.TEACHER_EDIT,
                    restored_from_revision=None,
                    principal_id=principal_id,
                    change_summary=change_summary,
                    content=content,
                    workspace=workspace,
                    model_adapter=None,
                )
                self._advance_plan(connection, plan.plan_id, revision_number)
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    plan_id=plan.plan_id,
                    revision_number=revision_number,
                    action="lesson_plan.revision_saved",
                    request_id=request_id,
                    details={"base_revision": str(base_revision_number)},
                )
                updated = self._load_plan(connection, workspace_id, school_id, required=True)
                assert updated is not None
                return LessonPlanMutationResult(plan=updated)

    def revisions(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> tuple[LessonPlanRevisionSummary, ...]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(connection, workspace_id, school_id, required=True)
                assert plan is not None
                rows = connection.execute(
                    """
                    SELECT
                        revision_number,
                        source,
                        restored_from_revision,
                        created_by,
                        created_at,
                        change_summary,
                        content_sha256
                    FROM lesson_plan_revisions
                    WHERE plan_id = %s
                    ORDER BY revision_number DESC
                    """,
                    (plan.plan_id,),
                ).fetchall()
                return tuple(_revision_summary(row) for row in rows)

    def compare(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        from_revision: int,
        to_revision: int,
    ) -> dict[str, Any]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(connection, workspace_id, school_id, required=True)
                assert plan is not None
                before = self._load_revision(connection, plan.plan_id, from_revision)
                after = self._load_revision(connection, plan.plan_id, to_revision)
                return _compare_revisions(before, after)

    def restore(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        revision_number: int,
        *,
        base_revision_number: int,
        change_summary: str,
        request_id: str,
    ) -> LessonPlanMutationResult:
        _require_request_id(request_id)
        _require_summary(change_summary)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                workspace = self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(
                    connection, workspace_id, school_id, for_update=True, required=True
                )
                assert plan is not None
                if plan.current_revision_number != base_revision_number:
                    raise LessonPlanConflictError(
                        "lesson plan revision changed; reload before restoring"
                    )
                target = self._load_revision(connection, plan.plan_id, revision_number)
                self._validate_evidence(connection, workspace, target.content.evidence_ids)
                new_revision = plan.current_revision_number + 1
                self._insert_revision(
                    connection,
                    plan_id=plan.plan_id,
                    school_id=school_id,
                    revision_number=new_revision,
                    source=LessonPlanRevisionSource.RESTORED,
                    restored_from_revision=revision_number,
                    principal_id=principal_id,
                    change_summary=change_summary,
                    content=target.content,
                    workspace=workspace,
                    model_adapter=None,
                )
                self._advance_plan(connection, plan.plan_id, new_revision)
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    plan_id=plan.plan_id,
                    revision_number=new_revision,
                    action="lesson_plan.revision_restored",
                    request_id=request_id,
                    details={"restored_from_revision": str(revision_number)},
                )
                updated = self._load_plan(connection, workspace_id, school_id, required=True)
                assert updated is not None
                return LessonPlanMutationResult(plan=updated)

    def confirm(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        revision_number: int,
        *,
        request_id: str,
    ) -> LessonPlanMutationResult:
        _require_request_id(request_id)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                self._workspaces.get_in_transaction(
                    connection, workspace_id, principal_id, school_id
                )
                plan = self._load_plan(
                    connection, workspace_id, school_id, for_update=True, required=True
                )
                assert plan is not None
                if plan.current_revision_number != revision_number:
                    raise LessonPlanConflictError(
                        "only the current lesson plan revision can be confirmed"
                    )
                if not plan.revision.content.confirmation_ready:
                    blockers = ", ".join(plan.revision.content.confirmation_blockers)
                    raise LessonPlanConfirmationError(
                        f"lesson plan is not ready for teacher confirmation: {blockers}"
                    )
                if (
                    plan.status is LessonPlanStatus.TEACHER_CONFIRMED
                    and plan.confirmed_revision_number == revision_number
                ):
                    return LessonPlanMutationResult(plan=plan, reused=True)
                connection.execute(
                    """
                    UPDATE lesson_plans
                    SET
                        status = 'teacher_confirmed',
                        confirmed_revision_number = %s,
                        confirmed_by = %s,
                        confirmed_at = now(),
                        updated_at = now()
                    WHERE plan_id = %s
                    """,
                    (revision_number, principal_id, plan.plan_id),
                )
                self._insert_event(
                    connection,
                    school_id=school_id,
                    principal_id=principal_id,
                    plan_id=plan.plan_id,
                    revision_number=revision_number,
                    action="lesson_plan.teacher_confirmed",
                    request_id=request_id,
                    details={"export_ready": "true"},
                )
                confirmed = self._load_plan(connection, workspace_id, school_id, required=True)
                assert confirmed is not None
                return LessonPlanMutationResult(plan=confirmed)

    def export(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> LessonPlanRecord:
        plan = self.get(workspace_id, principal_id, school_id)
        if plan.status is not LessonPlanStatus.TEACHER_CONFIRMED:
            raise LessonPlanConfirmationError("lesson plan must be teacher-confirmed before export")
        return plan

    def _validate_evidence(
        self,
        connection: psycopg.Connection,
        workspace: WorkspaceTextbook,
        evidence_ids: tuple[str, ...],
    ) -> None:
        if not evidence_ids:
            raise LessonPlanEvidenceError("lesson plan requires at least one evidence anchor")
        rows = connection.execute(
            """
            SELECT evidence_id
            FROM textbook_evidence
            WHERE edition_id = %s
              AND source_sha256 = %s
              AND evidence_id = ANY(%s)
            """,
            (workspace.edition_id, workspace.source_sha256, list(evidence_ids)),
        ).fetchall()
        found = {str(row["evidence_id"]) for row in rows}
        missing = sorted(set(evidence_ids) - found)
        if missing:
            raise LessonPlanEvidenceError(
                f"evidence is outside the workspace textbook: {', '.join(missing)}"
            )

    def _insert_revision(
        self,
        connection: psycopg.Connection,
        *,
        plan_id: str,
        school_id: str,
        revision_number: int,
        source: LessonPlanRevisionSource,
        restored_from_revision: int | None,
        principal_id: str,
        change_summary: str,
        content: LessonPlanContent,
        workspace: WorkspaceTextbook,
        model_adapter: str | None,
    ) -> None:
        payload = content.to_payload()
        connection.execute(
            """
            INSERT INTO lesson_plan_revisions (
                plan_id,
                owner_school_id,
                revision_number,
                source,
                restored_from_revision,
                created_by,
                change_summary,
                content,
                content_sha256,
                evidence_fingerprint,
                model_adapter,
                prompt_template_version,
                schema_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                plan_id,
                school_id,
                revision_number,
                str(source),
                restored_from_revision,
                principal_id,
                change_summary.strip(),
                Jsonb(payload),
                _content_sha256(content),
                _evidence_fingerprint(workspace, content.evidence_ids),
                model_adapter,
                _PROMPT_TEMPLATE_VERSION,
                LESSON_PLAN_SCHEMA_VERSION,
            ),
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO lesson_plan_revision_evidence (
                    plan_id,
                    revision_number,
                    owner_school_id,
                    evidence_id,
                    edition_id,
                    source_sha256
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        plan_id,
                        revision_number,
                        school_id,
                        evidence_id,
                        workspace.edition_id,
                        workspace.source_sha256,
                    )
                    for evidence_id in content.evidence_ids
                ],
            )

    @staticmethod
    def _advance_plan(
        connection: psycopg.Connection,
        plan_id: str,
        revision_number: int,
    ) -> None:
        connection.execute(
            """
            UPDATE lesson_plans
            SET
                current_revision_number = %s,
                status = 'draft',
                confirmed_revision_number = NULL,
                confirmed_by = NULL,
                confirmed_at = NULL,
                updated_at = now()
            WHERE plan_id = %s
            """,
            (revision_number, plan_id),
        )

    @staticmethod
    def _insert_event(
        connection: psycopg.Connection,
        *,
        school_id: str,
        principal_id: str,
        plan_id: str,
        revision_number: int | None,
        action: str,
        request_id: str,
        details: dict[str, str],
    ) -> None:
        event = AuditEvent(
            tenant_id=school_id,
            subject_id=principal_id,
            action=action,
            resource_type="lesson_plan",
            resource_id=plan_id,
            result=AuditResult.ALLOWED,
            request_id=request_id,
            details=details,
        )
        connection.execute(
            """
            INSERT INTO lesson_plan_events (
                event_id,
                owner_school_id,
                plan_id,
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
                plan_id,
                revision_number,
                principal_id,
                action,
                str(event.result),
                request_id,
                Jsonb(dict(event.details)),
                event.occurred_at,
            ),
        )

    def _load_plan(
        self,
        connection: psycopg.Connection,
        workspace_id: str,
        school_id: str,
        *,
        for_update: bool = False,
        required: bool,
    ) -> LessonPlanRecord | None:
        sql = _PLAN_SELECT_SQL + (" FOR UPDATE" if for_update else "")
        row = connection.execute(
            sql,
            {"workspace_id": workspace_id, "school_id": school_id},
        ).fetchone()
        if row is None:
            if required:
                raise LessonPlanNotFoundError("lesson plan was not found")
            return None
        revision = self._load_revision(
            connection,
            str(row["plan_id"]),
            int(row["current_revision_number"]),
        )
        return _plan_record(row, revision)

    @staticmethod
    def _load_revision(
        connection: psycopg.Connection,
        plan_id: str,
        revision_number: int,
    ) -> LessonPlanRevision:
        row = connection.execute(
            _REVISION_SELECT_SQL,
            {"plan_id": plan_id, "revision_number": revision_number},
        ).fetchone()
        if row is None:
            raise LessonPlanNotFoundError("lesson plan revision was not found")
        return _revision(row)


def _revision(row: dict[str, object]) -> LessonPlanRevision:
    content_value = row["content"]
    if not isinstance(content_value, dict):
        raise RuntimeError("lesson plan revision content is invalid")
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("lesson plan revision timestamp is invalid")
    return LessonPlanRevision(
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
        content=LessonPlanContent.from_payload(content_value),
        content_sha256=str(row["content_sha256"]),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        model_adapter=(str(row["model_adapter"]) if row["model_adapter"] else None),
        prompt_template_version=str(row["prompt_template_version"]),
        schema_version=str(row["schema_version"]),
    )


def _plan_record(
    row: dict[str, object],
    revision: LessonPlanRevision,
) -> LessonPlanRecord:
    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        raise RuntimeError("lesson plan timestamp is invalid")
    confirmed_at = row["confirmed_at"]
    if confirmed_at is not None and not isinstance(confirmed_at, datetime):
        raise RuntimeError("lesson plan confirmation timestamp is invalid")
    return LessonPlanRecord(
        plan_id=str(row["plan_id"]),
        workspace_id=str(row["workspace_id"]),
        owner_school_id=str(row["owner_school_id"]),
        created_by=str(row["created_by"]),
        created_at=created_at,
        updated_at=updated_at,
        status=LessonPlanStatus(str(row["status"])),
        current_revision_number=int(row["current_revision_number"]),
        confirmed_revision_number=(
            int(row["confirmed_revision_number"])
            if row["confirmed_revision_number"] is not None
            else None
        ),
        confirmed_by=str(row["confirmed_by"]) if row["confirmed_by"] else None,
        confirmed_at=confirmed_at,
        revision=revision,
    )


def _revision_summary(row: dict[str, object]) -> LessonPlanRevisionSummary:
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("lesson plan revision timestamp is invalid")
    return LessonPlanRevisionSummary(
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
        content_sha256=str(row["content_sha256"]),
    )


def _compare_revisions(
    before: LessonPlanRevision,
    after: LessonPlanRevision,
) -> dict[str, Any]:
    before_payload = before.content.to_payload()
    after_payload = after.content.to_payload()
    top_level = (
        "title",
        "objectives",
        "required_topics",
        "available_minutes",
        "sessions",
        "topic_coverage",
        "experiments",
        "confirmation_blockers",
        "board_plan",
        "checks_for_understanding",
        "materials",
        "omissions",
        "limitations",
    )
    before_segments = {item["segment_id"]: item for item in before_payload["lesson_segments"]}
    after_segments = {item["segment_id"]: item for item in after_payload["lesson_segments"]}
    return {
        "from_revision": before.revision_number,
        "to_revision": after.revision_number,
        "fields_changed": [key for key in top_level if before_payload[key] != after_payload[key]],
        "segments_added": sorted(after_segments.keys() - before_segments.keys()),
        "segments_removed": sorted(before_segments.keys() - after_segments.keys()),
        "segments_changed": sorted(
            key
            for key in before_segments.keys() & after_segments.keys()
            if before_segments[key] != after_segments[key]
        ),
        "planned_minutes_delta": (
            after.content.budget.planned_minutes - before.content.budget.planned_minutes
        ),
        "content_changed": before.content_sha256 != after.content_sha256,
    }


def _plan_id(school_id: str, workspace_id: str) -> str:
    digest = hashlib.sha256(f"{school_id}\0{workspace_id}".encode()).hexdigest()[:24]
    return f"lesson-plan-{digest}"


def _content_sha256(content: LessonPlanContent) -> str:
    canonical = json.dumps(
        content.to_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _evidence_fingerprint(
    workspace: WorkspaceTextbook,
    evidence_ids: tuple[str, ...],
) -> str:
    canonical = json.dumps(
        {
            "edition_id": workspace.edition_id,
            "source_sha256": workspace.source_sha256,
            "evidence_ids": list(evidence_ids),
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
