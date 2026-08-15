"""Evidence-bound slide storyboards derived from confirmed lesson plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .lesson_plan_v2 import LessonPlanContent

SLIDE_STORYBOARD_SCHEMA_VERSION = "athena.slide-storyboard.v1"
DEFAULT_STORYBOARD_TEMPLATE_ID = "simple-classroom"
DEFAULT_STORYBOARD_TEMPLATE_VERSION = "athena.simple-classroom.v1"


class SlideLayout(StrEnum):
    OPENING = "opening"
    CONCEPT = "concept"
    EVIDENCE = "evidence"
    EXPERIMENT = "experiment"
    SUMMARY = "summary"


class SlideStoryboardStatus(StrEnum):
    DRAFT = "draft"
    TEACHER_CONFIRMED = "teacher_confirmed"


class SlideStoryboardRevisionSource(StrEnum):
    GENERATED = "generated"
    TEACHER_EDIT = "teacher_edit"
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class StoryboardSlide:
    slide_id: str
    title: str
    purpose: str
    bullets: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    session_id: str
    topic_ids: tuple[str, ...]
    speaker_notes: tuple[str, ...]
    estimated_minutes: int
    layout: SlideLayout
    visual_suggestion: str

    def __post_init__(self) -> None:
        for name, value in (
            ("slide_id", self.slide_id),
            ("title", self.title),
            ("purpose", self.purpose),
            ("session_id", self.session_id),
            ("visual_suggestion", self.visual_suggestion),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        for name, values in (
            ("bullets", self.bullets),
            ("evidence_ids", self.evidence_ids),
            ("topic_ids", self.topic_ids),
            ("speaker_notes", self.speaker_notes),
        ):
            if not values or any(not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-blank values")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique values")
        if self.estimated_minutes <= 0:
            raise ValueError("estimated_minutes must be positive")

    def to_payload(self) -> dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "title": self.title,
            "purpose": self.purpose,
            "bullets": list(self.bullets),
            "evidence_ids": list(self.evidence_ids),
            "session_id": self.session_id,
            "topic_ids": list(self.topic_ids),
            "speaker_notes": list(self.speaker_notes),
            "estimated_minutes": self.estimated_minutes,
            "layout": str(self.layout),
            "visual_suggestion": self.visual_suggestion,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> StoryboardSlide:
        allowed = {
            "slide_id",
            "title",
            "purpose",
            "bullets",
            "evidence_ids",
            "session_id",
            "topic_ids",
            "speaker_notes",
            "estimated_minutes",
            "layout",
            "visual_suggestion",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unsupported slide fields: {', '.join(sorted(unknown))}")
        return cls(
            slide_id=_text(payload, "slide_id"),
            title=_text(payload, "title"),
            purpose=_text(payload, "purpose"),
            bullets=_text_tuple(payload, "bullets"),
            evidence_ids=_text_tuple(payload, "evidence_ids"),
            session_id=_text(payload, "session_id"),
            topic_ids=_text_tuple(payload, "topic_ids"),
            speaker_notes=_text_tuple(payload, "speaker_notes"),
            estimated_minutes=_positive_int(payload, "estimated_minutes"),
            layout=SlideLayout(_text(payload, "layout")),
            visual_suggestion=_text(payload, "visual_suggestion"),
        )


@dataclass(frozen=True, slots=True)
class SlideStoryboardContent:
    title: str
    source_lesson_plan_id: str
    source_lesson_revision: int
    source_lesson_content_sha256: str
    template_id: str
    template_version: str
    slides: tuple[StoryboardSlide, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("title", self.title),
            ("source_lesson_plan_id", self.source_lesson_plan_id),
            ("source_lesson_content_sha256", self.source_lesson_content_sha256),
            ("template_id", self.template_id),
            ("template_version", self.template_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.source_lesson_revision <= 0:
            raise ValueError("source_lesson_revision must be positive")
        if len(self.source_lesson_content_sha256) != 64:
            raise ValueError("source_lesson_content_sha256 must be a SHA-256 digest")
        if not self.slides:
            raise ValueError("storyboard must contain at least one slide")
        slide_ids = [slide.slide_id for slide in self.slides]
        if len(set(slide_ids)) != len(slide_ids):
            raise ValueError("slide identifiers must be unique")

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                evidence_id
                for slide in self.slides
                for evidence_id in slide.evidence_ids
            )
        )

    @property
    def estimated_minutes(self) -> int:
        return sum(slide.estimated_minutes for slide in self.slides)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SLIDE_STORYBOARD_SCHEMA_VERSION,
            "title": self.title,
            "source_lesson_plan_id": self.source_lesson_plan_id,
            "source_lesson_revision": self.source_lesson_revision,
            "source_lesson_content_sha256": self.source_lesson_content_sha256,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "slides": [slide.to_payload() for slide in self.slides],
            "summary": {
                "slide_count": len(self.slides),
                "estimated_minutes": self.estimated_minutes,
                "evidence_count": len(self.evidence_ids),
            },
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SlideStoryboardContent:
        allowed = {
            "schema_version",
            "title",
            "source_lesson_plan_id",
            "source_lesson_revision",
            "source_lesson_content_sha256",
            "template_id",
            "template_version",
            "slides",
            "summary",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unsupported storyboard fields: {', '.join(sorted(unknown))}")
        if payload.get("schema_version") != SLIDE_STORYBOARD_SCHEMA_VERSION:
            raise ValueError("unsupported slide storyboard schema version")
        slides_value = payload.get("slides")
        if not isinstance(slides_value, list) or not all(
            isinstance(item, dict) for item in slides_value
        ):
            raise ValueError("slides must be a list of objects")
        content = cls(
            title=_text(payload, "title"),
            source_lesson_plan_id=_text(payload, "source_lesson_plan_id"),
            source_lesson_revision=_positive_int(payload, "source_lesson_revision"),
            source_lesson_content_sha256=_text(payload, "source_lesson_content_sha256"),
            template_id=_text(payload, "template_id"),
            template_version=_text(payload, "template_version"),
            slides=tuple(StoryboardSlide.from_payload(item) for item in slides_value),
        )
        supplied_summary = payload.get("summary")
        if supplied_summary is not None and supplied_summary != content.to_payload()["summary"]:
            raise ValueError("storyboard summary does not match slide content")
        return content


def build_deterministic_storyboard(
    *,
    lesson_plan_id: str,
    lesson_revision: int,
    lesson_content_sha256: str,
    lesson: LessonPlanContent,
    template_id: str = DEFAULT_STORYBOARD_TEMPLATE_ID,
) -> SlideStoryboardContent:
    """Map each evidence-bound lesson segment to one editable slide."""

    if template_id != DEFAULT_STORYBOARD_TEMPLATE_ID:
        raise ValueError("unsupported storyboard template")
    topics = {item.topic_id: item.title for item in lesson.topic_coverage}
    experiments = {item.experiment_id: item for item in lesson.experiments}
    slides: list[StoryboardSlide] = []
    for index, segment in enumerate(lesson.lesson_segments):
        experiment = experiments.get(segment.segment_id)
        topic_titles = tuple(topics[item] for item in segment.topic_ids if item in topics)
        bullets = tuple(
            dict.fromkeys(
                (
                    *topic_titles,
                    f"教师活动：{segment.teacher_activity}",
                    f"学生活动：{segment.student_activity}",
                )
            )
        )
        notes = [f"本页对应教案环节：{segment.title}。"]
        if experiment is not None:
            notes.extend(f"连续步骤：{step}" for step in experiment.integrated_steps)
            notes.extend(f"安全复核：{note}" for note in experiment.safety_notes)
        layout = _layout_for_segment(index, len(lesson.lesson_segments), experiment is not None)
        visual = (
            "使用不复制教材原图的装置流程图，按连续实验步骤逐项呈现。"
            if experiment is not None
            else "使用证据—观察—结论关系图；教材原图仅在授权允许时受控预览。"
        )
        slides.append(
            StoryboardSlide(
                slide_id=f"slide-{index + 1:02d}-{segment.segment_id}",
                title=segment.title,
                purpose=f"在{segment.minutes}分钟内完成本环节，并保留教师现场判断空间。",
                bullets=bullets,
                evidence_ids=segment.evidence_ids,
                session_id=segment.session_id or "single-session",
                topic_ids=segment.topic_ids or (f"segment:{segment.segment_id}",),
                speaker_notes=tuple(notes),
                estimated_minutes=segment.minutes,
                layout=layout,
                visual_suggestion=visual,
            )
        )
    content = SlideStoryboardContent(
        title=f"{lesson.title}｜课堂幻灯片故事板",
        source_lesson_plan_id=lesson_plan_id,
        source_lesson_revision=lesson_revision,
        source_lesson_content_sha256=lesson_content_sha256,
        template_id=template_id,
        template_version=DEFAULT_STORYBOARD_TEMPLATE_VERSION,
        slides=tuple(slides),
    )
    validate_storyboard_against_lesson(content, lesson)
    return content


def validate_storyboard_against_lesson(
    storyboard: SlideStoryboardContent,
    lesson: LessonPlanContent,
) -> None:
    allowed_evidence = set(lesson.evidence_ids)
    allowed_sessions = {item.session_id for item in lesson.sessions} or {"single-session"}
    allowed_topics = {item.topic_id for item in lesson.topic_coverage}
    if not allowed_topics:
        allowed_topics = {f"segment:{item.segment_id}" for item in lesson.lesson_segments}
    if set(storyboard.evidence_ids) - allowed_evidence:
        raise ValueError("storyboard cannot introduce evidence outside the source lesson plan")
    if storyboard.estimated_minutes > lesson.available_minutes:
        raise ValueError("storyboard estimated minutes exceed the source lesson budget")
    for slide in storyboard.slides:
        if slide.session_id not in allowed_sessions:
            raise ValueError("storyboard slide references an unknown lesson session")
        if set(slide.topic_ids) - allowed_topics:
            raise ValueError("storyboard slide references an unknown lesson topic")
        if not set(slide.evidence_ids).intersection(allowed_evidence):
            raise ValueError("every storyboard slide requires source lesson evidence")


def _layout_for_segment(index: int, total: int, is_experiment: bool) -> SlideLayout:
    if is_experiment:
        return SlideLayout.EXPERIMENT
    if index == 0:
        return SlideLayout.OPENING
    if index == total - 1:
        return SlideLayout.SUMMARY
    return SlideLayout.CONCEPT if index % 2 else SlideLayout.EVIDENCE


def _text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _text_tuple(payload: dict[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(value)


def _positive_int(payload: dict[str, Any], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
