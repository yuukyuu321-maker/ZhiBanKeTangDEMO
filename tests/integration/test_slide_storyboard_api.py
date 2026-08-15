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
from app.slide_storyboard_service import (  # noqa: E402
    SlideStoryboardMutationResult,
    SlideStoryboardRecord,
    SlideStoryboardRevision,
    SlideStoryboardSourceChangedError,
)
from athena_domain import (  # noqa: E402
    SLIDE_STORYBOARD_SCHEMA_VERSION,
    SlideStoryboardStatus,
    build_deterministic_lesson_plan,
    build_deterministic_storyboard,
)
from fastapi.testclient import TestClient  # noqa: E402


def storyboard_content():
    lesson = build_deterministic_lesson_plan(
        title="空气的组成",
        objectives=("基于教材证据说明空气的组成",),
        required_topics=("空气的组成",),
        lesson_count=1,
        minutes_per_lesson=40,
        evidence_ids=("evidence-1",),
        preserve_experiment=True,
    )
    return build_deterministic_storyboard(
        lesson_plan_id="lesson-plan-demo",
        lesson_revision=3,
        lesson_content_sha256="a" * 64,
        lesson=lesson,
    )


def storyboard_record(
    revision_number: int = 1,
    status: SlideStoryboardStatus = SlideStoryboardStatus.DRAFT,
) -> SlideStoryboardRecord:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    content = storyboard_content()
    revision = SlideStoryboardRevision(
        revision_number=revision_number,
        source="generated" if revision_number == 1 else "teacher_edit",
        restored_from_revision=None,
        created_by="teacher-demo",
        created_at=now,
        change_summary="测试故事板修订",
        content=content,
        content_sha256="b" * 64,
        evidence_fingerprint="c" * 64,
        schema_version=SLIDE_STORYBOARD_SCHEMA_VERSION,
    )
    confirmed = status is SlideStoryboardStatus.TEACHER_CONFIRMED
    return SlideStoryboardRecord(
        storyboard_id="slide-storyboard-demo",
        workspace_id="workspace-demo",
        owner_school_id="school-demo",
        lesson_plan_id="lesson-plan-demo",
        source_lesson_revision=3,
        source_lesson_content_sha256="a" * 64,
        created_by="teacher-demo",
        created_at=now,
        updated_at=now,
        status=status,
        current_revision_number=revision_number,
        confirmed_revision_number=revision_number if confirmed else None,
        confirmed_by="teacher-demo" if confirmed else None,
        confirmed_at=now if confirmed else None,
        source_current=True,
        revision=revision,
    )


class SlideStoryboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = Mock()
        self.catalog.configured = True
        self.catalog.backend = "memory-test"
        self.patch = patch.object(main, "slide_storyboard_catalog", self.catalog)
        self.patch.start()
        self.client = TestClient(main.app)
        self.headers = {
            "X-Athena-Principal-Id": "teacher-demo",
            "X-Athena-Request-Id": "request-storyboard-api",
        }

    def tearDown(self) -> None:
        self.patch.stop()

    def test_generate_edit_confirm_and_export_routes(self) -> None:
        draft = storyboard_record()
        edited = storyboard_record(2)
        confirmed = storyboard_record(2, SlideStoryboardStatus.TEACHER_CONFIRMED)
        self.catalog.generate.return_value = SlideStoryboardMutationResult(draft)
        self.catalog.get.return_value = draft
        self.catalog.save.return_value = SlideStoryboardMutationResult(edited)
        self.catalog.confirm.return_value = SlideStoryboardMutationResult(confirmed)
        self.catalog.export.return_value = confirmed

        generated = self.client.post(
            "/v1/workspaces/workspace-demo/slide-storyboard/generate",
            headers=self.headers,
            json={"school_id": "school-demo", "template_id": "simple-classroom"},
        )
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(
            generated.json()["storyboard"]["revision"]["content"]["template_id"],
            "simple-classroom",
        )

        fetched = self.client.get(
            "/v1/workspaces/workspace-demo/slide-storyboard",
            params={"school_id": "school-demo"},
            headers=self.headers,
        )
        self.assertTrue(fetched.json()["storyboard"]["source_current"])

        saved = self.client.put(
            "/v1/workspaces/workspace-demo/slide-storyboard",
            headers=self.headers,
            json={
                "school_id": "school-demo",
                "base_revision_number": 1,
                "change_summary": "调整第一页标题",
                "content": draft.revision.content.to_payload(),
            },
        )
        self.assertEqual(saved.json()["storyboard"]["current_revision_number"], 2)

        confirmed_response = self.client.post(
            "/v1/workspaces/workspace-demo/slide-storyboard/confirm",
            headers=self.headers,
            json={"school_id": "school-demo", "revision_number": 2},
        )
        exported = self.client.get(
            "/v1/workspaces/workspace-demo/slide-storyboard/export",
            params={"school_id": "school-demo"},
            headers=self.headers,
        )
        self.assertTrue(confirmed_response.json()["storyboard"]["export_ready"])
        self.assertTrue(exported.json()["teacher_confirmed"])

    def test_source_change_returns_conflict(self) -> None:
        self.catalog.confirm.side_effect = SlideStoryboardSourceChangedError(
            "源教案必须保持为当前且已由教师确认；请基于最新确认教案重新生成故事板。"
        )
        response = self.client.post(
            "/v1/workspaces/workspace-demo/slide-storyboard/confirm",
            headers=self.headers,
            json={"school_id": "school-demo", "revision_number": 1},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "源教案必须保持为当前且已由教师确认；请基于最新确认教案重新生成故事板。",
        )


if __name__ == "__main__":
    unittest.main()
