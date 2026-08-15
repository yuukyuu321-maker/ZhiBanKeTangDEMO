from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))

from athena_domain import GenerationTask, UnsupportedTaskError, require_supported_task  # noqa: E402


class ScopeGuardTests(unittest.TestCase):
    def test_allows_approved_teaching_task(self) -> None:
        self.assertEqual(require_supported_task("lesson_plan"), GenerationTask.LESSON_PLAN)

    def test_rejects_unapproved_surveillance_or_entertainment_tasks(self) -> None:
        for task in ("face_recognition", "emotion_recognition", "discipline_decision", "roleplay"):
            with self.subTest(task=task), self.assertRaises(UnsupportedTaskError):
                require_supported_task(task)


if __name__ == "__main__":
    unittest.main()
