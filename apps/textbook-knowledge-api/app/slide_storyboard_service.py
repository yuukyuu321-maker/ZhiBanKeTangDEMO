"""Slide-storyboard revision contract and response serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from athena_domain import (
    SlideStoryboardContent,
    SlideStoryboardStatus,
)


class SlideStoryboardCatalogNotConfiguredError(RuntimeError):
    pass


class SlideStoryboardNotFoundError(LookupError):
    pass


class SlideStoryboardConflictError(RuntimeError):
    pass


class SlideStoryboardEvidenceError(ValueError):
    pass


class SlideStoryboardConfirmationError(PermissionError):
    pass


class SlideStoryboardSourceChangedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SlideStoryboardRevision:
    revision_number: int
    source: str
    restored_from_revision: int | None
    created_by: str
    created_at: datetime
    change_summary: str
    content: SlideStoryboardContent
    content_sha256: str
    evidence_fingerprint: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class SlideStoryboardRecord:
    storyboard_id: str
    workspace_id: str
    owner_school_id: str
    lesson_plan_id: str
    source_lesson_revision: int
    source_lesson_content_sha256: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    status: SlideStoryboardStatus
    current_revision_number: int
    confirmed_revision_number: int | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    source_current: bool
    revision: SlideStoryboardRevision


@dataclass(frozen=True, slots=True)
class SlideStoryboardMutationResult:
    storyboard: SlideStoryboardRecord
    reused: bool = False


class SlideStoryboardCatalogBackend(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def generate(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        *,
        template_id: str,
        request_id: str,
    ) -> SlideStoryboardMutationResult: ...

    def get(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> SlideStoryboardRecord: ...

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
    ) -> SlideStoryboardMutationResult: ...

    def confirm(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
        revision_number: int,
        *,
        request_id: str,
    ) -> SlideStoryboardMutationResult: ...

    def export(
        self,
        workspace_id: str,
        principal_id: str,
        school_id: str,
    ) -> SlideStoryboardRecord: ...


class DisabledSlideStoryboardCatalog:
    @property
    def configured(self) -> bool:
        return False

    @property
    def backend(self) -> str:
        return "disabled"

    def _fail(self) -> None:
        raise SlideStoryboardCatalogNotConfiguredError(
            "slide storyboard catalog requires PostgreSQL"
        )

    def generate(self, *args: object, **kwargs: object) -> SlideStoryboardMutationResult:
        del args, kwargs
        self._fail()

    def get(self, *args: object, **kwargs: object) -> SlideStoryboardRecord:
        del args, kwargs
        self._fail()

    def save(self, *args: object, **kwargs: object) -> SlideStoryboardMutationResult:
        del args, kwargs
        self._fail()

    def confirm(self, *args: object, **kwargs: object) -> SlideStoryboardMutationResult:
        del args, kwargs
        self._fail()

    def export(self, *args: object, **kwargs: object) -> SlideStoryboardRecord:
        del args, kwargs
        self._fail()


def build_slide_storyboard_catalog(
    database_url: str | None,
) -> SlideStoryboardCatalogBackend:
    if database_url is not None and database_url.strip():
        from app.postgres_slide_storyboard_service import PostgresSlideStoryboardCatalog

        return PostgresSlideStoryboardCatalog(database_url)
    return DisabledSlideStoryboardCatalog()


def serialize_slide_storyboard(storyboard: SlideStoryboardRecord) -> dict[str, Any]:
    return {
        "storyboard_id": storyboard.storyboard_id,
        "workspace_id": storyboard.workspace_id,
        "owner_school_id": storyboard.owner_school_id,
        "lesson_plan_id": storyboard.lesson_plan_id,
        "source_lesson_revision": storyboard.source_lesson_revision,
        "source_lesson_content_sha256": storyboard.source_lesson_content_sha256,
        "created_by": storyboard.created_by,
        "created_at": storyboard.created_at.isoformat(),
        "updated_at": storyboard.updated_at.isoformat(),
        "status": str(storyboard.status),
        "current_revision_number": storyboard.current_revision_number,
        "confirmed_revision_number": storyboard.confirmed_revision_number,
        "confirmed_by": storyboard.confirmed_by,
        "confirmed_at": (
            storyboard.confirmed_at.isoformat() if storyboard.confirmed_at else None
        ),
        "source_current": storyboard.source_current,
        "export_ready": (
            storyboard.status is SlideStoryboardStatus.TEACHER_CONFIRMED
            and storyboard.source_current
        ),
        "revision": {
            "revision_number": storyboard.revision.revision_number,
            "source": storyboard.revision.source,
            "restored_from_revision": storyboard.revision.restored_from_revision,
            "created_by": storyboard.revision.created_by,
            "created_at": storyboard.revision.created_at.isoformat(),
            "change_summary": storyboard.revision.change_summary,
            "content": storyboard.revision.content.to_payload(),
            "content_sha256": storyboard.revision.content_sha256,
            "evidence_fingerprint": storyboard.revision.evidence_fingerprint,
            "schema_version": storyboard.revision.schema_version,
        },
    }
