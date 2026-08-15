import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))

from athena_domain import (  # noqa: E402
    ExperimentMode,
    LessonBudget,
    LessonExperiment,
    LessonPlanContent,
    LessonSegment,
    LessonSession,
    LessonSessionKind,
    SegmentPriority,
    TopicCoverageStatus,
    TopicEvidenceCoverage,
    build_deterministic_lesson_plan,
)


class LessonBudgetTests(unittest.TestCase):
    def test_reports_over_budget_instead_of_hiding_it(self) -> None:
        budget = LessonBudget(
            available_minutes=40,
            segments=(
                LessonSegment("导入", 5, SegmentPriority.REQUIRED, ("ev-1",)),
                LessonSegment("探究", 30, SegmentPriority.REQUIRED, ("ev-2",)),
                LessonSegment("练习", 10, SegmentPriority.OPTIONAL, ("ev-3",)),
            ),
        )
        self.assertTrue(budget.is_over_budget)
        self.assertEqual(budget.over_by_minutes, 5)
        self.assertEqual([item.title for item in budget.optional_segments()], ["练习"])

    def test_deterministic_plan_respects_40_minute_budget_and_keeps_experiment(self) -> None:
        plan = build_deterministic_lesson_plan(
            title="空气的组成",
            objectives=("定位教材证据并说明空气组成",),
            required_topics=("空气的组成",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("ev-1", "ev-2"),
            preserve_experiment=True,
        )

        self.assertEqual(plan.available_minutes, 40)
        self.assertEqual(plan.budget.planned_minutes, 35)
        self.assertFalse(plan.budget.is_over_budget)
        experiment = next(item for item in plan.lesson_segments if item.segment_id == "experiment")
        self.assertTrue(experiment.locked)
        self.assertEqual(plan, LessonPlanContent.from_payload(plan.to_payload()))

    def test_real_teacher_task_preserves_sessions_coverage_and_integrated_lab(self) -> None:
        topics = (
            "拉瓦锡实验及原理分析",
            "实验重构",
            "通过重构实验验证空气中氧气含量",
            "实验误差来源分析",
            "空气成分",
            "氧气的性质",
            "代表性物质与氧气的反应",
            "氧气的三种实验室制法",
            "气体收集方式与实验装置连接",
            "气密性检测",
            "实验操作注意事项",
            "催化剂定义与作用",
            "化合反应与分解反应",
        )
        coverage = tuple(
            TopicEvidenceCoverage(
                topic_id=f"topic-{index}",
                title=topic,
                status=(
                    TopicCoverageStatus.PARTIAL
                    if index in {8, 9, 11}
                    else TopicCoverageStatus.COVERED
                ),
                evidence_ids=(f"ev-{index}",),
                notes=(
                    "高锰酸钾制氧来自教师补充图片，尚未登记为工作区证据。"
                    if index == 8
                    else "教材只明确覆盖排水收集，尚未定位向上排空气法。"
                    if index == 9
                    else "教材覆盖正确步骤，尚未定位错误装置图专项材料。"
                    if index == 11
                    else "教材证据已定位，仍需教师复核。"
                ),
            )
            for index, topic in enumerate(topics, start=1)
        )
        sessions = (
            LessonSession("lecture-1", "讲授与空气含量实验", 40, LessonSessionKind.MIXED),
            LessonSession("lecture-2", "氧气性质与反应实验", 40, LessonSessionKind.MIXED),
            LessonSession("lecture-3", "制取方法与反应类型", 20),
            LessonSession("student-lab", "学生连续实验", 40, LessonSessionKind.STUDENT_LAB),
        )
        experiments = (
            LessonExperiment(
                "experiment-air-content",
                "空气中氧气含量重构实验",
                "lecture-1",
                12,
                ExperimentMode.DEMONSTRATION_AND_STUDENT,
                ("topic-3",),
                ("ev-3",),
                ("装置确认", "反应与冷却", "读数与误差"),
                ("教师确认药品、点燃和冷却条件",),
            ),
            LessonExperiment(
                "experiment-oxygen-reactions",
                "代表性物质与氧气反应",
                "lecture-2",
                14,
                ExperimentMode.DEMONSTRATION_AND_STUDENT,
                ("topic-7",),
                ("ev-7",),
                ("现象观察", "产物判断", "反应表达"),
                ("教师确认燃烧实验防护和废气处理",),
            ),
            LessonExperiment(
                "experiment-integrated-oxygen-demo",
                "制氧—气密性—收集连续演示",
                "lecture-3",
                12,
                ExperimentMode.DEMONSTRATION,
                ("topic-8", "topic-9", "topic-10"),
                ("ev-8", "ev-9", "ev-10"),
                ("连接装置", "检查气密性", "制取氧气", "排水收集"),
                ("教师确认演示药品、装置、防护和废弃物处理",),
            ),
            LessonExperiment(
                "experiment-integrated-oxygen-lab",
                "制氧—气密性—收集连续学生实验",
                "student-lab",
                40,
                ExperimentMode.STUDENT_LAB,
                ("topic-8", "topic-9", "topic-10"),
                ("ev-8", "ev-9", "ev-10"),
                ("连接装置", "检查气密性", "制取氧气", "排水收集", "验满与整理"),
                ("教师确认学生实验药品浓度、装置连接、个人防护和废弃物处理",),
            ),
        )
        plan = build_deterministic_lesson_plan(
            title="1.1 空气的成分",
            objectives=("按教材证据和实验链路完成空气与氧气单元学习",),
            required_topics=topics,
            lesson_count=4,
            minutes_per_lesson=40,
            evidence_ids=tuple(f"ev-{index}" for index in range(1, 14)),
            preserve_experiment=True,
            sessions=sessions,
            topic_coverage=coverage,
            experiments=experiments,
        )

        self.assertEqual(plan.available_minutes, 140)
        self.assertLessEqual(plan.budget.planned_minutes, 140)
        self.assertEqual(plan.session_budget_summaries[-1]["planned_minutes"], 40)
        self.assertEqual(len(plan.experiments), 4)
        self.assertIn("检查气密性", plan.experiments[-1].integrated_steps)
        self.assertIn("topic_evidence:topic-8:partial", plan.confirmation_blockers)
        self.assertFalse(plan.confirmation_ready)

        payload = plan.to_payload()
        for index in (7, 8, 10):
            payload["topic_coverage"][index]["status"] = "covered"
        for experiment in payload["experiments"]:
            experiment["teacher_safety_confirmed"] = True
        payload.pop("confirmation_ready")
        payload.pop("confirmation_blockers")
        ready = LessonPlanContent.from_payload(payload)
        self.assertTrue(ready.confirmation_ready)
        self.assertEqual(ready, LessonPlanContent.from_payload(ready.to_payload()))

    def test_reads_legacy_v1_payload_without_inventing_session_evidence(self) -> None:
        plan = build_deterministic_lesson_plan(
            title="空气的组成",
            objectives=("定位教材证据",),
            required_topics=("空气的组成",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("ev-1",),
            preserve_experiment=True,
        )
        payload = plan.to_payload()
        payload["schema_version"] = "athena.lesson-plan.v1"
        for field in (
            "sessions",
            "topic_coverage",
            "experiments",
            "session_budgets",
            "confirmation_ready",
            "confirmation_blockers",
        ):
            payload.pop(field)
        for segment in payload["lesson_segments"]:
            segment.pop("session_id")
            segment.pop("topic_ids")

        restored = LessonPlanContent.from_payload(payload)
        self.assertFalse(restored.sessions)
        self.assertTrue(restored.confirmation_ready)

    def test_rejects_forged_session_budget_and_confirmation_state(self) -> None:
        topic = TopicEvidenceCoverage(
            "topic-1",
            "空气成分",
            TopicCoverageStatus.COVERED,
            ("ev-1",),
        )
        plan = build_deterministic_lesson_plan(
            title="空气成分",
            objectives=("定位教材证据",),
            required_topics=("空气成分",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("ev-1",),
            preserve_experiment=False,
            sessions=(LessonSession("session-1", "第一课时", 40),),
            topic_coverage=(topic,),
        )
        payload = plan.to_payload()
        payload["session_budgets"][0]["planned_minutes"] = 1
        payload["confirmation_ready"] = not payload["confirmation_ready"]

        with self.assertRaisesRegex(ValueError, "session_budgets"):
            LessonPlanContent.from_payload(payload)

    def test_rejects_unknown_nested_v2_fields(self) -> None:
        plan = build_deterministic_lesson_plan(
            title="空气成分",
            objectives=("定位教材证据",),
            required_topics=("空气成分",),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("ev-1",),
            preserve_experiment=False,
            sessions=(LessonSession("session-1", "第一课时", 40),),
            topic_coverage=(
                TopicEvidenceCoverage(
                    "topic-1",
                    "空气成分",
                    TopicCoverageStatus.COVERED,
                    ("ev-1",),
                ),
            ),
        )
        payload = plan.to_payload()
        payload["sessions"][0]["ignored_field"] = "should fail"

        with self.assertRaisesRegex(ValueError, "unsupported lesson session fields"):
            LessonPlanContent.from_payload(payload)

    def test_rejects_experiment_evidence_unrelated_to_its_topic(self) -> None:
        with self.assertRaisesRegex(ValueError, "topic must share a topic evidence"):
            build_deterministic_lesson_plan(
                title="空气成分",
                objectives=("定位教材证据",),
                required_topics=("空气成分",),
                lesson_count=1,
                minutes_per_lesson=40,
                evidence_ids=("ev-topic", "ev-unrelated"),
                preserve_experiment=True,
                sessions=(
                    LessonSession(
                        "session-1",
                        "混合课时",
                        40,
                        LessonSessionKind.MIXED,
                    ),
                ),
                topic_coverage=(
                    TopicEvidenceCoverage(
                        "topic-1",
                        "空气成分",
                        TopicCoverageStatus.COVERED,
                        ("ev-topic",),
                    ),
                ),
                experiments=(
                    LessonExperiment(
                        "experiment-1",
                        "无关证据实验",
                        "session-1",
                        10,
                        ExperimentMode.DEMONSTRATION,
                        ("topic-1",),
                        ("ev-unrelated",),
                    ),
                ),
            )

    def test_rejects_client_budget_summary_that_hides_overtime(self) -> None:
        plan = build_deterministic_lesson_plan(
            title="空气的组成",
            objectives=("定位教材证据",),
            required_topics=(),
            lesson_count=1,
            minutes_per_lesson=40,
            evidence_ids=("ev-1",),
            preserve_experiment=False,
        )
        payload = plan.to_payload()
        payload["budget"]["planned_minutes"] = 1

        with self.assertRaisesRegex(ValueError, "budget summary"):
            LessonPlanContent.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
