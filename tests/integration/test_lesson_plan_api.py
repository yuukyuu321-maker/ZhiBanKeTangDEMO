import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "model-gateway" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "audit" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "textbook-ingestion" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app import main  # noqa: E402
from app.lesson_plan_service import (  # noqa: E402
    LessonPlanConfirmationError,
    LessonPlanMutationResult,
    LessonPlanRecord,
    LessonPlanRevision,
    LessonPlanRevisionSummary,
)
from athena_domain import (  # noqa: E402
    LESSON_PLAN_SCHEMA_VERSION,
    LessonPlanStatus,
    build_deterministic_lesson_plan,
)
from fastapi.testclient import TestClient  # noqa: E402


def lesson_content():
    return build_deterministic_lesson_plan(
        title="空气的组成",
        objectives=("定位教材证据并说明空气组成",),
        required_topics=("空气的组成",),
        lesson_count=1,
        minutes_per_lesson=40,
        evidence_ids=("evidence-1",),
        preserve_experiment=True,
    )


def lesson_plan(
    revision_number: int = 1,
    status: LessonPlanStatus = LessonPlanStatus.DRAFT,
) -> LessonPlanRecord:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    revision = LessonPlanRevision(
        revision_number=revision_number,
        source="generated" if revision_number == 1 else "teacher_edit",
        restored_from_revision=None,
        created_by="teacher-demo",
        created_at=now,
        change_summary="测试修订",
        content=lesson_content(),
        content_sha256="a" * 64,
        evidence_fingerprint="b" * 64,
        model_adapter="deterministic-test" if revision_number == 1 else None,
        prompt_template_version="athena.lesson-plan.deterministic.v1",
        schema_version=LESSON_PLAN_SCHEMA_VERSION,
    )
    confirmed = status is LessonPlanStatus.TEACHER_CONFIRMED
    return LessonPlanRecord(
        plan_id="lesson-plan-demo",
        workspace_id="workspace-demo",
        owner_school_id="school-demo",
        created_by="teacher-demo",
        created_at=now,
        updated_at=now,
        status=status,
        current_revision_number=revision_number,
        confirmed_revision_number=revision_number if confirmed else None,
        confirmed_by="teacher-demo" if confirmed else None,
        confirmed_at=now if confirmed else None,
        revision=revision,
    )


class LessonPlanApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Mock()
        self.catalog.configured = True
        self.catalog.backend = "memory-test"
        self.patch = patch.object(main, "lesson_plan_catalog", self.catalog)
        self.patch.start()
        self.client = TestClient(main.app)
        self.headers = {
            "X-Athena-Principal-Id": "teacher-demo",
            "X-Athena-Request-Id": "request-api-test",
        }

    def tearDown(self) -> None:
        self.patch.stop()

    def test_generation_revision_restore_confirmation_and_export_routes(self) -> None:
        draft = lesson_plan()
        edited = lesson_plan(2)
        restored = lesson_plan(3)
        confirmed = lesson_plan(3, LessonPlanStatus.TEACHER_CONFIRMED)
        self.catalog.generate.return_value = LessonPlanMutationResult(draft)
        self.catalog.save.return_value = LessonPlanMutationResult(edited)
        self.catalog.revisions.return_value = (
            LessonPlanRevisionSummary(
                revision_number=2,
                source="teacher_edit",
                restored_from_revision=None,
                created_by="teacher-demo",
                created_at=edited.updated_at,
                change_summary="自动保存",
                content_sha256="a" * 64,
            ),
        )
        self.catalog.compare.return_value = {
            "from_revision": 1,
            "to_revision": 2,
            "content_changed": True,
        }
        self.catalog.restore.return_value = LessonPlanMutationResult(restored)
        self.catalog.confirm.return_value = LessonPlanMutationResult(confirmed)
        self.catalog.export.return_value = confirmed

        generated = self.client.post(
            "/v1/workspaces/workspace-demo/lesson-plan/generate",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "title": "空气的组成",
                "objectives": ["定位教材证据并说明空气组成"],
                "required_topics": ["空气的组成"],
                "lesson_count": 1,
                "minutes_per_lesson": 40,
                "evidence_ids": ["evidence-1"],
                "preserve_experiment": True,
                "instruction": "按 40 分钟生成教案并保留实验环节",
            },
        )
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(
            generated.json()["plan"]["revision"]["content"]["budget"]["planned_minutes"],
            35,
        )

        saved = self.client.put(
            "/v1/workspaces/workspace-demo/lesson-plan",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "base_revision_number": 1,
                "change_summary": "自动保存",
                "content": draft.revision.content.to_payload(),
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["plan"]["current_revision_number"], 2)

        revisions = self.client.get(
            "/v1/workspaces/workspace-demo/lesson-plan/revisions",
            params={"school_id": "school-demo"},
            headers=self.headers,
        )
        comparison = self.client.get(
            "/v1/workspaces/workspace-demo/lesson-plan/compare",
            params={
                "school_id": "school-demo",
                "from_revision": 1,
                "to_revision": 2,
            },
            headers=self.headers,
        )
        self.assertEqual(revisions.status_code, 200)
        self.assertTrue(comparison.json()["content_changed"])

        restored_response = self.client.post(
            "/v1/workspaces/workspace-demo/lesson-plan/revisions/1/restore",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "base_revision_number": 2,
                "change_summary": "恢复首版",
            },
        )
        self.assertEqual(restored_response.json()["plan"]["current_revision_number"], 3)

        confirmed_response = self.client.post(
            "/v1/workspaces/workspace-demo/lesson-plan/confirm",
            headers=self.headers,
            json={"school_id": "school-demo", "revision_number": 3},
        )
        exported = self.client.get(
            "/v1/workspaces/workspace-demo/lesson-plan/export",
            params={"school_id": "school-demo"},
            headers=self.headers,
        )
        self.assertTrue(confirmed_response.json()["plan"]["export_ready"])
        self.assertTrue(exported.json()["teacher_confirmed"])

    def test_real_teacher_task_maps_multi_session_and_integrated_lab_contract(self) -> None:
        self.catalog.generate.return_value = LessonPlanMutationResult(lesson_plan())
        topics = [
            "拉瓦锡实验及原理分析",
            "实验重构",
            "通过重构实验验证空气中氧气含量",
            "实验误差来源分析",
            "空气成分",
            "氧气的性质（物理和化学）",
            "代表性物质与氧气的反应",
            "氧气的三种实验室制法",
            "气体收集方式与实验装置连接",
            "气密性检测",
            "实验操作注意事项",
            "催化剂定义与作用",
            "化合反应与分解反应",
        ]
        coverage = [
            {
                "topic_id": f"topic-{index}",
                "title": title,
                "status": "partial" if index in {8, 9, 11} else "covered",
                "evidence_ids": [f"evidence-{index}"],
                "notes": (
                    "高锰酸钾制氧来自教师补充图片，尚未登记为教材证据。"
                    if index == 8
                    else "教材只明确覆盖排水收集，尚未定位向上排空气法。"
                    if index == 9
                    else "教材覆盖正确步骤，尚未定位错误装置图专项材料。"
                    if index == 11
                    else "教材证据已定位，仍需教师复核。"
                ),
            }
            for index, title in enumerate(topics, start=1)
        ]
        response = self.client.post(
            "/v1/workspaces/workspace-demo/lesson-plan/generate",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "title": "1.1 空气的成分",
                "objectives": ["按证据和实验链路完成空气与氧气单元学习"],
                "required_topics": topics,
                "lesson_count": 4,
                "minutes_per_lesson": 40,
                "evidence_ids": [f"evidence-{index}" for index in range(1, 14)],
                "preserve_experiment": True,
                "instruction": "总计约 140 分钟；学生实验连续完成制氧、气密性检测和收集。",
                "sessions": [
                    {
                        "session_id": "lecture-1",
                        "title": "第一阶段",
                        "minutes": 40,
                        "kind": "instruction",
                    },
                    {
                        "session_id": "lecture-2",
                        "title": "第二阶段",
                        "minutes": 40,
                        "kind": "mixed",
                    },
                    {
                        "session_id": "lecture-3",
                        "title": "第三阶段",
                        "minutes": 20,
                        "kind": "instruction",
                    },
                    {
                        "session_id": "student-lab",
                        "title": "连续学生实验",
                        "minutes": 40,
                        "kind": "student_lab",
                    },
                ],
                "topic_coverage": coverage,
                "experiments": [
                    {
                        "experiment_id": "experiment-integrated-oxygen-demo",
                        "title": "制氧—气密性检测—收集连续演示",
                        "session_id": "lecture-3",
                        "minutes": 12,
                        "mode": "demonstration",
                        "topic_ids": ["topic-8", "topic-9", "topic-10"],
                        "evidence_ids": ["evidence-8", "evidence-9", "evidence-10"],
                        "integrated_steps": ["连接装置", "检查气密性", "制取氧气", "收集氧气"],
                        "safety_notes": ["教师确认演示药品、装置、防护和废弃物处理"],
                        "teacher_safety_confirmed": False,
                    },
                    {
                        "experiment_id": "experiment-integrated-oxygen-lab",
                        "title": "制氧—气密性检测—收集连续学生实验",
                        "session_id": "student-lab",
                        "minutes": 40,
                        "mode": "student_lab",
                        "topic_ids": ["topic-8", "topic-9", "topic-10"],
                        "evidence_ids": ["evidence-8", "evidence-9", "evidence-10"],
                        "integrated_steps": ["连接装置", "检查气密性", "制取氧气", "收集氧气"],
                        "safety_notes": ["教师确认药品、装置、防护和废弃物处理"],
                        "teacher_safety_confirmed": False,
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        generation = self.catalog.generate.call_args.args[3]
        self.assertEqual(sum(session.minutes for session in generation.sessions), 140)
        self.assertEqual(generation.sessions[-1].minutes, 40)
        self.assertEqual(len(generation.experiments), 2)
        self.assertEqual(generation.experiments[0].mode, "demonstration")
        self.assertEqual(
            generation.experiments[1].integrated_steps,
            ("连接装置", "检查气密性", "制取氧气", "收集氧气"),
        )
        self.assertEqual(
            [item.status for item in generation.topic_coverage if item.status == "partial"],
            ["partial", "partial", "partial"],
        )
        self.assertIn("高锰酸钾", generation.topic_coverage[7].notes)
        self.assertIn("向上排空气", generation.topic_coverage[8].notes)

    def test_invalid_budget_and_unconfirmed_export_are_explicit(self) -> None:
        payload = lesson_content().to_payload()
        payload["budget"]["planned_minutes"] = 1
        invalid = self.client.put(
            "/v1/workspaces/workspace-demo/lesson-plan",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "base_revision_number": 1,
                "change_summary": "伪造预算",
                "content": payload,
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.catalog.save.assert_not_called()

        self.catalog.export.side_effect = LessonPlanConfirmationError(
            "lesson plan must be teacher-confirmed before export"
        )
        blocked = self.client.get(
            "/v1/workspaces/workspace-demo/lesson-plan/export",
            params={"school_id": "school-demo"},
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 409)


if __name__ == "__main__":
    unittest.main()
