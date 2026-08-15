"""Lesson-plan revision persistence contract and response serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from athena_domain import (
    LessonExperiment,
    LessonPlanContent,
    LessonPlanStatus,
    LessonSession,
    TopicEvidenceCoverage,
)


class LessonPlanCatalogNotConfiguredError(RuntimeError):
    pass


class LessonPlanNotFoundError(LookupError):
    pass


class LessonPlanConflictError(RuntimeError):
    pass


class LessonPlanEvidenceError(ValueError):
    pass


class LessonPlanConfirmationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class LessonPlanGenerationInput:
    title: str
    objectives: tuple[str, ...]
    required_topics: tuple[str, ...]
    lesson_count: int
    minutes_per_lesson: int
    evidence_ids: tuple[str, ...]
    preserve_experiment: bool
    instruction: str
    sessions: tuple[LessonSession, ...] = ()
    topic_coverage: tuple[TopicEvidenceCoverage, ...] = ()
    experiments: tuple[LessonExperiment, ...] = ()


@dataclass(frozen=True, slots=True)
class LessonPlanRevision:
    revision_number: int
    source: str
    restored_from_revision: int | None
    created_by: str
    created_at: datetime
    change_summary: str
    content: LessonPlanContent
    content_sha256: str
    evidence_fingerprint: str
    model_adapter: str | None
    prompt_template_version: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class LessonPlanRecord:
    plan_id: str
    workspace_id: str
    owner_school_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    status: LessonPlanStatus
    current_revision_number: int
    confirmed_revision_number: int | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    revision: LessonPlanRevision


@dataclass(frozen=True, slots=True)
class LessonPlanMutationResult:
    plan: LessonPlanRecord
    reused: bool = False


@dataclass(frozen=True, slots=True)
class LessonPlanRevisionSummary:
    revision_number: int
    source: str
    restored_from_revision: int | None
    created_by: str
    created_at: datetime
    change_summary: str
    content_sha256: str


class LessonPlanCatalogBackend(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def generate(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        generation: LessonPlanGenerationInput,
        *,
        request_id: str,
    ) -> LessonPlanMutationResult: ...

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> LessonPlanRecord: ...

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
    ) -> LessonPlanMutationResult: ...

    def revisions(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> tuple[LessonPlanRevisionSummary, ...]: ...

    def compare(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        from_revision: int,
        to_revision: int,
    ) -> dict[str, Any]: ...

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
    ) -> LessonPlanMutationResult: ...

    def confirm(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        revision_number: int,
        *,
        request_id: str,
    ) -> LessonPlanMutationResult: ...

    def export(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> LessonPlanRecord: ...


class DisabledLessonPlanCatalog:
    @property
    def configured(self) -> bool:
        return False

    @property
    def backend(self) -> str:
        return "disabled"

    def _fail(self) -> None:
        raise LessonPlanCatalogNotConfiguredError("lesson plan catalog requires PostgreSQL")

    def generate(self, *args: object, **kwargs: object) -> LessonPlanMutationResult:
        del args, kwargs
        self._fail()

    def get(self, *args: object, **kwargs: object) -> LessonPlanRecord:
        del args, kwargs
        self._fail()

    def save(self, *args: object, **kwargs: object) -> LessonPlanMutationResult:
        del args, kwargs
        self._fail()

    def revisions(self, *args: object, **kwargs: object) -> tuple[LessonPlanRevisionSummary, ...]:
        del args, kwargs
        self._fail()

    def compare(self, *args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        self._fail()

    def restore(self, *args: object, **kwargs: object) -> LessonPlanMutationResult:
        del args, kwargs
        self._fail()

    def confirm(self, *args: object, **kwargs: object) -> LessonPlanMutationResult:
        del args, kwargs
        self._fail()

    def export(self, *args: object, **kwargs: object) -> LessonPlanRecord:
        del args, kwargs
        self._fail()


def build_lesson_plan_catalog(database_url: str | None) -> LessonPlanCatalogBackend:
    if database_url is not None and database_url.strip():
        from app.postgres_lesson_plan_service import PostgresLessonPlanCatalog

        return PostgresLessonPlanCatalog(database_url)
    return DisabledLessonPlanCatalog()


def serialize_lesson_plan(plan: LessonPlanRecord) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "workspace_id": plan.workspace_id,
        "owner_school_id": plan.owner_school_id,
        "created_by": plan.created_by,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
        "status": str(plan.status),
        "current_revision_number": plan.current_revision_number,
        "confirmed_revision_number": plan.confirmed_revision_number,
        "confirmed_by": plan.confirmed_by,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "export_ready": plan.status is LessonPlanStatus.TEACHER_CONFIRMED,
        "revision": serialize_revision(plan.revision),
    }


def serialize_revision(revision: LessonPlanRevision) -> dict[str, Any]:
    return {
        "revision_number": revision.revision_number,
        "source": revision.source,
        "restored_from_revision": revision.restored_from_revision,
        "created_by": revision.created_by,
        "created_at": revision.created_at.isoformat(),
        "change_summary": revision.change_summary,
        "content": revision.content.to_payload(),
        "content_sha256": revision.content_sha256,
        "evidence_fingerprint": revision.evidence_fingerprint,
        "model_adapter": revision.model_adapter,
        "prompt_template_version": revision.prompt_template_version,
        "schema_version": revision.schema_version,
    }


def serialize_revision_summary(summary: LessonPlanRevisionSummary) -> dict[str, Any]:
    return {
        "revision_number": summary.revision_number,
        "source": summary.source,
        "restored_from_revision": summary.restored_from_revision,
        "created_by": summary.created_by,
        "created_at": summary.created_at.isoformat(),
        "change_summary": summary.change_summary,
        "content_sha256": summary.content_sha256,
    }
