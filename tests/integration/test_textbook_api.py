import base64
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "domain" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "textbook-ingestion" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "textbook-knowledge-api"))

from app import main  # noqa: E402
from app.assignment_service import AssignmentCatalog  # noqa: E402
from app.service import BundleCatalog  # noqa: E402
from app.workspace_service import (  # noqa: E402
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePinResult,
    WorkspaceTextbook,
    WorkspaceUnauthorizedError,
)
from athena_ingestion.storage import write_json, write_jsonl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DIGEST = "a" * 64
EDITION_ID = "synthetic-science-grade8-volume2"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def assignment_catalog() -> AssignmentCatalog:
    return AssignmentCatalog.from_payload(
        {
            "schema_version": "athena.textbook-assignment-catalog.v1",
            "editions": [
                {
                    "edition_id": EDITION_ID,
                    "source_sha256": DIGEST,
                    "status": "active",
                }
            ],
            "assignments": [
                {
                    "assignment_id": "assignment-1",
                    "scope": {
                        "school_id": "school-demo",
                        "academic_year": "2026-2027",
                        "grade": "八年级",
                        "subject": "科学",
                    },
                    "edition_id": EDITION_ID,
                    "source_sha256": DIGEST,
                    "valid_from": "2026-09-01",
                    "valid_until": "2027-08-31",
                    "assigned_by": "admin-demo",
                }
            ],
            "authorizations": [
                {
                    "principal_id": "teacher-demo",
                    "scope": {
                        "school_id": "school-demo",
                        "academic_year": "2026-2027",
                        "grade": "八年级",
                        "subject": "科学",
                    },
                }
            ],
        }
    )


class MemoryWorkspaceCatalog:
    def __init__(self, assignments: AssignmentCatalog) -> None:
        self._assignments = assignments
        self._pins: dict[str, WorkspaceTextbook] = {}

    @property
    def configured(self) -> bool:
        return True

    @property
    def backend(self) -> str:
        return "memory-test"

    def pin(self, workspace_id, principal_id, scope, *, on_date=None):
        resolved = self._assignments.resolve(principal_id, scope, on_date=on_date)
        proposed = WorkspaceTextbook(
            workspace_id=workspace_id,
            owner_school_id=scope.school_id,
            assignment_id=resolved.assignment.assignment_id,
            edition_id=resolved.registration.edition_id,
            source_sha256=resolved.registration.source_sha256,
            pinned_by=principal_id,
            pinned_at=datetime(2026, 8, 13, tzinfo=UTC),
        )
        existing = self._pins.get(workspace_id)
        if existing is not None:
            if existing != proposed:
                raise WorkspaceConflictError("workspace cannot be rebound")
            return WorkspacePinResult(workspace=existing, reused=True)
        self._pins[workspace_id] = proposed
        return WorkspacePinResult(workspace=proposed, reused=False)

    def get(self, workspace_id, principal_id, school_id):
        workspace = self._pins.get(workspace_id)
        if workspace is None or workspace.owner_school_id != school_id:
            raise WorkspaceNotFoundError("workspace was not found")
        if workspace.pinned_by != principal_id:
            raise WorkspaceUnauthorizedError("workspace is not authorized")
        return workspace


class TextbookApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        bundle = root / EDITION_ID / DIGEST
        write_json(
            bundle / "manifest.json",
            {
                "status": "active",
                "source": {"sha256": DIGEST},
                "edition": {"edition_id": EDITION_ID},
            },
        )
        write_json(bundle / "import-report.json", {"status": "active"})
        write_jsonl(
            bundle / "pages.jsonl",
            [
                {
                    "pdf_page_index": 1,
                    "page_label": "2",
                    "printed_page": 2,
                    "width": 100.0,
                    "height": 200.0,
                    "render_uri": "renders/page-0001.png",
                }
            ],
        )
        write_jsonl(
            bundle / "evidence.jsonl",
            [
                {
                    "evidence_id": "evidence-1",
                    "textbook_edition_id": EDITION_ID,
                    "source_sha256": DIGEST,
                    "pdf_page_index": 1,
                    "page_label": "2",
                    "printed_page": 2,
                    "bbox": {"x0": 10.0, "y0": 20.0, "x1": 90.0, "y1": 50.0},
                    "quote": "空气是一种混合物。",
                }
            ],
        )
        render = bundle / "renders" / "page-0001.png"
        render.parent.mkdir(parents=True, exist_ok=True)
        render.write_bytes(PNG_1X1)

        assignments = assignment_catalog()
        self.bundle_patch = patch.object(main, "catalog", BundleCatalog(root))
        self.assignment_patch = patch.object(main, "assignment_catalog", assignments)
        self.workspace_patch = patch.object(
            main,
            "workspace_catalog",
            MemoryWorkspaceCatalog(assignments),
        )
        self.bundle_patch.start()
        self.assignment_patch.start()
        self.workspace_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.workspace_patch.stop()
        self.assignment_patch.stop()
        self.bundle_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def scope_params() -> dict[str, str]:
        return {
            "school_id": "school-demo",
            "academic_year": "2026-2027",
            "grade": "八年级",
            "subject": "科学",
            "class_id": "class-2",
            "on_date": "2026-10-01",
        }

    def test_openapi_and_assignment_resolution_are_runnable(self) -> None:
        openapi = self.client.get("/openapi.json")
        self.assertEqual(openapi.status_code, 200)
        self.assertIn("/v1/textbooks/resolve", openapi.json()["paths"])

        response = self.client.get(
            "/v1/textbooks/resolve",
            params=self.scope_params(),
            headers={"X-Athena-Principal-Id": "teacher-demo"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assignment"]["assignment_id"], "assignment-1")

    def test_assigned_search_returns_page_dimensions_and_render_url(self) -> None:
        response = self.client.get(
            "/v1/textbooks/assigned-search",
            params={**self.scope_params(), "q": "空气"},
            headers={"X-Athena-Principal-Id": "teacher-demo"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["page"]["width"], 100.0)
        self.assertEqual(result["page"]["height"], 200.0)
        self.assertTrue(result["render_url"].endswith("/pages/1/render"))

        render = self.client.get(result["render_url"])
        self.assertEqual(render.status_code, 200)
        self.assertEqual(render.headers["content-type"], "image/png")

    def test_workspace_pin_is_idempotent_and_searches_the_fixed_textbook(self) -> None:
        payload = {"workspace_id": "workspace-demo", **self.scope_params()}
        headers = {"X-Athena-Principal-Id": "teacher-demo"}

        created = self.client.post("/v1/workspaces", json=payload, headers=headers)
        repeated = self.client.post("/v1/workspaces", json=payload, headers=headers)

        self.assertEqual(created.status_code, 201)
        self.assertFalse(created.json()["reused"])
        self.assertTrue(repeated.json()["reused"])
        self.assertTrue(created.json()["workspace"]["immutable_textbook_pin"])

        with patch.object(main, "assignment_catalog", AssignmentCatalog.disabled()):
            search = self.client.get(
                "/v1/workspaces/workspace-demo/search",
                params={"school_id": "school-demo", "q": "\u7a7a\u6c14"},
                headers=headers,
            )

        self.assertEqual(search.status_code, 200)
        result = search.json()["results"][0]
        self.assertIn("/v1/workspaces/workspace-demo/pages/1/render", result["render_url"])
        self.assertNotIn("/v1/textbooks/", result["render_url"])
        render = self.client.get(result["render_url"], headers=headers)
        self.assertEqual(render.status_code, 200)
        self.assertEqual(render.headers["content-type"], "image/png")

        unauthorized = self.client.get(
            "/v1/workspaces/workspace-demo/search",
            params={"school_id": "school-demo", "q": "\u7a7a\u6c14"},
            headers={"X-Athena-Principal-Id": "teacher-outside-scope"},
        )
        self.assertEqual(unauthorized.status_code, 403)

    def test_unauthorized_principal_is_explicitly_rejected(self) -> None:
        response = self.client.get(
            "/v1/textbooks/resolve",
            params=self.scope_params(),
            headers={"X-Athena-Principal-Id": "teacher-outside-scope"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
