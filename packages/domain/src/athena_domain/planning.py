"""Lesson time-budget and session primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SegmentPriority(StrEnum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class LessonSessionKind(StrEnum):
    INSTRUCTION = "instruction"
    DEMONSTRATION = "demonstration"
    STUDENT_LAB = "student_lab"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class LessonSession:
    session_id: str
    title: str
    minutes: int
    kind: LessonSessionKind = LessonSessionKind.INSTRUCTION

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("lesson session identifier must not be blank")
        if not self.title.strip():
            raise ValueError("lesson session title must not be blank")
        if self.minutes <= 0:
            raise ValueError("lesson session minutes must be positive")


@dataclass(frozen=True, slots=True)
class LessonSegment:
    title: str
    minutes: int
    priority: SegmentPriority
    evidence_ids: tuple[str, ...]
    segment_id: str = ""
    teacher_activity: str = ""
    student_activity: str = ""
    locked: bool = False
    session_id: str = ""
    topic_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("segment title must not be blank")
        if self.minutes <= 0:
            raise ValueError("segment minutes must be positive")
        if not self.evidence_ids:
            raise ValueError("each lesson segment must have textbook evidence")
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("lesson segment evidence identifiers must not be blank")
        if self.segment_id and not self.segment_id.strip():
            raise ValueError("segment_id must be absent or non-blank")
        if self.teacher_activity and not self.teacher_activity.strip():
            raise ValueError("teacher_activity must be absent or non-blank")
        if self.student_activity and not self.student_activity.strip():
            raise ValueError("student_activity must be absent or non-blank")
        if self.session_id and not self.session_id.strip():
            raise ValueError("session_id must be absent or non-blank")
        if any(not item.strip() for item in self.topic_ids):
            raise ValueError("topic identifiers must not be blank")
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("lesson segment topic identifiers must be unique")


@dataclass(frozen=True, slots=True)
class LessonBudget:
    available_minutes: int
    segments: tuple[LessonSegment, ...]

    def __post_init__(self) -> None:
        if self.available_minutes <= 0:
            raise ValueError("available_minutes must be positive")

    @property
    def planned_minutes(self) -> int:
        return sum(segment.minutes for segment in self.segments)

    @property
    def over_by_minutes(self) -> int:
        return max(0, self.planned_minutes - self.available_minutes)

    @property
    def is_over_budget(self) -> bool:
        return self.over_by_minutes > 0

    def optional_segments(self) -> tuple[LessonSegment, ...]:
        return tuple(
            segment for segment in self.segments if segment.priority is SegmentPriority.OPTIONAL
        )
