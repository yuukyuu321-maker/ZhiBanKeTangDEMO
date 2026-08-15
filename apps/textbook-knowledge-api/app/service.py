"""Safe access to local textbook import bundles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from athena_ingestion import EvidenceIndex
from athena_ingestion.storage import read_json

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_READABLE_STATUSES = {"approved", "active"}


class BundleNotFoundError(LookupError):
    pass


class BundleNotReadableError(PermissionError):
    pass


class BundleCatalog:
    def __init__(self, import_root: Path, allow_needs_review: bool = False) -> None:
        self._root = import_root.resolve()
        self._allow_needs_review = allow_needs_review

    def _bundle(self, edition_id: str, source_sha256: str) -> Path:
        if not _SAFE_ID.fullmatch(edition_id):
            raise ValueError("invalid edition_id")
        digest = source_sha256.lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError("invalid source_sha256")
        candidate = self._root / edition_id / digest
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise BundleNotFoundError("textbook import bundle was not found") from error
        if not resolved.is_relative_to(self._root):
            raise ValueError("bundle path escapes the configured import root")
        return resolved

    def _readable_bundle(self, edition_id: str, source_sha256: str) -> tuple[Path, dict[str, Any]]:
        bundle = self._bundle(edition_id, source_sha256)
        manifest = read_json(bundle / "manifest.json")
        status = str(manifest.get("status", ""))
        readable = status in _READABLE_STATUSES or (
            self._allow_needs_review and status == "needs_review"
        )
        if not readable:
            raise BundleNotReadableError(f"textbook import status is not readable: {status}")
        source = manifest.get("source", {})
        if not isinstance(source, dict) or source.get("sha256") != source_sha256.lower():
            raise ValueError("manifest digest does not match requested source")
        return bundle, manifest

    def describe(self, edition_id: str, source_sha256: str) -> dict[str, Any]:
        bundle, manifest = self._readable_bundle(edition_id, source_sha256)
        return {"manifest": manifest, "report": read_json(bundle / "import-report.json")}

    def pages(
        self, edition_id: str, source_sha256: str, *, offset: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset or limit is out of range")
        bundle, _ = self._readable_bundle(edition_id, source_sha256)
        records: list[dict[str, Any]] = []
        with (bundle / "pages.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("page record must be an object")
                    records.append(record)
        return records[offset : offset + limit]

    def page(
        self, edition_id: str, source_sha256: str, pdf_page_index: int
    ) -> dict[str, Any]:
        if pdf_page_index < 1:
            raise ValueError("pdf_page_index must be positive")
        pages = self.pages(
            edition_id, source_sha256, offset=pdf_page_index - 1, limit=1
        )
        if not pages or pages[0].get("pdf_page_index") != pdf_page_index:
            raise BundleNotFoundError("page was not found")
        return pages[0]

    def search(
        self, edition_id: str, source_sha256: str, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        bundle, _ = self._readable_bundle(edition_id, source_sha256)
        return [
            {"score": result.score, "evidence": result.evidence}
            for result in EvidenceIndex.from_bundle(bundle).search(query, limit)
        ]

    def render_path(self, edition_id: str, source_sha256: str, pdf_page_index: int) -> Path:
        if pdf_page_index < 1:
            raise ValueError("pdf_page_index must be positive")
        bundle, _ = self._readable_bundle(edition_id, source_sha256)
        render_uri = self.page(edition_id, source_sha256, pdf_page_index).get("render_uri")
        if not isinstance(render_uri, str) or not render_uri:
            raise BundleNotFoundError("page render is unavailable")
        render = (bundle / render_uri).resolve(strict=True)
        if not render.is_relative_to(bundle) or render.suffix.lower() != ".png":
            raise ValueError("invalid page render reference")
        return render
