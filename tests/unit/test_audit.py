from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "audit" / "src"))

from athena_audit import AuditEvent, AuditResult  # noqa: E402


class AuditEventTests(unittest.TestCase):
    def test_rejects_hidden_reasoning_or_secrets(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            AuditEvent(
                tenant_id="school-1",
                subject_id="teacher-1",
                action="workspace.generate",
                resource_type="workspace",
                resource_id="workspace-1",
                result=AuditResult.ALLOWED,
                request_id="req-1",
                details={"chain_of_thought": "must not be stored"},
            )


if __name__ == "__main__":
    unittest.main()
