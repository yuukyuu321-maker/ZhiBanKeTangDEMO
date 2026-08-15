"""FastAPI entry point for the textbook knowledge MVP."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import uuid4

from athena_domain import (
    DEFAULT_STORYBOARD_TEMPLATE_ID,
    AssignmentConflictError,
    AssignmentNotFoundError,
    ExperimentMode,
    LessonExperiment,
    LessonPlanContent,
    LessonSession,
    LessonSessionKind,
    SlideStoryboardContent,
    TeachingScope,
    TeachingScopeUnauthorizedError,
    TextbookEditionInactiveError,
    TopicCoverageStatus,
    TopicEvidenceCoverage,
)
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.assignment_service import (
    AssignmentCatalogNotConfiguredError,
    build_assignment_catalog,
    serialize_resolution,
)
from app.lesson_plan_service import (
    LessonPlanCatalogNotConfiguredError,
    LessonPlanConfirmationError,
    LessonPlanConflictError,
    LessonPlanEvidenceError,
    LessonPlanGenerationInput,
    LessonPlanNotFoundError,
    build_lesson_plan_catalog,
    serialize_lesson_plan,
    serialize_revision_summary,
)
from app.service import BundleCatalog, BundleNotFoundError, BundleNotReadableError
from app.slide_storyboard_service import (
    SlideStoryboardCatalogNotConfiguredError,
    SlideStoryboardConfirmationError,
    SlideStoryboardConflictError,
    SlideStoryboardEvidenceError,
    SlideStoryboardNotFoundError,
    SlideStoryboardSourceChangedError,
    build_slide_storyboard_catalog,
    serialize_slide_storyboard,
)
from app.workspace_service import (
    WorkspaceCatalogNotConfiguredError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspaceUnauthorizedError,
    build_workspace_catalog,
    serialize_workspace,
)


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _allowed_origins() -> list[str]:
    configured = os.getenv("ATHENA_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


app = FastAPI(
    title="Project Athena Textbook Knowledge API",
    version="0.6.0",
    description=(
        "教材适用关系解析、教材内检索和可定位页面证据 API。"
        "模型常识和联网搜索不属于此接口的证据来源。"
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Athena-Principal-Id", "X-Athena-Request-Id"],
)

catalog = BundleCatalog(
    Path(os.getenv("ATHENA_IMPORT_DIR", "./data/imports")),
    allow_needs_review=_enabled("ATHENA_LOCAL_REVIEW_MODE"),
)
database_url = os.getenv("ATHENA_DATABASE_URL")
assignment_catalog = build_assignment_catalog(
    database_url,
    os.getenv("ATHENA_ASSIGNMENT_CATALOG"),
)
workspace_catalog = build_workspace_catalog(database_url)
lesson_plan_catalog = build_lesson_plan_catalog(database_url)
slide_storyboard_catalog = build_slide_storyboard_catalog(database_url)


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    assignment_catalog_configured: bool
    assignment_catalog_backend: str
    workspace_catalog_configured: bool
    workspace_catalog_backend: str
    lesson_plan_catalog_configured: bool
    lesson_plan_catalog_backend: str
    slide_storyboard_catalog_configured: bool
    slide_storyboard_catalog_backend: str
    external_model_enabled: bool = False
    web_search_enabled: bool = False


@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        assignment_catalog_configured=assignment_catalog.configured,
        assignment_catalog_backend=assignment_catalog.backend,
        workspace_catalog_configured=workspace_catalog.configured,
        workspace_catalog_backend=workspace_catalog.backend,
        lesson_plan_catalog_configured=lesson_plan_catalog.configured,
        lesson_plan_catalog_backend=lesson_plan_catalog.backend,
        slide_storyboard_catalog_configured=slide_storyboard_catalog.configured,
        slide_storyboard_catalog_backend=slide_storyboard_catalog.backend,
    )


class SearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]
    evidence_required: bool = True


class AssignedSearchResponse(SearchResponse):
    resolution: dict[str, Any]


class WorkspaceCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    school_id: str = Field(min_length=1)
    academic_year: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    campus_id: str | None = None
    class_id: str | None = None
    on_date: date | None = None


class WorkspaceResponse(BaseModel):
    workspace: dict[str, Any]
    reused: bool = False


class WorkspaceSearchResponse(SearchResponse):
    workspace: dict[str, Any]


class LessonSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    minutes: int = Field(ge=5, le=180)
    kind: str = Field(pattern="^(instruction|demonstration|student_lab|mixed)$")


class TopicEvidenceRequest(BaseModel):
    topic_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    status: str = Field(pattern="^(covered|partial|missing)$")
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=1000)


class LessonExperimentRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    session_id: str = Field(min_length=1, max_length=128)
    minutes: int = Field(ge=1, le=180)
    mode: str = Field(pattern="^(demonstration|student_lab|demonstration_and_student)$")
    topic_ids: list[str] = Field(min_length=1, max_length=30)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    integrated_steps: list[str] = Field(default_factory=list, max_length=30)
    safety_notes: list[str] = Field(default_factory=list, max_length=30)
    teacher_safety_confirmed: bool = False


class LessonPlanGenerateRequest(BaseModel):
    school_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    objectives: list[str] = Field(min_length=1, max_length=20)
    required_topics: list[str] = Field(default_factory=list, max_length=30)
    lesson_count: int = Field(default=1, ge=1, le=8)
    minutes_per_lesson: int = Field(default=40, ge=10, le=180)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    preserve_experiment: bool = False
    instruction: str = Field(min_length=1, max_length=2000)
    sessions: list[LessonSessionRequest] = Field(default_factory=list, max_length=8)
    topic_coverage: list[TopicEvidenceRequest] = Field(default_factory=list, max_length=30)
    experiments: list[LessonExperimentRequest] = Field(default_factory=list, max_length=20)


class LessonPlanSaveRequest(BaseModel):
    school_id: str = Field(min_length=1)
    base_revision_number: int = Field(ge=1)
    change_summary: str = Field(min_length=1, max_length=500)
    content: dict[str, Any]


class LessonPlanRestoreRequest(BaseModel):
    school_id: str = Field(min_length=1)
    base_revision_number: int = Field(ge=1)
    change_summary: str = Field(min_length=1, max_length=500)


class LessonPlanConfirmRequest(BaseModel):
    school_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)


class LessonPlanResponse(BaseModel):
    plan: dict[str, Any]
    reused: bool = False


class SlideStoryboardGenerateRequest(BaseModel):
    school_id: str = Field(min_length=1)
    template_id: str = Field(default=DEFAULT_STORYBOARD_TEMPLATE_ID, min_length=1)


class SlideStoryboardSaveRequest(BaseModel):
    school_id: str = Field(min_length=1)
    base_revision_number: int = Field(ge=1)
    change_summary: str = Field(min_length=1, max_length=500)
    content: dict[str, Any]


class SlideStoryboardConfirmRequest(BaseModel):
    school_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)


class SlideStoryboardResponse(BaseModel):
    storyboard: dict[str, Any]
    reused: bool = False


def _translate_error(error: Exception) -> HTTPException:
    if isinstance(
        error,
        AssignmentCatalogNotConfiguredError
        | WorkspaceCatalogNotConfiguredError
        | LessonPlanCatalogNotConfiguredError
        | SlideStoryboardCatalogNotConfiguredError,
    ):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(
        error,
        TeachingScopeUnauthorizedError | WorkspaceUnauthorizedError,
    ):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, TextbookEditionInactiveError):
        return HTTPException(status_code=410, detail=str(error))
    if isinstance(
        error,
        AssignmentConflictError
        | WorkspaceConflictError
        | LessonPlanConflictError
        | SlideStoryboardConflictError
        | SlideStoryboardSourceChangedError,
    ):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(
        error,
        AssignmentNotFoundError
        | BundleNotFoundError
        | WorkspaceNotFoundError
        | LessonPlanNotFoundError
        | SlideStoryboardNotFoundError,
    ):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, BundleNotReadableError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, LessonPlanConfirmationError | SlideStoryboardConfirmationError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(
        error, LessonPlanEvidenceError | SlideStoryboardEvidenceError | ValueError
    ):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(status_code=500, detail="textbook request could not be completed")


def _request_id(value: str | None) -> str:
    if value is not None and value.strip():
        return value.strip()
    return str(uuid4())


def _scope(
    school_id: str,
    academic_year: str,
    grade: str,
    subject: str,
    campus_id: str | None,
    class_id: str | None,
) -> TeachingScope:
    return TeachingScope(
        school_id=school_id,
        academic_year=academic_year,
        grade=grade,
        subject=subject,
        campus_id=campus_id,
        class_id=class_id,
    )


def _search_results(
    edition_id: str,
    source_sha256: str,
    query: str,
    limit: int,
    *,
    workspace_id: str | None = None,
    school_id: str | None = None,
) -> list[dict[str, Any]]:
    results = catalog.search(edition_id, source_sha256, query, limit)
    enriched: list[dict[str, Any]] = []
    for result in results:
        evidence = dict(result["evidence"])
        pdf_page_index = int(evidence["pdf_page_index"])
        page = catalog.page(edition_id, source_sha256, pdf_page_index)
        render_available = bool(page.get("render_uri"))
        enriched.append(
            {
                "score": result["score"],
                "evidence": evidence,
                "page": {
                    "pdf_page_index": pdf_page_index,
                    "page_label": page.get("page_label"),
                    "printed_page": page.get("printed_page"),
                    "width": page.get("width"),
                    "height": page.get("height"),
                    "render_available": render_available,
                },
                "render_url": _render_url(
                    edition_id,
                    source_sha256,
                    pdf_page_index,
                    render_available,
                    workspace_id=workspace_id,
                    school_id=school_id,
                ),
            }
        )
    return enriched


def _render_url(
    edition_id: str,
    source_sha256: str,
    pdf_page_index: int,
    render_available: bool,
    *,
    workspace_id: str | None,
    school_id: str | None,
) -> str | None:
    if not render_available:
        return None
    if workspace_id is not None:
        if school_id is None:
            raise ValueError("school_id is required for a workspace render URL")
        query = urlencode({"school_id": school_id})
        return f"/v1/workspaces/{workspace_id}/pages/{pdf_page_index}/render?{query}"
    return f"/v1/textbooks/{edition_id}/imports/{source_sha256}/pages/{pdf_page_index}/render"


@app.get("/v1/textbooks/resolve", tags=["assignments"])
def resolve_textbook(
    school_id: str = Query(min_length=1),
    academic_year: str = Query(min_length=1),
    grade: str = Query(min_length=1),
    subject: str = Query(min_length=1),
    campus_id: str | None = Query(default=None),
    class_id: str | None = Query(default=None),
    on_date: Annotated[date | None, Query()] = None,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> dict[str, Any]:
    try:
        resolved = assignment_catalog.resolve(
            principal_id,
            _scope(
                school_id,
                academic_year,
                grade,
                subject,
                campus_id,
                class_id,
            ),
            on_date=on_date,
        )
        return serialize_resolution(resolved)
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/textbooks/assigned-search",
    response_model=AssignedSearchResponse,
    tags=["assignments", "search"],
)
def search_assigned_textbook(
    q: str = Query(min_length=1, max_length=200),
    school_id: str = Query(min_length=1),
    academic_year: str = Query(min_length=1),
    grade: str = Query(min_length=1),
    subject: str = Query(min_length=1),
    campus_id: str | None = Query(default=None),
    class_id: str | None = Query(default=None),
    on_date: Annotated[date | None, Query()] = None,
    limit: int = Query(default=10, ge=1, le=50),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> AssignedSearchResponse:
    try:
        resolved = assignment_catalog.resolve(
            principal_id,
            _scope(
                school_id,
                academic_year,
                grade,
                subject,
                campus_id,
                class_id,
            ),
            on_date=on_date,
        )
        registration = resolved.registration
        results = _search_results(
            registration.edition_id,
            registration.source_sha256,
            q,
            limit,
        )
        return AssignedSearchResponse(
            query=q,
            results=results,
            resolution=serialize_resolution(resolved),
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces",
    response_model=WorkspaceResponse,
    status_code=201,
    tags=["workspaces"],
)
def create_workspace(
    request: WorkspaceCreateRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> WorkspaceResponse:
    try:
        result = workspace_catalog.pin(
            request.workspace_id,
            principal_id,
            _scope(
                request.school_id,
                request.academic_year,
                request.grade,
                request.subject,
                request.campus_id,
                request.class_id,
            ),
            on_date=request.on_date,
        )
        return WorkspaceResponse(
            workspace=serialize_workspace(result.workspace),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}",
    response_model=WorkspaceResponse,
    tags=["workspaces"],
)
def get_workspace(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> WorkspaceResponse:
    try:
        workspace = workspace_catalog.get(workspace_id, principal_id, school_id)
        return WorkspaceResponse(workspace=serialize_workspace(workspace))
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/search",
    response_model=WorkspaceSearchResponse,
    tags=["workspaces", "search"],
)
def search_workspace(
    workspace_id: str,
    q: str = Query(min_length=1, max_length=200),
    school_id: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> WorkspaceSearchResponse:
    try:
        workspace = workspace_catalog.get(workspace_id, principal_id, school_id)
        results = _search_results(
            workspace.edition_id,
            workspace.source_sha256,
            q,
            limit,
            workspace_id=workspace.workspace_id,
            school_id=workspace.owner_school_id,
        )
        return WorkspaceSearchResponse(
            query=q,
            results=results,
            workspace=serialize_workspace(workspace),
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/pages/{pdf_page_index}/render",
    tags=["workspaces"],
    response_class=FileResponse,
)
def get_workspace_page_render(
    workspace_id: str,
    pdf_page_index: int,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> FileResponse:
    try:
        workspace = workspace_catalog.get(workspace_id, principal_id, school_id)
        path = catalog.render_path(
            workspace.edition_id,
            workspace.source_sha256,
            pdf_page_index,
        )
        return FileResponse(path, media_type="image/png", filename=path.name)
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces/{workspace_id}/lesson-plan/generate",
    response_model=LessonPlanResponse,
    status_code=201,
    tags=["lesson-plans"],
)
def generate_lesson_plan(
    workspace_id: str,
    request: LessonPlanGenerateRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> LessonPlanResponse:
    try:
        result = lesson_plan_catalog.generate(
            workspace_id,
            principal_id,
            request.school_id,
            LessonPlanGenerationInput(
                title=request.title,
                objectives=tuple(request.objectives),
                required_topics=tuple(request.required_topics),
                lesson_count=request.lesson_count,
                minutes_per_lesson=request.minutes_per_lesson,
                evidence_ids=tuple(dict.fromkeys(request.evidence_ids)),
                preserve_experiment=request.preserve_experiment,
                instruction=request.instruction,
                sessions=tuple(
                    LessonSession(
                        session_id=item.session_id,
                        title=item.title,
                        minutes=item.minutes,
                        kind=LessonSessionKind(item.kind),
                    )
                    for item in request.sessions
                ),
                topic_coverage=tuple(
                    TopicEvidenceCoverage(
                        topic_id=item.topic_id,
                        title=item.title,
                        status=TopicCoverageStatus(item.status),
                        evidence_ids=tuple(dict.fromkeys(item.evidence_ids)),
                        notes=item.notes,
                    )
                    for item in request.topic_coverage
                ),
                experiments=tuple(
                    LessonExperiment(
                        experiment_id=item.experiment_id,
                        title=item.title,
                        session_id=item.session_id,
                        minutes=item.minutes,
                        mode=ExperimentMode(item.mode),
                        topic_ids=tuple(dict.fromkeys(item.topic_ids)),
                        evidence_ids=tuple(dict.fromkeys(item.evidence_ids)),
                        integrated_steps=tuple(item.integrated_steps),
                        safety_notes=tuple(item.safety_notes),
                        teacher_safety_confirmed=item.teacher_safety_confirmed,
                    )
                    for item in request.experiments
                ),
            ),
            request_id=_request_id(request_id),
        )
        return LessonPlanResponse(
            plan=serialize_lesson_plan(result.plan),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/lesson-plan",
    response_model=LessonPlanResponse,
    tags=["lesson-plans"],
)
def get_lesson_plan(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> LessonPlanResponse:
    try:
        plan = lesson_plan_catalog.get(workspace_id, principal_id, school_id)
        return LessonPlanResponse(plan=serialize_lesson_plan(plan))
    except Exception as error:
        raise _translate_error(error) from error


@app.put(
    "/v1/workspaces/{workspace_id}/lesson-plan",
    response_model=LessonPlanResponse,
    tags=["lesson-plans"],
)
def save_lesson_plan(
    workspace_id: str,
    request: LessonPlanSaveRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> LessonPlanResponse:
    try:
        result = lesson_plan_catalog.save(
            workspace_id,
            principal_id,
            request.school_id,
            LessonPlanContent.from_payload(request.content),
            base_revision_number=request.base_revision_number,
            change_summary=request.change_summary,
            request_id=_request_id(request_id),
        )
        return LessonPlanResponse(
            plan=serialize_lesson_plan(result.plan),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/lesson-plan/revisions",
    tags=["lesson-plans"],
)
def list_lesson_plan_revisions(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> dict[str, Any]:
    try:
        revisions = lesson_plan_catalog.revisions(workspace_id, principal_id, school_id)
        return {"revisions": [serialize_revision_summary(item) for item in revisions]}
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/lesson-plan/compare",
    tags=["lesson-plans"],
)
def compare_lesson_plan_revisions(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    from_revision: int = Query(ge=1),
    to_revision: int = Query(ge=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> dict[str, Any]:
    try:
        return lesson_plan_catalog.compare(
            workspace_id,
            principal_id,
            school_id,
            from_revision,
            to_revision,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces/{workspace_id}/lesson-plan/revisions/{revision_number}/restore",
    response_model=LessonPlanResponse,
    tags=["lesson-plans"],
)
def restore_lesson_plan_revision(
    workspace_id: str,
    revision_number: int,
    request: LessonPlanRestoreRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> LessonPlanResponse:
    try:
        result = lesson_plan_catalog.restore(
            workspace_id,
            principal_id,
            request.school_id,
            revision_number,
            base_revision_number=request.base_revision_number,
            change_summary=request.change_summary,
            request_id=_request_id(request_id),
        )
        return LessonPlanResponse(plan=serialize_lesson_plan(result.plan))
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces/{workspace_id}/lesson-plan/confirm",
    response_model=LessonPlanResponse,
    tags=["lesson-plans"],
)
def confirm_lesson_plan(
    workspace_id: str,
    request: LessonPlanConfirmRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> LessonPlanResponse:
    try:
        result = lesson_plan_catalog.confirm(
            workspace_id,
            principal_id,
            request.school_id,
            request.revision_number,
            request_id=_request_id(request_id),
        )
        return LessonPlanResponse(
            plan=serialize_lesson_plan(result.plan),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/lesson-plan/export",
    tags=["lesson-plans"],
)
def export_lesson_plan(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> dict[str, Any]:
    try:
        plan = lesson_plan_catalog.export(workspace_id, principal_id, school_id)
        return {
            "export_format": "athena.lesson-plan.json.v1",
            "teacher_confirmed": True,
            "plan": serialize_lesson_plan(plan),
        }
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces/{workspace_id}/slide-storyboard/generate",
    response_model=SlideStoryboardResponse,
    status_code=201,
    tags=["slide-storyboards"],
)
def generate_slide_storyboard(
    workspace_id: str,
    request: SlideStoryboardGenerateRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> SlideStoryboardResponse:
    try:
        result = slide_storyboard_catalog.generate(
            workspace_id,
            principal_id,
            request.school_id,
            template_id=request.template_id,
            request_id=_request_id(request_id),
        )
        return SlideStoryboardResponse(
            storyboard=serialize_slide_storyboard(result.storyboard),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/slide-storyboard",
    response_model=SlideStoryboardResponse,
    tags=["slide-storyboards"],
)
def get_slide_storyboard(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> SlideStoryboardResponse:
    try:
        storyboard = slide_storyboard_catalog.get(
            workspace_id, principal_id, school_id
        )
        return SlideStoryboardResponse(
            storyboard=serialize_slide_storyboard(storyboard)
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.put(
    "/v1/workspaces/{workspace_id}/slide-storyboard",
    response_model=SlideStoryboardResponse,
    tags=["slide-storyboards"],
)
def save_slide_storyboard(
    workspace_id: str,
    request: SlideStoryboardSaveRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> SlideStoryboardResponse:
    try:
        result = slide_storyboard_catalog.save(
            workspace_id,
            principal_id,
            request.school_id,
            SlideStoryboardContent.from_payload(request.content),
            base_revision_number=request.base_revision_number,
            change_summary=request.change_summary,
            request_id=_request_id(request_id),
        )
        return SlideStoryboardResponse(
            storyboard=serialize_slide_storyboard(result.storyboard),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.post(
    "/v1/workspaces/{workspace_id}/slide-storyboard/confirm",
    response_model=SlideStoryboardResponse,
    tags=["slide-storyboards"],
)
def confirm_slide_storyboard(
    workspace_id: str,
    request: SlideStoryboardConfirmRequest,
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
    request_id: str | None = Header(default=None, alias="X-Athena-Request-Id"),
) -> SlideStoryboardResponse:
    try:
        result = slide_storyboard_catalog.confirm(
            workspace_id,
            principal_id,
            request.school_id,
            request.revision_number,
            request_id=_request_id(request_id),
        )
        return SlideStoryboardResponse(
            storyboard=serialize_slide_storyboard(result.storyboard),
            reused=result.reused,
        )
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/workspaces/{workspace_id}/slide-storyboard/export",
    tags=["slide-storyboards"],
)
def export_slide_storyboard(
    workspace_id: str,
    school_id: str = Query(min_length=1),
    principal_id: str = Header(alias="X-Athena-Principal-Id", min_length=1),
) -> dict[str, Any]:
    try:
        storyboard = slide_storyboard_catalog.export(
            workspace_id, principal_id, school_id
        )
        return {
            "export_format": "athena.slide-storyboard.json.v1",
            "teacher_confirmed": True,
            "storyboard": serialize_slide_storyboard(storyboard),
        }
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/textbooks/{edition_id}/imports/{source_sha256}",
    tags=["textbooks"],
)
def describe_import(edition_id: str, source_sha256: str) -> dict[str, Any]:
    try:
        return catalog.describe(edition_id, source_sha256)
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/textbooks/{edition_id}/imports/{source_sha256}/pages",
    tags=["textbooks"],
)
def list_pages(
    edition_id: str,
    source_sha256: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    try:
        pages = catalog.pages(edition_id, source_sha256, offset=offset, limit=limit)
        return {"offset": offset, "limit": limit, "pages": pages}
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/textbooks/{edition_id}/imports/{source_sha256}/pages/{pdf_page_index}/render",
    tags=["textbooks"],
    response_class=FileResponse,
)
def get_page_render(edition_id: str, source_sha256: str, pdf_page_index: int) -> FileResponse:
    try:
        path = catalog.render_path(edition_id, source_sha256, pdf_page_index)
        return FileResponse(path, media_type="image/png", filename=path.name)
    except Exception as error:
        raise _translate_error(error) from error


@app.get(
    "/v1/textbooks/{edition_id}/imports/{source_sha256}/search",
    response_model=SearchResponse,
    tags=["search"],
)
def search_textbook(
    edition_id: str,
    source_sha256: str,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
) -> SearchResponse:
    try:
        results = _search_results(edition_id, source_sha256, q, limit)
        return SearchResponse(query=q, results=results)
    except Exception as error:
        raise _translate_error(error) from error
