"""Minimal append-only audit event shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4


class AuditResult(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    tenant_id: str
    subject_id: str
    action: str
    resource_type: str
    resource_id: str
    result: AuditResult
    request_id: str
    details: Mapping[str, str] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        forbidden = {"password", "token", "secret", "chain_of_thought"}
        if forbidden.intersection(key.lower() for key in self.details):
            raise ValueError("audit details contain a forbidden sensitive field")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
