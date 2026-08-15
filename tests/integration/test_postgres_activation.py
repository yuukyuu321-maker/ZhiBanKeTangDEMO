import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "textbook-ingestion" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app.migrations import apply_migrations  # noqa: E402
from app.postgres_assignment_service import PostgresAssignmentCatalog  # noqa: E402
from athena_domain import TeachingScope  # noqa: E402
from athena_ingestion.postgres_activation import (  # noqa: E402
    ActivationConflictError,
    ActivationValidationError,
    activate_and_assign_bundle,
    grant_principal_teaching_scope,
)
from athena_ingestion.postgres_registration import register_promoted_bundle  # noqa: E402
from athena_ingestion.promotion import promote_bundle  # noqa: E402

from tests.textbook_bundle_fixture import build_approved_candidate  # noqa: E402

DATABASE_URL = os.getenv("ATHENA_TEST_DATABASE_URL")
RLS_TABLES = (
    "textbook_editions",
    "textbook_sources",
    "textbook_pages",
    "textbook_evidence",
    "teaching_groups",
    "principal_teaching_scopes",
    "textbook_assignments",
    "workspace_textbook_pins",
)


@unittest.skipUnless(DATABASE_URL, "ATHENA_TEST_DATABASE_URL is not configured")
class PostgresActivationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        parameters = psycopg.conninfo.conninfo_to_dict(DATABASE_URL)
        if not parameters.get("dbname", "").endswith("_test"):
            raise RuntimeError("integration database name must end with _test")
        apply_migrations(DATABASE_URL, ROOT / "deploy" / "postgres" / "migrations")
        cls.connection = psycopg.connect(
            DATABASE_URL,
            autocommit=True,
            row_factory=dict_row,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "connection"):
            cls._reset_database()
            cls.connection.close()

    @classmethod
    def _reset_database(cls) -> None:
        tables = sql.SQL(", ").join(sql.Identifier(name) for name in reversed(RLS_TABLES))
        cls.connection.execute(sql.SQL("TRUNCATE {} CASCADE").format(tables))

    def setUp(self) -> None:
        assert DATABASE_URL is not None
        self._reset_database()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        candidate = build_approved_candidate(self.root)
        self.import_root = self.root / "imports"
        self.bundle = promote_bundle(
            candidate,
            self.import_root,
            "release-owner",
        ).destination
        register_promoted_bundle(
            self.bundle,
            self.import_root,
            DATABASE_URL,
            "school-activation",
            "registry-owner",
        )

    def tearDown(self) -> None:
        self._reset_database()
        self.temp.cleanup()

    def _activate(self, *, valid_from: date = date(2026, 9, 1)):
        assert DATABASE_URL is not None
        return activate_and_assign_bundle(
            self.bundle,
            self.import_root,
            DATABASE_URL,
            "school-activation",
            "2026-2027",
            "八年级",
            "科学",
            valid_from,
            "curriculum-admin",
            "测试阶段教材检索闭环",
        )

    def test_activation_assignment_grant_and_resolver_form_a_closed_loop(self) -> None:
        assert DATABASE_URL is not None
        activated = self._activate()
        activation_rerun = self._activate()
        granted = grant_principal_teaching_scope(
            DATABASE_URL,
            "school-activation",
            "2026-2027",
            "八年级",
            "科学",
            "teacher-pilot",
            "curriculum-admin",
        )
        grant_rerun = grant_principal_teaching_scope(
            DATABASE_URL,
            "school-activation",
            "2026-2027",
            "八年级",
            "科学",
            "teacher-pilot",
            "curriculum-admin",
        )
        resolved = PostgresAssignmentCatalog(DATABASE_URL).resolve(
            "teacher-pilot",
            TeachingScope("school-activation", "2026-2027", "八年级", "科学"),
            on_date=date(2026, 10, 1),
        )

        self.assertFalse(activated.reused)
        self.assertTrue(activation_rerun.reused)
        self.assertFalse(granted.reused)
        self.assertTrue(grant_rerun.reused)
        self.assertEqual(resolved.assignment.assignment_id, activated.assignment_id)
        self.assertEqual(resolved.registration.status, "active")
        with self.connection.transaction():
            self.connection.execute(
                "SELECT set_config('athena.school_id', 'school-activation', true)"
            )
            edition = self.connection.execute(
                """
                SELECT lifecycle_status, activated_by, activation_reason
                FROM textbook_editions
                """
            ).fetchone()
            source = self.connection.execute(
                """
                SELECT import_status, activated_by, activation_reason
                FROM textbook_sources
                """
            ).fetchone()
        self.assertEqual(edition["lifecycle_status"], "active")
        self.assertEqual(source["import_status"], "active")
        self.assertEqual(edition["activated_by"], "curriculum-admin")
        self.assertEqual(source["activation_reason"], "测试阶段教材检索闭环")

    def test_activation_rejects_same_count_registered_content_drift(self) -> None:
        with self.connection.transaction():
            self.connection.execute(
                "SELECT set_config('athena.school_id', 'school-activation', true)"
            )
            self.connection.execute(
                """
                UPDATE textbook_pages
                SET page_label = 'drifted'
                WHERE edition_id = 'edition-test'
                  AND pdf_page_index = 1
                """
            )

        with self.assertRaisesRegex(ActivationValidationError, "content differs"):
            self._activate()

    def test_equal_scope_date_overlap_is_rejected(self) -> None:
        self._activate()

        with self.assertRaisesRegex(ActivationConflictError, "overlapping assignment"):
            self._activate(valid_from=date(2026, 10, 1))

    def test_database_rejects_active_status_without_audit_metadata(self) -> None:
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.transaction():
                self.connection.execute(
                    "SELECT set_config('athena.school_id', 'school-activation', true)"
                )
                self.connection.execute("UPDATE textbook_editions SET lifecycle_status = 'active'")

    def test_other_school_cannot_activate_registered_textbook(self) -> None:
        assert DATABASE_URL is not None
        with self.assertRaisesRegex(ActivationValidationError, "not visible"):
            activate_and_assign_bundle(
                self.bundle,
                self.import_root,
                DATABASE_URL,
                "school-other",
                "2026-2027",
                "八年级",
                "科学",
                date(2026, 9, 1),
                "curriculum-admin",
                "wrong school",
            )

    def test_assignment_metadata_must_match_registered_edition(self) -> None:
        assert DATABASE_URL is not None
        with self.assertRaisesRegex(ActivationValidationError, "grade and subject"):
            activate_and_assign_bundle(
                self.bundle,
                self.import_root,
                DATABASE_URL,
                "school-activation",
                "2026-2027",
                "九年级",
                "科学",
                date(2026, 9, 1),
                "curriculum-admin",
                "invalid scope",
            )

    def test_grant_requires_an_existing_active_scope(self) -> None:
        assert DATABASE_URL is not None
        with self.assertRaisesRegex(ActivationValidationError, "active textbook"):
            grant_principal_teaching_scope(
                DATABASE_URL,
                "school-activation",
                "2026-2027",
                "八年级",
                "科学",
                "teacher-pilot",
                "curriculum-admin",
            )


if __name__ == "__main__":
    unittest.main()
