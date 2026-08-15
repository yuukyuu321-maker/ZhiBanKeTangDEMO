"""Strict payload parsing for the v2 lesson-plan contract."""

from __future__ import annotations

from typing import Any

from .lesson_plan_v2 import (
    ExperimentMode,
    LessonExperiment,
    TopicCoverageStatus,
    TopicEvidenceCoverage,
)
from .planning import LessonSegment, LessonSession, LessonSessionKind, SegmentPriority


def segment_from_payload(value: object) -> LessonSegment:
    if not isinstance(value, dict):
        raise ValueError("lesson segment must be an object")
    allowed = {
        "segment_id",
        "title",
        "minutes",
        "priority",
        "teacher_activity",
        "student_activity",
        "evidence_ids",
        "locked",
        "session_id",
        "topic_ids",
    }
    _reject_unknown(value, allowed, "lesson segment")
    locked = value.get("locked", False)
    if not isinstance(locked, bool):
        raise ValueError("lesson segment locked must be a boolean")
    try:
        priority = SegmentPriority(str(value["priority"]))
    except (KeyError, ValueError) as error:
        raise ValueError("unsupported lesson segment priority") from error
    return LessonSegment(
        title=text(value, "title"),
        minutes=positive_int(value, "minutes"),
        priority=priority,
        evidence_ids=string_list(value, "evidence_ids"),
        segment_id=text(value, "segment_id"),
        teacher_activity=text(value, "teacher_activity"),
        student_activity=text(value, "student_activity"),
        locked=locked,
        session_id=optional_text(value, "session_id"),
        topic_ids=string_list(value, "topic_ids"),
    )


def session_from_payload(value: object) -> LessonSession:
    if not isinstance(value, dict):
        raise ValueError("lesson session must be an object")
    _reject_unknown(value, {"session_id", "title", "minutes", "kind"}, "lesson session")
    try:
        kind = LessonSessionKind(str(value["kind"]))
    except (KeyError, ValueError) as error:
        raise ValueError("unsupported lesson session kind") from error
    return LessonSession(
        session_id=text(value, "session_id"),
        title=text(value, "title"),
        minutes=positive_int(value, "minutes"),
        kind=kind,
    )


def coverage_from_payload(value: object) -> TopicEvidenceCoverage:
    if not isinstance(value, dict):
        raise ValueError("topic coverage must be an object")
    _reject_unknown(
        value,
        {"topic_id", "title", "status", "evidence_ids", "notes"},
        "topic coverage",
    )
    try:
        status = TopicCoverageStatus(str(value["status"]))
    except (KeyError, ValueError) as error:
        raise ValueError("unsupported topic coverage status") from error
    return TopicEvidenceCoverage(
        topic_id=text(value, "topic_id"),
        title=text(value, "title"),
        status=status,
        evidence_ids=string_list(value, "evidence_ids"),
        notes=optional_text(value, "notes"),
    )


def experiment_from_payload(value: object) -> LessonExperiment:
    if not isinstance(value, dict):
        raise ValueError("lesson experiment must be an object")
    _reject_unknown(
        value,
        {
            "experiment_id",
            "title",
            "session_id",
            "minutes",
            "mode",
            "topic_ids",
            "evidence_ids",
            "integrated_steps",
            "safety_notes",
            "teacher_safety_confirmed",
        },
        "lesson experiment",
    )
    try:
        mode = ExperimentMode(str(value["mode"]))
    except (KeyError, ValueError) as error:
        raise ValueError("unsupported experiment mode") from error
    safety_confirmed = value.get("teacher_safety_confirmed", False)
    if not isinstance(safety_confirmed, bool):
        raise ValueError("teacher_safety_confirmed must be a boolean")
    return LessonExperiment(
        experiment_id=text(value, "experiment_id"),
        title=text(value, "title"),
        session_id=text(value, "session_id"),
        minutes=positive_int(value, "minutes"),
        mode=mode,
        topic_ids=string_list(value, "topic_ids"),
        evidence_ids=string_list(value, "evidence_ids"),
        integrated_steps=string_list(value, "integrated_steps"),
        safety_notes=string_list(value, "safety_notes"),
        teacher_safety_confirmed=safety_confirmed,
    )


def _reject_unknown(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported {label} fields: {', '.join(sorted(unknown))}")


def text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-blank string")
    return value.strip()


def optional_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def positive_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def text_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in string_list(payload, key))


def string_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    if any(not item.strip() for item in value):
        raise ValueError(f"{key} must contain non-blank strings")
    return tuple(item.strip() for item in value)
