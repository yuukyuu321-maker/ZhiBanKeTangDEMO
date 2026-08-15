"""Explicit task allow-list for the first MVP."""

from enum import StrEnum


class GenerationTask(StrEnum):
    TEXTBOOK_SEARCH = "textbook_search"
    LESSON_PLAN = "lesson_plan"
    SLIDE_STORYBOARD = "slide_storyboard"
    PEDAGOGICAL_STEPS = "pedagogical_steps"


class UnsupportedTaskError(ValueError):
    """Raised when a request is outside the approved educational task set."""


def require_supported_task(task: str) -> GenerationTask:
    try:
        return GenerationTask(task)
    except ValueError as exc:
        raise UnsupportedTaskError("OUT_OF_EDUCATIONAL_SCOPE") from exc
