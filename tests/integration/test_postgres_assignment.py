import os
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app.lesson_plan_service import (  # noqa: E402
    LessonPlanConfirmationError,
    LessonPlanConflictError,
    LessonPlanGenerationInput,
)
from app.migrations import apply_migrations  # noqa: E402
from app.postgres_assignment_service import PostgresAssignmentCatalog  # noqa: E402
from app.postgres_lesson_plan_service import PostgresLessonPlanCatalog  # noqa: E402
from app.postgres_slide_storyboard_service import (  # noqa: E402
    PostgresSlideStoryboardCatalog,
)
from app.postgres_workspace_service import PostgresWorkspaceCatalog  # noqa: E402
from app.slide_storyboard_service import SlideStoryboardSourceChangedError  # noqa: E402
from app.workspace_service import (  # noqa: E402
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspaceUnauthorizedError,
)
from athena_domain import (  # noqa: E402
    LessonPlanContent,
    LessonPlanStatus,
    SlideStoryboardContent,
    SlideStoryboardStatus,
    TeachingScope,
    TeachingScopeUnauthorizedError,
)

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
class PostgresAssignmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert DATABASE_URL is not None
        parameters = psycopg.conninfo.conninfo_to_dict(DATABASE_URL)
        database_name = parameters.get("dbname", "")
        if not database_name.endswith("_test"):
            raise RuntimeError("integration database name must end with _test")

        apply_migrations(DATABASE_URL, ROOT / "deploy" / "postgres" / "migrations")
        cls.role = f"athena_rls_{uuid.uuid4().hex[:12]}"
        cls.connection = psycopg.connect(
            DATABASE_URL,
            autocommit=True,
            row_factory=dict_row,
        )
        cls._reset_fixtures()
        cls.connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(cls.role)))
        cls.connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(cls.role))
        )
        cls.connection.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(cls.role)
            )
        )
        cls._insert_school("school-a", "a", "teacher-a")
        cls._insert_school("school-b", "b", "teacher-b")

    @classmethod
    def tearDownClass(cls) -> None:
        if not hasattr(cls, "connection"):
            return
        cls._reset_fixtures()
        cls.connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(cls.role)))
        cls.connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.role)))
        cls.connection.close()

    @classmethod
    def _reset_fixtures(cls) -> None:
        tables = sql.SQL(", ").join(sql.Identifier(name) for name in reversed(RLS_TABLES))
        cls.connection.execute(sql.SQL("TRUNCATE {} CASCADE").format(tables))

    @classmethod
    def _insert_school(cls, school_id: str, suffix: str, principal_id: str) -> None:
        edition_id = f"edition-{suffix}"
        source_sha256 = suffix * 64
        group_id = f"group-{suffix}"
        assignment_id = f"assignment-{suffix}"
        cls.connection.execute(
            """
            INSERT INTO textbook_editions (
                edition_id,
                owner_school_id,
                subject,
                grade,
                volume,
                publisher,
                edition_label,
                lifecycle_status,
                activated_by,
                activated_at,
                activation_reason
            )
            VALUES (
                %s, %s, 'science', '8', '2', 'publisher', '2026',
                'active', 'fixture-admin', now(), 'integration fixture'
            )
            """,
            (edition_id, school_id),
        )
        cls.connection.execute(
            """
            INSERT INTO textbook_sources (
                edition_id,
                source_sha256,
                original_filename,
                byte_size,
                page_count,
                import_status,
                authorization_scope,
                manifest_uri,
                approved_by,
                approved_at,
                activated_by,
                activated_at,
                activation_reason
            )
            VALUES (
                %s, %s, 'textbook.pdf', 100, 1, 'active', 'school', %s,
                'reviewer', now(), 'fixture-admin', now(), 'integration fixture'
            )
            """,
            (edition_id, source_sha256, f"imports/{suffix}/manifest.json"),
        )
        cls.connection.execute(
            """
            INSERT INTO textbook_pages (
                edition_id,
                source_sha256,
                pdf_page_index,
                page_label,
                printed_page,
                width,
                height,
                render_uri,
                quality_status
            )
            VALUES (%s, %s, 1, '1', 1, 100, 200, 'renders/page-0001.png', 'passed')
            """,
            (edition_id, source_sha256),
        )
        cls.connection.execute(
            """
            INSERT INTO textbook_evidence (
                evidence_id,
                edition_id,
                source_sha256,
                pdf_page_index,
                evidence_type,
                quote,
                content_hash,
                bbox_x0,
                bbox_y0,
                bbox_x1,
                bbox_y1
            )
            VALUES (%s, %s, %s, 1, 'paragraph', 'fixture', %s, 0, 0, 10, 10)
            """,
            (f"evidence-{suffix}", edition_id, source_sha256, suffix * 64),
        )
        cls.connection.execute(
            """
            INSERT INTO teaching_groups (
                teaching_group_id,
                owner_school_id,
                academic_year,
                grade,
                subject
            )
            VALUES (%s, %s, '2026-2027', '8', 'science')
            """,
            (group_id, school_id),
        )
        cls.connection.execute(
            """
            INSERT INTO principal_teaching_scopes (
                principal_id,
                teaching_group_id,
                granted_by
            )
            VALUES (%s, %s, 'admin')
            """,
            (principal_id, group_id),
        )
        cls.connection.execute(
            """
            INSERT INTO textbook_assignments (
                assignment_id,
                teaching_group_id,
                edition_id,
                source_sha256,
                valid_from,
                valid_until,
                assigned_by
            )
            VALUES (%s, %s, %s, %s, '2026-01-01', '2026-12-31', 'admin')
            """,
            (assignment_id, group_id, edition_id, source_sha256),
        )
        cls.connection.execute(
            """
            INSERT INTO workspace_textbook_pins (
                workspace_id,
                owner_school_id,
                assignment_id,
                edition_id,
                source_sha256,
                pinned_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                f"workspace-{suffix}",
                school_id,
                assignment_id,
                edition_id,
                source_sha256,
                principal_id,
            ),
        )

    def setUp(self) -> None:
        self.connection.execute(
            "TRUNCATE lesson_plan_events, lesson_plan_revision_evidence, "
            "lesson_plan_revisions, lesson_plans CASCADE"
        )

    def tearDown(self) -> None:
        self.connection.execute(
            "TRUNCATE lesson_plan_events, lesson_plan_revision_evidence, "
            "lesson_plan_revisions, lesson_plans CASCADE"
        )

    def test_repository_resolves_only_authorized_school_scope(self) -> None:
        assert DATABASE_URL is not None
        catalog = PostgresAssignmentCatalog(DATABASE_URL)
        scope = TeachingScope("school-a", "2026-2027", "8", "science")

        resolved = catalog.resolve("teacher-a", scope, on_date=date(2026, 8, 1))

        self.assertEqual(resolved.assignment.assignment_id, "assignment-a")
        self.assertEqual(resolved.registration.edition_id, "edition-a")
        with self.assertRaises(TeachingScopeUnauthorizedError):
            catalog.resolve("teacher-b", scope, on_date=date(2026, 8, 1))

    def test_workspace_pin_is_idempotent_and_cannot_cross_school(self) -> None:
        assert DATABASE_URL is not None
        catalog = PostgresWorkspaceCatalog(DATABASE_URL)
        scope = TeachingScope("school-a", "2026-2027", "8", "science")

        result = catalog.pin(
            "workspace-a",
            "teacher-a",
            scope,
            on_date=date(2026, 8, 1),
        )

        self.assertTrue(result.reused)
        self.assertEqual(result.workspace.assignment_id, "assignment-a")
        fetched = catalog.get("workspace-a", "teacher-a", "school-a")
        self.assertEqual(fetched.edition_id, "edition-a")
        with self.assertRaises(WorkspaceUnauthorizedError):
            catalog.get("workspace-a", "teacher-b", "school-a")
        with self.assertRaises(WorkspaceNotFoundError):
            catalog.get("workspace-a", "teacher-a", "school-b")
        with self.assertRaises(WorkspaceConflictError):
            catalog.pin(
                "workspace-a",
                "teacher-b",
                TeachingScope("school-b", "2026-2027", "8", "science"),
                on_date=date(2026, 8, 1),
            )

    def test_workspace_keeps_pinned_edition_but_rechecks_active_grant(self) -> None:
        assert DATABASE_URL is not None
        catalog = PostgresWorkspaceCatalog(DATABASE_URL)
        try:
            self.connection.execute(
                "UPDATE textbook_assignments SET valid_until = '2026-07-31' "
                "WHERE assignment_id = 'assignment-a'"
            )
            workspace = catalog.get("workspace-a", "teacher-a", "school-a")
            self.assertEqual(workspace.assignment_id, "assignment-a")

            self.connection.execute(
                "UPDATE principal_teaching_scopes SET revoked_at = now() "
                "WHERE principal_id = 'teacher-a' AND revoked_at IS NULL"
            )
            with self.assertRaises(WorkspaceUnauthorizedError):
                catalog.get("workspace-a", "teacher-a", "school-a")
        finally:
            self.connection.execute(
                "UPDATE textbook_assignments SET valid_until = '2026-12-31' "
                "WHERE assignment_id = 'assignment-a'"
            )
            self.connection.execute(
                "UPDATE principal_teaching_scopes SET revoked_at = NULL "
                "WHERE principal_id = 'teacher-a'"
            )

    def test_lesson_plan_revisions_restore_confirmation_and_append_only_guards(self) -> None:
        assert DATABASE_URL is not None
        catalog = PostgresLessonPlanCatalog(DATABASE_URL)
        generation = LessonPlanGenerationInput(
            title="空气的组成",
            objectives=("定位教材证据并说明空气组成",),
            required_topics=("空气的组成",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("evidence-a",),
            preserve_experiment=True,
            instruction="按 40 分钟生成教案并保留实验环节",
        )

        created = catalog.generate(
            "workspace-a",
            "teacher-a",
            "school-a",
            generation,
            request_id="request-generate",
        )
        repeated = catalog.generate(
            "workspace-a",
            "teacher-a",
            "school-a",
            generation,
            request_id="request-generate-repeat",
        )
        self.assertFalse(created.reused)
        self.assertTrue(repeated.reused)
        self.assertEqual(created.plan.revision.content.budget.planned_minutes, 35)

        payload = created.plan.revision.content.to_payload()
        payload.pop("budget")
        payload.pop("confirmation_ready")
        payload.pop("confirmation_blockers")
        payload["lesson_segments"][0]["minutes"] += 10
        over_budget = LessonPlanContent.from_payload(payload)
        saved = catalog.save(
            "workspace-a",
            "teacher-a",
            "school-a",
            over_budget,
            base_revision_number=1,
            change_summary="延长问题导入用于测试超时门禁",
            request_id="request-save",
        )
        self.assertEqual(saved.plan.current_revision_number, 2)
        self.assertTrue(saved.plan.revision.content.budget.is_over_budget)
        with self.assertRaises(LessonPlanConflictError):
            catalog.save(
                "workspace-a",
                "teacher-a",
                "school-a",
                over_budget,
                base_revision_number=1,
                change_summary="过期客户端保存",
                request_id="request-stale-save",
            )
        with self.assertRaises(LessonPlanConfirmationError):
            catalog.confirm(
                "workspace-a",
                "teacher-a",
                "school-a",
                2,
                request_id="request-confirm-over-budget",
            )

        comparison = catalog.compare("workspace-a", "teacher-a", "school-a", 1, 2)
        self.assertEqual(comparison["planned_minutes_delta"], 10)
        self.assertEqual(comparison["segments_changed"], ["opening"])

        restored = catalog.restore(
            "workspace-a",
            "teacher-a",
            "school-a",
            1,
            base_revision_number=2,
            change_summary="恢复首版课时安排",
            request_id="request-restore",
        )
        self.assertEqual(restored.plan.current_revision_number, 3)
        self.assertEqual(restored.plan.revision.restored_from_revision, 1)
        confirmed = catalog.confirm(
            "workspace-a",
            "teacher-a",
            "school-a",
            3,
            request_id="request-confirm",
        )
        self.assertEqual(confirmed.plan.status, LessonPlanStatus.TEACHER_CONFIRMED)
        self.assertTrue(catalog.export("workspace-a", "teacher-a", "school-a"))

        with self.assertRaises(psycopg.errors.RaiseException):
            self.connection.execute(
                "UPDATE lesson_plan_revisions SET change_summary = 'overwrite' "
                "WHERE plan_id = %s AND revision_number = 1",
                (confirmed.plan.plan_id,),
            )

        with self.connection.transaction():
            self.connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.role)))
            self.connection.execute("SELECT set_config('athena.school_id', 'school-b', true)")
            hidden = {
                table: self.connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"]
                for table in (
                    "lesson_plans",
                    "lesson_plan_revisions",
                    "lesson_plan_revision_evidence",
                    "lesson_plan_events",
                )
            }
        self.assertEqual(hidden, {table: 0 for table in hidden})

    def test_slide_storyboard_requires_current_confirmed_lesson_and_is_append_only(
        self,
    ) -> None:
        assert DATABASE_URL is not None
        plans = PostgresLessonPlanCatalog(DATABASE_URL)
        storyboards = PostgresSlideStoryboardCatalog(DATABASE_URL)
        generation = LessonPlanGenerationInput(
            title="空气的组成",
            objectives=("定位教材证据并说明空气组成",),
            required_topics=("空气的组成",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("evidence-a",),
            preserve_experiment=True,
            instruction="按 40 分钟生成教案并保留实验环节",
        )
        plan = plans.generate(
            "workspace-a",
            "teacher-a",
            "school-a",
            generation,
            request_id="storyboard-plan-generate",
        ).plan
        plans.confirm(
            "workspace-a",
            "teacher-a",
            "school-a",
            plan.current_revision_number,
            request_id="storyboard-plan-confirm",
        )

        generated = storyboards.generate(
            "workspace-a",
            "teacher-a",
            "school-a",
            template_id="simple-classroom",
            request_id="storyboard-generate",
        )
        self.assertEqual(generated.storyboard.source_lesson_revision, 1)
        self.assertTrue(generated.storyboard.source_current)
        payload = generated.storyboard.revision.content.to_payload()
        payload["slides"][0]["title"] = "空气由什么组成？"
        payload.pop("summary")
        edited = storyboards.save(
            "workspace-a",
            "teacher-a",
            "school-a",
            SlideStoryboardContent.from_payload(payload),
            base_revision_number=1,
            change_summary="将第一页改成问题导入",
            request_id="storyboard-save",
        )
        self.assertEqual(edited.storyboard.current_revision_number, 2)
        confirmed = storyboards.confirm(
            "workspace-a",
            "teacher-a",
            "school-a",
            2,
            request_id="storyboard-confirm",
        )
        self.assertEqual(confirmed.storyboard.status, SlideStoryboardStatus.TEACHER_CONFIRMED)
        self.assertTrue(storyboards.export("workspace-a", "teacher-a", "school-a"))

        lesson_payload = plan.revision.content.to_payload()
        lesson_payload["title"] = "空气的组成（教师二次修改）"
        changed_lesson = LessonPlanContent.from_payload(lesson_payload)
        plans.save(
            "workspace-a",
            "teacher-a",
            "school-a",
            changed_lesson,
            base_revision_number=1,
            change_summary="确认后重新修改教案",
            request_id="storyboard-source-change",
        )
        with self.assertRaisesRegex(
            SlideStoryboardSourceChangedError,
            "源教案必须保持为当前且已由教师确认",
        ):
            storyboards.export("workspace-a", "teacher-a", "school-a")

        with self.assertRaises(psycopg.errors.RaiseException):
            self.connection.execute(
                "UPDATE slide_storyboard_revisions SET change_summary = 'overwrite' "
                "WHERE storyboard_id = %s AND revision_number = 1",
                (confirmed.storyboard.storyboard_id,),
            )

        with self.connection.transaction():
            self.connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.role)))
            self.connection.execute("SELECT set_config('athena.school_id', 'school-b', true)")
            hidden = {
                table: self.connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"]
                for table in (
                    "slide_storyboards",
                    "slide_storyboard_revisions",
                    "slide_storyboard_revision_evidence",
                    "slide_storyboard_events",
                )
            }
        self.assertEqual(hidden, {table: 0 for table in hidden})

    def test_row_level_security_hides_every_other_school_row(self) -> None:
        with self.connection.transaction():
            self.connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.role)))
            self.connection.execute("SELECT set_config('athena.school_id', 'school-a', true)")
            counts = {
                table: self.connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"]
                for table in RLS_TABLES
            }

        self.assertEqual(counts, {table: 1 for table in RLS_TABLES})


if __name__ == "__main__":
    unittest.main()
