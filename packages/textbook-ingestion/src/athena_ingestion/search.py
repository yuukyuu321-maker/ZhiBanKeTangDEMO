"""Deterministic local search over server-produced evidence anchors."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


_ALNUM = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]+")


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(_ALNUM.findall(lowered))
    normalized = "".join(lowered.split())
    for segment in _CJK.findall(normalized):
        tokens.update(segment[index : index + 2] for index in range(max(0, len(segment) - 1)))
        if len(segment) == 1:
            tokens.add(segment)
    return {token for token in tokens if token}


@dataclass(frozen=True, slots=True)
class SearchResult:
    score: float
    evidence: dict[str, Any]


class EvidenceIndex:
    def __init__(self, evidence: list[dict[str, Any]]) -> None:
        self._records = tuple(evidence)
        self._tokens = tuple(_tokens(str(record.get("quote", ""))) for record in evidence)

    @classmethod
    def from_bundle(cls, bundle_path: Path) -> "EvidenceIndex":
        evidence_path = bundle_path.resolve(strict=True) / "evidence.jsonl"
        records: list[dict[str, Any]] = []
        with evidence_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not record.get("evidence_id"):
                    raise ValueError(f"invalid evidence record at line {line_number}")
                records.append(record)
        return cls(records)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query must not be blank")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        query_compact = "".join(query.lower().split())
        query_tokens = _tokens(query)
        if not query_tokens:
            raise ValueError("query does not contain searchable terms")

        ranked: list[SearchResult] = []
        for record, tokens in zip(self._records, self._tokens, strict=True):
            overlap = query_tokens & tokens
            if not overlap:
                continue
            quote_compact = "".join(str(record.get("quote", "")).lower().split())
            phrase_bonus = 4.0 if query_compact in quote_compact else 0.0
            coverage = len(overlap) / len(query_tokens)
            precision = len(overlap) / max(1, len(tokens))
            score = round(phrase_bonus + coverage * 3.0 + precision, 6)
            ranked.append(SearchResult(score=score, evidence=record))
        ranked.sort(
            key=lambda result: (
                -result.score,
                int(result.evidence.get("pdf_page_index", 0)),
                str(result.evidence.get("evidence_id", "")),
            )
        )
        return ranked[:limit]
