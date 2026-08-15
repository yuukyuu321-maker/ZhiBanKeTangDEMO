import os
import sys
import tempfile
import unittest
from decimal import Decimal
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
from athena_ingestion.postgres_registration import (  # noqa: E402
    RegistrationConflictError,
    _numeric_signature,
    register_promoted_bundle,
)
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
class PostgresRegistrationIntegrationTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self._reset_database()
        self.temp.cleanup()

    def test_registers_approved_content_without_activation_or_assignment(self) -> None:
        assert DATABASE_URL is not None
        result = register_promoted_bundle(
            self.bundle,
            self.import_root,
            DATABASE_URL,
            "school-registration",
            "registry-owner",
        )
        rerun = register_promoted_bundle(
            self.bundle,
            self.import_root,
            DATABASE_URL,
            "school-registration",
            "another-operator",
        )

        self.assertFalse(result.reused)
        self.assertTrue(rerun.reused)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.evidence_count, 1)
        with self.connection.transaction():
            self.connection.execute(
                "SELECT set_config('athena.school_id', 'school-registration', true)"
            )
            edition = self.connection.execute(
                "SELECT lifecycle_status FROM textbook_editions"
            ).fetchone()
            source = self.connection.execute(
                """
                SELECT
                    import_status,
                    bundle_content_sha256,
                    import_pipeline_version,
                    review_id,
                    registered_by
                FROM textbook_sources
                """
            ).fetchone()
            counts = {
                table: self.connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"]
                for table in RLS_TABLES
            }

        self.assertEqual(edition["lifecycle_status"], "approved")
        self.assertEqual(source["import_status"], "approved")
        self.assertEqual(source["import_pipeline_version"], "2.0-test")
        self.assertEqual(source["registered_by"], "registry-owner")
        self.assertEqual(len(source["bundle_content_sha256"]), 64)
        self.assertTrue(source["review_id"].startswith("review_"))
        self.assertEqual(
            counts,
            {
                "textbook_editions": 1,
                "textbook_sources": 1,
                "textbook_pages": 2,
                "textbook_evidence": 1,
                "teaching_groups": 0,
                "principal_teaching_scopes": 0,
                "textbook_assignments": 0,
                "workspace_textbook_pins": 0,
            },
        )

    def test_coordinate_signature_ignores_only_float_tail_noise(self) -> None:
        self.assertEqual(
            _numeric_signature(429.14179999999993),
            _numeric_signature(Decimal("429.1418")),
        )
        self.assertNotEqual(
            _numeric_signature(429.14179999),
            _numeric_signature(Decimal("429.1418")),
        )

    def test_exact_rerun_rejects_same_count_page_content_drift(self) -> None:
        assert DATABASE_URL is not None
        register_promoted_bundle(
            self.bundle,
            self.import_root,
            DATABASE_URL,
            "school-registration",
            "registry-owner",
        )
        with self.connection.transaction():
            self.connection.execute(
                "SELECT set_config('athena.school_id', 'school-registration', true)"
            )
            self.connection.execute(
                """
                UPDATE textbook_pages
                SET page_label = 'drifted'
                WHERE edition_id = 'edition-test'
                  AND pdf_page_index = 1
                """
            )

        with self.assertRaisesRegex(RegistrationConflictError, "page records differ"):
            register_promoted_bundle(
                self.bundle,
                self.import_root,
                DATABASE_URL,
                "school-registration",
                "registry-owner",
            )

    def test_refuses_candidate_outside_canonical_import_root(self) -> None:
        assert DATABASE_URL is not None
        candidate = build_approved_candidate(self.root / "other")

        with self.assertRaisesRegex(ValueError, "canonical bundle"):
            register_promoted_bundle(
                candidate,
                self.import_root,
                DATABASE_URL,
                "school-registration",
                "registry-owner",
            )


if __name__ == "__main__":
    unittest.main()
