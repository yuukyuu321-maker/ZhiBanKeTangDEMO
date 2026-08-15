import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app.assignment_service import AssignmentCatalog  # noqa: E402
from athena_domain import TeachingScope  # noqa: E402


class AssignmentCatalogTests(unittest.TestCase):
    def test_checked_in_example_resolves_and_serializes_version_reference(self) -> None:
        catalog = AssignmentCatalog.from_file(
            ROOT / "deploy" / "examples" / "textbook-assignment-catalog.example.json"
        )
        resolved = catalog.resolve(
            "teacher-demo",
            TeachingScope(
                school_id="school-demo",
                academic_year="2026-2027",
                grade="八年级",
                subject="科学",
                class_id="class-2",
            ),
            on_date=date(2026, 10, 1),
        )
        payload = catalog.serialize(resolved)
        self.assertEqual(
            payload["textbook"]["edition_id"], "synthetic-science-grade8-volume2"
        )
        self.assertTrue(payload["workspace_pin_required"])

    def test_unknown_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema version"):
            AssignmentCatalog.from_payload(
                {
                    "schema_version": "unknown",
                    "editions": [],
                    "assignments": [],
                    "authorizations": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
