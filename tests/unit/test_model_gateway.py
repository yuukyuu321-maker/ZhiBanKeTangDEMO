from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "model-gateway" / "src"))

from athena_model_gateway import (  # noqa: E402
    DeterministicModelGateway,
    ModelRequest,
    ModelStatus,
)


class DeterministicGatewayTests(unittest.TestCase):
    def test_refuses_to_confirm_without_textbook_evidence(self) -> None:
        response = DeterministicModelGateway().generate(
            ModelRequest(
                request_id="req-1",
                task="lesson_plan",
                instruction="生成教案",
                evidence_ids=(),
            )
        )
        self.assertEqual(response.status, ModelStatus.CANNOT_CONFIRM)
        self.assertEqual(response.evidence_ids, ())

    def test_returns_only_supplied_evidence_identifiers(self) -> None:
        response = DeterministicModelGateway().generate(
            ModelRequest(
                request_id="req-2",
                task="lesson_plan",
                instruction="生成合成教案",
                evidence_ids=("ev-1",),
            )
        )
        self.assertEqual(response.status, ModelStatus.COMPLETED)
        self.assertEqual(response.evidence_ids, ("ev-1",))


if __name__ == "__main__":
    unittest.main()
