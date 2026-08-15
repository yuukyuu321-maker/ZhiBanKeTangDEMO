"""Vendor-neutral model gateway primitives for deterministic local testing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ModelStatus(StrEnum):
    COMPLETED = "completed"
    CANNOT_CONFIRM = "cannot_confirm"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    request_id: str
    task: str
    instruction: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    status: ModelStatus
    content: str
    evidence_ids: tuple[str, ...]
    adapter: str


class ModelGateway(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class DeterministicModelGateway:
    """Offline adapter that never invents content beyond supplied evidence identifiers."""

    adapter_name = "deterministic-test"

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not request.evidence_ids:
            return ModelResponse(
                status=ModelStatus.CANNOT_CONFIRM,
                content="当前教材中没有足够证据，无法确认。",
                evidence_ids=(),
                adapter=self.adapter_name,
            )

        return ModelResponse(
            status=ModelStatus.COMPLETED,
            content=f"教学草稿：{request.instruction.strip()}",
            evidence_ids=request.evidence_ids,
            adapter=self.adapter_name,
        )
