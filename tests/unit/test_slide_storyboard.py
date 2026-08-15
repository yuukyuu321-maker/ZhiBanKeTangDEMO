import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))

from athena_domain import (  # noqa: E402
    DEFAULT_STORYBOARD_TEMPLATE_ID,
    SlideStoryboardContent,
    build_deterministic_lesson_plan,
    build_deterministic_storyboard,
    validate_storyboard_against_lesson,
)


class SlideStoryboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lesson = build_deterministic_lesson_plan(
            title="空气的组成",
            objectives=("基于教材证据说明空气的组成",),
            required_topics=("空气的组成",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("evidence-1",),
            preserve_experiment=True,
        )

    def test_builds_deterministic_evidence_bound_storyboard(self) -> None:
        storyboard = build_deterministic_storyboard(
            lesson_plan_id="lesson-plan-1",
            lesson_revision=3,
            lesson_content_sha256="a" * 64,
            lesson=self.lesson,
        )

        self.assertEqual(storyboard.template_id, DEFAULT_STORYBOARD_TEMPLATE_ID)
        self.assertEqual(storyboard.source_lesson_revision, 3)
        self.assertEqual(storyboard.estimated_minutes, self.lesson.budget.planned_minutes)
        self.assertEqual(storyboard.evidence_ids, ("evidence-1",))
        self.assertTrue(all(slide.evidence_ids for slide in storyboard.slides))
        self.assertEqual(
            SlideStoryboardContent.from_payload(storyboard.to_payload()),
            storyboard,
        )

    def test_rejects_new_evidence_and_forged_summary(self) -> None:
        storyboard = build_deterministic_storyboard(
            lesson_plan_id="lesson-plan-1",
            lesson_revision=1,
            lesson_content_sha256="b" * 64,
            lesson=self.lesson,
        )
        first = replace(storyboard.slides[0], evidence_ids=("outside-evidence",))
        changed = replace(storyboard, slides=(first, *storyboard.slides[1:]))
        with self.assertRaisesRegex(ValueError, "outside the source lesson plan"):
            validate_storyboard_against_lesson(changed, self.lesson)

        payload = storyboard.to_payload()
        payload["summary"]["slide_count"] = 999
        with self.assertRaisesRegex(ValueError, "summary does not match"):
            SlideStoryboardContent.from_payload(payload)

    def test_rejects_unknown_template(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported storyboard template"):
            build_deterministic_storyboard(
                lesson_plan_id="lesson-plan-1",
                lesson_revision=1,
                lesson_content_sha256="c" * 64,
                lesson=self.lesson,
                template_id="invented-template",
            )


if __name__ == "__main__":
    unittest.main()
