"""Deterministic, non-mutating sampling plans for textbook import review."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .review import REQUIRED_REVIEW_CATEGORIES
from .storage import read_json, write_json

PLAN_SCHEMA_VERSION = "athena.textbook-review-plan.v1"
SAMPLING_POLICY_VERSION = "warning-strata-v1"
_CHAPTER = re.compile(r"第\s*[一二三四五六七八九十百0-9]+\s*章")
_MATH = re.compile(r"[=≈≠≤≥√∑∫±×÷]|\b(?:sin|cos|tan)\b", re.IGNORECASE)


def warning_signature(warning: str) -> str:
    """Collapse verbose renderer messages into stable review strata."""

    normalized = warning.strip()
    if normalized == "no_extractable_text":
        return "no_extractable_text"
    if normalized.startswith("renderer_warning:"):
        lowered = normalized.lower()
        if "malformed jp2" in lowered or "jpeg 2000" in lowered:
            return "renderer_malformed_jp2"
        if "font" in lowered:
            return "renderer_font_warning"
        return "renderer_warning"
    return normalized.split(":", 1)[0] or "unknown_warning"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON objects in {path}")
            records.append(value)
    return records


def _page_text(evidence: list[dict[str, Any]]) -> dict[int, str]:
    quotes: dict[int, list[str]] = defaultdict(list)
    for item in evidence:
        quotes[int(item["pdf_page_index"])].append(str(item.get("quote", "")))
    return {page: "\n".join(values) for page, values in quotes.items()}


def _categories(
    page: dict[str, Any],
    text: str,
    *,
    page_count: int,
) -> tuple[str, ...]:
    index = int(page["pdf_page_index"])
    categories: set[str] = set()
    if index <= 2 or index == page_count:
        categories.add("cover")
    if "目录" in text or (index <= 12 and len(_CHAPTER.findall(text)) >= 2):
        categories.add("contents")
    if _CHAPTER.search(text):
        categories.add("chapter_start")
    if any(token in text for token in ("实验", "探究", "活动")):
        categories.add("experiment")
    if index > page_count - 5 or any(token in text for token in ("附录", "元素周期表")):
        categories.add("appendix")
    if (
        int(page.get("image_count", 0)) > 0
        or int(page.get("vector_element_count", 0)) >= 50
        or _MATH.search(text)
    ):
        categories.add("formula_or_figure")
    if not {"cover", "contents", "appendix"}.intersection(categories):
        categories.add("body")
    return tuple(sorted(categories))


def _pick_positions(values: list[int], positions: tuple[str, ...]) -> list[tuple[int, str]]:
    if not values:
        return []
    indexes = {
        "first": 0,
        "middle": len(values) // 2,
        "last": len(values) - 1,
    }
    picked: list[tuple[int, str]] = []
    seen: set[int] = set()
    for position in positions:
        page = values[indexes[position]]
        if page not in seen:
            picked.append((page, position))
            seen.add(page)
    return picked


def _evenly_spaced(values: list[int], count: int) -> list[int]:
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return values
    if count == 1:
        return [values[len(values) // 2]]
    return [values[round(index * (len(values) - 1) / (count - 1))] for index in range(count)]


def build_review_plan(
    bundle_path: Path,
    *,
    minimum_warning_pages: int = 20,
    warning_ratio: float = 0.10,
) -> dict[str, Any]:
    """Build a reproducible review plan without writing to the import bundle."""

    if minimum_warning_pages < 1:
        raise ValueError("minimum_warning_pages must be positive")
    if not 0 < warning_ratio <= 1:
        raise ValueError("warning_ratio must be in (0, 1]")

    bundle = bundle_path.resolve(strict=True)
    manifest = read_json(bundle / "manifest.json")
    report = read_json(bundle / "import-report.json")
    pages = _read_jsonl(bundle / "pages.jsonl")
    evidence = _read_jsonl(bundle / "evidence.jsonl")
    if not pages:
        raise ValueError("review bundle has no pages")
    if manifest.get("status") != "needs_review":
        raise ValueError("review plans are only generated for needs_review bundles")

    source = manifest.get("source")
    edition = manifest.get("edition")
    if not isinstance(source, dict) or not isinstance(edition, dict):
        raise ValueError("manifest source and edition metadata are required")
    import_pipeline = manifest.get("import_pipeline")
    if not isinstance(import_pipeline, dict):
        import_pipeline = {
            "name": "athena-textbook-ingestion",
            "version": "legacy-unknown",
        }
    source_sha256 = str(source.get("sha256", ""))
    if source_sha256 != str(report.get("source_sha256", "")):
        raise ValueError("manifest and import report source hashes do not match")

    page_count = len(pages)
    by_index = {int(page["pdf_page_index"]): page for page in pages}
    if sorted(by_index) != list(range(1, page_count + 1)):
        raise ValueError("pages must use contiguous one-based PDF indexes")

    text_by_page = _page_text(evidence)
    categories_by_page = {
        index: _categories(page, text_by_page.get(index, ""), page_count=page_count)
        for index, page in by_index.items()
    }
    signatures_by_page = {
        index: tuple(
            sorted(
                {
                    warning_signature(str(warning))
                    for warning in page.get("warnings", [])
                    if str(warning).strip()
                }
            )
        )
        for index, page in by_index.items()
    }
    warning_pages = [
        index
        for index, page in by_index.items()
        if page.get("quality_status") != "passed" or signatures_by_page[index]
    ]

    reasons: dict[int, set[str]] = defaultdict(set)
    for index, page in by_index.items():
        if int(page.get("text_character_count", 0)) == 0:
            reasons[index].add("mandatory:no_extractable_text")
        if not page.get("render_uri"):
            reasons[index].add("mandatory:missing_render")
    reasons[1].add("boundary:first_page")
    reasons[page_count].add("boundary:last_page")

    for category in sorted(REQUIRED_REVIEW_CATEGORIES):
        candidates = [
            index for index in warning_pages if category in categories_by_page[index]
        ] or [index for index in sorted(by_index) if category in categories_by_page[index]]
        if candidates:
            reasons[candidates[0]].add(f"category:{category}")

    signature_pages: dict[str, list[int]] = defaultdict(list)
    for index in warning_pages:
        for signature in signatures_by_page[index]:
            signature_pages[signature].append(index)
    for signature in sorted(signature_pages):
        for index, position in _pick_positions(
            signature_pages[signature],
            ("first", "middle", "last"),
        ):
            reasons[index].add(f"warning_stratum:{signature}:{position}")

    warning_target = min(
        len(warning_pages),
        max(minimum_warning_pages, math.ceil(len(warning_pages) * warning_ratio)),
    )
    selected_warning_count = sum(index in reasons for index in warning_pages)
    remaining = [index for index in warning_pages if index not in reasons]
    for index in _evenly_spaced(
        remaining,
        max(0, warning_target - selected_warning_count),
    ):
        reasons[index].add("warning_sample:evenly_spaced")

    selected_pages: list[dict[str, Any]] = []
    for index in sorted(reasons):
        page = by_index[index]
        selected_pages.append(
            {
                "pdf_page_index": index,
                "page_label": page.get("page_label"),
                "printed_page": page.get("printed_page"),
                "categories": list(categories_by_page[index]),
                "warning_signatures": list(signatures_by_page[index]),
                "reasons": sorted(reasons[index]),
                "render_uri": page.get("render_uri"),
                "text_character_count": int(page.get("text_character_count", 0)),
                "image_count": int(page.get("image_count", 0)),
                "vector_element_count": int(page.get("vector_element_count", 0)),
            }
        )

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "sampling_policy_version": SAMPLING_POLICY_VERSION,
        "bundle_status": manifest["status"],
        "status_unchanged": True,
        "review_decision_recorded": False,
        "edition": edition,
        "import_pipeline": import_pipeline,
        "source_sha256": source_sha256,
        "summary": {
            "page_count": page_count,
            "warning_page_count": len(warning_pages),
            "warning_sample_target": warning_target,
            "selected_page_count": len(selected_pages),
            "selected_warning_page_count": sum(
                item["pdf_page_index"] in warning_pages for item in selected_pages
            ),
            "mandatory_page_count": sum(
                any(reason.startswith("mandatory:") for reason in item["reasons"])
                for item in selected_pages
            ),
        },
        "required_categories": sorted(REQUIRED_REVIEW_CATEGORIES),
        "warning_signature_counts": {
            signature: len(indexes) for signature, indexes in sorted(signature_pages.items())
        },
        "selected_pages": selected_pages,
    }


def _review_markdown(plan: dict[str, Any]) -> str:
    edition = plan["edition"]
    summary = plan["summary"]
    textbook_label = " ".join(
        str(edition.get(key, "")) for key in ("publisher", "grade", "subject", "volume")
    ).strip()
    sampling_summary = (
        f"- 总页数：{summary['page_count']}；"
        f"警告页：{summary['warning_page_count']}；"
        f"抽查页：{summary['selected_page_count']}"
    )
    lines = [
        "# 教材导入人工复核清单",
        "",
        f"- 教材：{textbook_label}",
        f"- 版本：{edition.get('edition_label', '')}",
        f"- 导入管线：{plan['import_pipeline'].get('version', 'unknown')}",
        f"- 源文件 SHA-256：{plan['source_sha256']}",
        f"- 当前状态：{plan['bundle_status']}（生成本清单不会改变状态）",
        f"- 抽样策略：{plan['sampling_policy_version']}",
        sampling_summary,
        "",
        "## 复核要求",
        "",
        "逐页对比导入页图与 PDF 独立渲染，确认文字、公式、图片、页码和裁切没有缺失或错位。",
        "发现异常时请记录 PDF 页序号、问题类型和简短说明；本清单不代表批准教材。",
        "",
        "## 逐页清单",
        "",
    ]
    for item in plan["selected_pages"]:
        categories = "、".join(item["categories"]) or "未分类"
        warnings = "、".join(item["warning_signatures"]) or "无"
        lines.extend(
            [
                f"### [ ] PDF 第 {item['pdf_page_index']} 页（标签 {item['page_label']}）",
                "",
                f"- 类别：{categories}",
                f"- 警告：{warnings}",
                "- [ ] 导入页图与独立渲染一致",
                "- [ ] 文字、公式、图片和页码可辨认",
                "- [ ] 无缺页、裁切、错位或异常空白",
                "- 问题记录：",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_review_plan(
    bundle_path: Path,
    output_directory: Path,
    *,
    minimum_warning_pages: int = 20,
    warning_ratio: float = 0.10,
) -> dict[str, Any]:
    plan = build_review_plan(
        bundle_path,
        minimum_warning_pages=minimum_warning_pages,
        warning_ratio=warning_ratio,
    )
    output = output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "review-plan.json", plan)
    (output / "review-checklist.md").write_text(
        _review_markdown(plan),
        encoding="utf-8",
        newline="\n",
    )
    return plan
