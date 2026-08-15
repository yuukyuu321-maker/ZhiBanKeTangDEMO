"""Structured multi-session lesson plans with evidence and experiment gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .planning import (
    LessonBudget,
    LessonSegment,
    LessonSession,
    LessonSessionKind,
)

LEGACY_LESSON_PLAN_SCHEMA_VERSION = "athena.lesson-plan.v1"
LESSON_PLAN_SCHEMA_VERSION = "athena.lesson-plan.v2"


class LessonPlanStatus(StrEnum):
    DRAFT = "draft"
    TEACHER_CONFIRMED = "teacher_confirmed"


class LessonPlanRevisionSource(StrEnum):
    GENERATED = "generated"
    TEACHER_EDIT = "teacher_edit"
    RESTORED = "restored"


class TopicCoverageStatus(StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"


class ExperimentMode(StrEnum):
    DEMONSTRATION = "demonstration"
    STUDENT_LAB = "student_lab"
    DEMONSTRATION_AND_STUDENT = "demonstration_and_student"


@dataclass(frozen=True, slots=True)
class TopicEvidenceCoverage:
    topic_id: str
    title: str
    status: TopicCoverageStatus
    evidence_ids: tuple[str, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.topic_id.strip():
            raise ValueError("topic identifier must not be blank")
        if not self.title.strip():
            raise ValueError("topic title must not be blank")
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("topic evidence identifiers must not be blank")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("topic evidence identifiers must be unique")
        if self.status is TopicCoverageStatus.COVERED and not self.evidence_ids:
            raise ValueError("covered topic requires at least one evidence anchor")
        if self.status is TopicCoverageStatus.MISSING and self.evidence_ids:
            raise ValueError("missing topic must not claim evidence anchors")
        if self.notes and not self.notes.strip():
            raise ValueError("topic notes must be absent or non-blank")


@dataclass(frozen=True, slots=True)
class LessonExperiment:
    experiment_id: str
    title: str
    session_id: str
    minutes: int
    mode: ExperimentMode
    topic_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    integrated_steps: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    teacher_safety_confirmed: bool = False

    def __post_init__(self) -> None:
        if not self.experiment_id.strip():
            raise ValueError("experiment identifier must not be blank")
        if not self.title.strip():
            raise ValueError("experiment title must not be blank")
        if not self.session_id.strip():
            raise ValueError("experiment session identifier must not be blank")
        if self.minutes <= 0:
            raise ValueError("experiment minutes must be positive")
        if not self.topic_ids or any(not item.strip() for item in self.topic_ids):
            raise ValueError("experiment topic identifiers must not be blank")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("experiment requires non-blank textbook evidence")
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("experiment topic identifiers must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("experiment evidence identifiers must be unique")
        for name, values in (
            ("integrated_steps", self.integrated_steps),
            ("safety_notes", self.safety_notes),
        ):
            if any(not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-blank values")


@dataclass(frozen=True, slots=True)
class LessonPlanContent:
    title: str
    objectives: tuple[str, ...]
    required_topics: tuple[str, ...]
    available_minutes: int
    lesson_segments: tuple[LessonSegment, ...]
    board_plan: tuple[str, ...]
    checks_for_understanding: tuple[str, ...]
    materials: tuple[str, ...]
    omissions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    sessions: tuple[LessonSession, ...] = ()
    topic_coverage: tuple[TopicEvidenceCoverage, ...] = ()
    experiments: tuple[LessonExperiment, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("lesson plan title must not be blank")
        if not self.objectives or any(not item.strip() for item in self.objectives):
            raise ValueError("lesson plan objectives must contain non-blank values")
        if any(not item.strip() for item in self.required_topics):
            raise ValueError("required_topics must contain non-blank values")
        if not self.lesson_segments:
            raise ValueError("lesson plan must contain at least one segment")
        segment_ids = [item.segment_id for item in self.lesson_segments]
        if any(not item for item in segment_ids):
            raise ValueError("persisted lesson segments require segment_id")
        if len(set(segment_ids)) != len(segment_ids):
            raise ValueError("lesson segment identifiers must be unique")
        for name, values in (
            ("board_plan", self.board_plan),
            ("checks_for_understanding", self.checks_for_understanding),
            ("materials", self.materials),
            ("omissions", self.omissions),
            ("limitations", self.limitations),
        ):
            if any(not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-blank values")
        LessonBudget(self.available_minutes, self.lesson_segments)
        self._validate_sessions()
        self._validate_topic_coverage()
        self._validate_experiments()

    def _validate_sessions(self) -> None:
        if not self.sessions:
            if any(item.session_id for item in self.lesson_segments):
                raise ValueError("segments cannot reference sessions when none are defined")
            return
        session_ids = [item.session_id for item in self.sessions]
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("lesson session identifiers must be unique")
        if sum(item.minutes for item in self.sessions) != self.available_minutes:
            raise ValueError("lesson session minutes must equal available_minutes")
        known = set(session_ids)
        if any(item.session_id not in known for item in self.lesson_segments):
            raise ValueError("lesson segment references an unknown session")

    def _validate_topic_coverage(self) -> None:
        if not self.topic_coverage:
            if any(item.topic_ids for item in self.lesson_segments):
                raise ValueError("segments cannot reference topics without coverage records")
            return
        topic_ids = [item.topic_id for item in self.topic_coverage]
        if len(set(topic_ids)) != len(topic_ids):
            raise ValueError("topic coverage identifiers must be unique")
        if tuple(item.title for item in self.topic_coverage) != self.required_topics:
            raise ValueError("topic coverage must preserve required topic order and titles")
        known = set(topic_ids)
        if any(
            topic_id not in known for item in self.lesson_segments for topic_id in item.topic_ids
        ):
            raise ValueError("lesson segment references an unknown topic")
        coverage_by_id = {item.topic_id: item for item in self.topic_coverage}
        for segment in self.lesson_segments:
            for topic_id in segment.topic_ids:
                if not set(segment.evidence_ids).intersection(
                    coverage_by_id[topic_id].evidence_ids
                ):
                    raise ValueError("lesson segment topic must share a topic evidence anchor")

    def _validate_experiments(self) -> None:
        if not self.experiments:
            return
        experiment_ids = [item.experiment_id for item in self.experiments]
        if len(set(experiment_ids)) != len(experiment_ids):
            raise ValueError("experiment identifiers must be unique")
        segments = {item.segment_id: item for item in self.lesson_segments}
        session_kinds = {item.session_id: item.kind for item in self.sessions}
        topics = {item.topic_id: item for item in self.topic_coverage}
        for experiment in self.experiments:
            segment = segments.get(experiment.experiment_id)
            if segment is None:
                raise ValueError("experiment must reference a matching lesson segment")
            if experiment.session_id not in session_kinds:
                raise ValueError("experiment references an unknown session")
            if set(experiment.topic_ids) - topics.keys():
                raise ValueError("experiment references an unknown topic")
            if experiment.mode is ExperimentMode.STUDENT_LAB and session_kinds[
                experiment.session_id
            ] not in {LessonSessionKind.STUDENT_LAB, LessonSessionKind.MIXED}:
                raise ValueError("student experiment requires a student-lab or mixed session")
            if experiment.mode is ExperimentMode.DEMONSTRATION_AND_STUDENT and session_kinds[
                experiment.session_id
            ] not in {LessonSessionKind.STUDENT_LAB, LessonSessionKind.MIXED}:
                raise ValueError("combined experiment requires a student-lab or mixed session")
            for topic_id in experiment.topic_ids:
                if not set(experiment.evidence_ids).intersection(topics[topic_id].evidence_ids):
                    raise ValueError("experiment topic must share a topic evidence anchor")
            if experiment.minutes != segment.minutes or experiment.session_id != segment.session_id:
                raise ValueError("experiment timing must match its lesson segment")
            if not set(experiment.evidence_ids).issubset(segment.evidence_ids):
                raise ValueError("experiment evidence must be present on its lesson segment")

    @property
    def budget(self) -> LessonBudget:
        return LessonBudget(self.available_minutes, self.lesson_segments)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                evidence_id
                for collection in (
                    (item.evidence_ids for item in self.lesson_segments),
                    (item.evidence_ids for item in self.topic_coverage),
                    (item.evidence_ids for item in self.experiments),
                )
                for evidence_ids in collection
                for evidence_id in evidence_ids
            )
        )

    @property
    def session_budget_summaries(self) -> tuple[dict[str, Any], ...]:
        summaries: list[dict[str, Any]] = []
        for session in self.sessions:
            planned = sum(
                item.minutes
                for item in self.lesson_segments
                if item.session_id == session.session_id
            )
            over_by = max(0, planned - session.minutes)
            summaries.append(
                {
                    "session_id": session.session_id,
                    "planned_minutes": planned,
                    "available_minutes": session.minutes,
                    "over_by_minutes": over_by,
                    "status": "over_budget" if over_by else "within_budget",
                }
            )
        return tuple(summaries)

    @property
    def confirmation_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.budget.is_over_budget:
            blockers.append("total_budget_overrun")
        blockers.extend(
            f"session_overrun:{item['session_id']}"
            for item in self.session_budget_summaries
            if item["over_by_minutes"]
        )
        if self.topic_coverage:
            scheduled = {
                topic_id for segment in self.lesson_segments for topic_id in segment.topic_ids
            }
            blockers.extend(
                f"topic_evidence:{item.topic_id}:{item.status}"
                for item in self.topic_coverage
                if item.status is not TopicCoverageStatus.COVERED
            )
            blockers.extend(
                f"topic_unscheduled:{item.topic_id}"
                for item in self.topic_coverage
                if item.topic_id not in scheduled
            )
        blockers.extend(
            f"experiment_safety_review:{item.experiment_id}"
            for item in self.experiments
            if not item.teacher_safety_confirmed
        )
        if self.sessions:
            experiment_sessions = {item.session_id for item in self.experiments}
            blockers.extend(
                f"student_lab_without_experiment:{item.session_id}"
                for item in self.sessions
                if item.kind is LessonSessionKind.STUDENT_LAB
                and item.session_id not in experiment_sessions
            )
        return tuple(dict.fromkeys(blockers))

    @property
    def confirmation_ready(self) -> bool:
        return not self.confirmation_blockers

    def to_payload(self) -> dict[str, Any]:
        budget = self.budget
        return {
            "schema_version": LESSON_PLAN_SCHEMA_VERSION,
            "title": self.title,
            "objectives": list(self.objectives),
            "required_topics": list(self.required_topics),
            "available_minutes": self.available_minutes,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "title": item.title,
                    "minutes": item.minutes,
                    "kind": str(item.kind),
                }
                for item in self.sessions
            ],
            "topic_coverage": [
                {
                    "topic_id": item.topic_id,
                    "title": item.title,
                    "status": str(item.status),
                    "evidence_ids": list(item.evidence_ids),
                    "notes": item.notes,
                }
                for item in self.topic_coverage
            ],
            "experiments": [
                {
                    "experiment_id": item.experiment_id,
                    "title": item.title,
                    "session_id": item.session_id,
                    "minutes": item.minutes,
                    "mode": str(item.mode),
                    "topic_ids": list(item.topic_ids),
                    "evidence_ids": list(item.evidence_ids),
                    "integrated_steps": list(item.integrated_steps),
                    "safety_notes": list(item.safety_notes),
                    "teacher_safety_confirmed": item.teacher_safety_confirmed,
                }
                for item in self.experiments
            ],
            "lesson_segments": [
                {
                    "segment_id": item.segment_id,
                    "title": item.title,
                    "minutes": item.minutes,
                    "priority": str(item.priority),
                    "teacher_activity": item.teacher_activity,
                    "student_activity": item.student_activity,
                    "evidence_ids": list(item.evidence_ids),
                    "locked": item.locked,
                    "session_id": item.session_id,
                    "topic_ids": list(item.topic_ids),
                }
                for item in self.lesson_segments
            ],
            "board_plan": list(self.board_plan),
            "checks_for_understanding": list(self.checks_for_understanding),
            "materials": list(self.materials),
            "omissions": list(self.omissions),
            "limitations": list(self.limitations),
            "budget": {
                "planned_minutes": budget.planned_minutes,
                "available_minutes": budget.available_minutes,
                "over_by_minutes": budget.over_by_minutes,
                "status": "over_budget" if budget.is_over_budget else "within_budget",
            },
            "session_budgets": list(self.session_budget_summaries),
            "confirmation_ready": self.confirmation_ready,
            "confirmation_blockers": list(self.confirmation_blockers),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> LessonPlanContent:
        from .lesson_plan_parsing_v2 import (
            coverage_from_payload,
            experiment_from_payload,
            positive_int,
            segment_from_payload,
            session_from_payload,
            text,
            text_tuple,
        )

        allowed = {
            "schema_version",
            "title",
            "objectives",
            "required_topics",
            "available_minutes",
            "sessions",
            "topic_coverage",
            "experiments",
            "lesson_segments",
            "board_plan",
            "checks_for_understanding",
            "materials",
            "omissions",
            "limitations",
            "budget",
            "session_budgets",
            "confirmation_ready",
            "confirmation_blockers",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unsupported lesson plan fields: {', '.join(sorted(unknown))}")
        schema = payload.get("schema_version")
        if schema not in {
            LEGACY_LESSON_PLAN_SCHEMA_VERSION,
            LESSON_PLAN_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported lesson plan schema version")
        segments_value = payload.get("lesson_segments")
        sessions_value = payload.get("sessions", [])
        coverage_value = payload.get("topic_coverage", [])
        experiments_value = payload.get("experiments", [])
        if not isinstance(segments_value, list):
            raise ValueError("lesson_segments must be a list")
        if not all(
            isinstance(value, list) for value in (sessions_value, coverage_value, experiments_value)
        ):
            raise ValueError("sessions, topic_coverage and experiments must be lists")
        content = cls(
            title=text(payload, "title"),
            objectives=text_tuple(payload, "objectives"),
            required_topics=text_tuple(payload, "required_topics"),
            available_minutes=positive_int(payload, "available_minutes"),
            lesson_segments=tuple(segment_from_payload(item) for item in segments_value),
            board_plan=text_tuple(payload, "board_plan"),
            checks_for_understanding=text_tuple(payload, "checks_for_understanding"),
            materials=text_tuple(payload, "materials"),
            omissions=text_tuple(payload, "omissions"),
            limitations=text_tuple(payload, "limitations"),
            sessions=tuple(session_from_payload(item) for item in sessions_value),
            topic_coverage=tuple(coverage_from_payload(item) for item in coverage_value),
            experiments=tuple(experiment_from_payload(item) for item in experiments_value),
        )
        canonical = content.to_payload()
        supplied_budget = payload.get("budget")
        if supplied_budget is not None and supplied_budget != canonical["budget"]:
            raise ValueError("lesson plan budget summary does not match segment minutes")
        if schema == LESSON_PLAN_SCHEMA_VERSION:
            for field in (
                "session_budgets",
                "confirmation_ready",
                "confirmation_blockers",
            ):
                supplied = payload.get(field)
                if supplied is not None and supplied != canonical[field]:
                    raise ValueError(f"lesson plan {field} does not match content")
        return content
