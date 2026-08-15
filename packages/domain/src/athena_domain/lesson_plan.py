"""Public lesson-plan contract; implementation is split across v2 modules."""

from .lesson_plan_builder_v2 import build_deterministic_lesson_plan
from .lesson_plan_v2 import (
    LEGACY_LESSON_PLAN_SCHEMA_VERSION,
    LESSON_PLAN_SCHEMA_VERSION,
    ExperimentMode,
    LessonExperiment,
    LessonPlanContent,
    LessonPlanRevisionSource,
    LessonPlanStatus,
    TopicCoverageStatus,
    TopicEvidenceCoverage,
)

__all__ = [
    "LEGACY_LESSON_PLAN_SCHEMA_VERSION",
    "LESSON_PLAN_SCHEMA_VERSION",
    "ExperimentMode",
    "LessonExperiment",
    "LessonPlanContent",
    "LessonPlanRevisionSource",
    "LessonPlanStatus",
    "TopicCoverageStatus",
    "TopicEvidenceCoverage",
    "build_deterministic_lesson_plan",
]
