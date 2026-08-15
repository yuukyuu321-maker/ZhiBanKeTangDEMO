import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))

from athena_domain import (  # noqa: E402
    AssignmentConflictError,
    AssignmentNotFoundError,
    AssignmentResolver,
    EditionRegistration,
    TeachingAuthorization,
    TeachingScope,
    TeachingScopeUnauthorizedError,
    TextbookAssignment,
    TextbookEditionInactiveError,
    TextbookEditionStatus,
    pin_workspace,
)

DIGEST_OLD = "a" * 64
DIGEST_NEW = "b" * 64
GRADE_SCOPE = TeachingScope("school-1", "2026-2027", "八年级", "科学")
CLASS_SCOPE = TeachingScope(
    "school-1", "2026-2027", "八年级", "科学", class_id="class-2"
)


def assignment(
    assignment_id: str,
    edition_id: str,
    digest: str,
    scope: TeachingScope = GRADE_SCOPE,
    *,
    valid_from: date = date(2026, 9, 1),
    valid_until: date | None = None,
) -> TextbookAssignment:
    return TextbookAssignment(
        assignment_id=assignment_id,
        scope=scope,
        edition_id=edition_id,
        source_sha256=digest,
        valid_from=valid_from,
        valid_until=valid_until,
        assigned_by="admin-1",
    )


def resolver(
    assignments: tuple[TextbookAssignment, ...],
    *,
    new_status: TextbookEditionStatus = TextbookEditionStatus.ACTIVE,
) -> AssignmentResolver:
    return AssignmentResolver(
        registrations=(
            EditionRegistration("science-old", DIGEST_OLD, TextbookEditionStatus.ACTIVE),
            EditionRegistration("science-new", DIGEST_NEW, new_status),
        ),
        assignments=assignments,
        authorizations=(TeachingAuthorization("teacher-1", GRADE_SCOPE),),
    )


class AssignmentResolverTests(unittest.TestCase):
    def test_class_assignment_wins_over_grade_assignment(self) -> None:
        result = resolver(
            (
                assignment("grade-old", "science-old", DIGEST_OLD),
                assignment("class-new", "science-new", DIGEST_NEW, CLASS_SCOPE),
            )
        ).resolve("teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1))
        self.assertEqual(result.assignment.assignment_id, "class-new")

    def test_grade_assignment_is_used_when_class_override_is_absent(self) -> None:
        result = resolver((assignment("grade-old", "science-old", DIGEST_OLD),)).resolve(
            "teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1)
        )
        self.assertEqual(result.assignment.assignment_id, "grade-old")

    def test_equal_priority_overlap_is_an_explicit_conflict(self) -> None:
        with self.assertRaisesRegex(AssignmentConflictError, "grade-new, grade-old"):
            resolver(
                (
                    assignment("grade-old", "science-old", DIGEST_OLD),
                    assignment("grade-new", "science-new", DIGEST_NEW),
                )
            ).resolve("teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1))

    def test_inactive_or_merely_approved_edition_cannot_start_new_workspace(self) -> None:
        with self.assertRaises(TextbookEditionInactiveError):
            resolver(
                (assignment("grade-new", "science-new", DIGEST_NEW),),
                new_status=TextbookEditionStatus.APPROVED,
            ).resolve("teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1))

    def test_out_of_scope_principal_is_rejected_before_resolution(self) -> None:
        with self.assertRaises(TeachingScopeUnauthorizedError):
            resolver((assignment("grade-old", "science-old", DIGEST_OLD),)).resolve(
                "teacher-2", CLASS_SCOPE, on_date=date(2026, 10, 1)
            )

    def test_assignment_date_range_is_inclusive(self) -> None:
        limited = assignment(
            "fall-old",
            "science-old",
            DIGEST_OLD,
            valid_until=date(2026, 12, 31),
        )
        result = resolver((limited,)).resolve(
            "teacher-1", CLASS_SCOPE, on_date=date(2026, 12, 31)
        )
        self.assertEqual(result.assignment.assignment_id, "fall-old")
        with self.assertRaises(AssignmentNotFoundError):
            resolver((limited,)).resolve(
                "teacher-1", CLASS_SCOPE, on_date=date(2027, 1, 1)
            )

    def test_workspace_pin_does_not_drift_when_assignment_changes(self) -> None:
        initial = resolver((assignment("grade-old", "science-old", DIGEST_OLD),)).resolve(
            "teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1)
        )
        pin = pin_workspace("workspace-1", initial)
        current = resolver((assignment("grade-new", "science-new", DIGEST_NEW),)).resolve(
            "teacher-1", CLASS_SCOPE, on_date=date(2026, 10, 1)
        )
        self.assertEqual(pin.edition_id, "science-old")
        self.assertEqual(current.registration.edition_id, "science-new")


if __name__ == "__main__":
    unittest.main()
