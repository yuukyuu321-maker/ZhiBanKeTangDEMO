"""Build a side-by-side PDF packet for non-mutating textbook import review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageOps, ImageStat
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_EMBEDDED_FONT = "AthenaReviewCJK"
_CID_FALLBACK_FONT = "STSong-Light"
_PAGE_SIZE = landscape(A3)


def _review_font_candidates() -> list[Path]:
    candidates: list[Path] = []
    windows_directory = os.environ.get("WINDIR")
    if windows_directory:
        candidates.extend(
            [
                Path(windows_directory) / "Fonts" / "simhei.ttf",
                Path(windows_directory) / "Fonts" / "msyh.ttc",
                Path(windows_directory) / "Fonts" / "simsun.ttc",
            ]
        )
    candidates.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        ]
    )
    return candidates


def _register_review_font() -> str:
    for candidate in _review_font_candidates():
        if not candidate.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(_EMBEDDED_FONT, str(candidate), subfontIndex=0))
        except (OSError, ValueError):
            continue
        return _EMBEDDED_FONT
    pdfmetrics.registerFont(UnicodeCIDFont(_CID_FALLBACK_FONT))
    return _CID_FALLBACK_FONT


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_plan(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("review plan must be a JSON object")
    if value.get("schema_version") != "athena.textbook-review-plan.v1":
        raise ValueError("unsupported review plan schema")
    return value


def _fit(width: float, height: float, box_width: float, box_height: float) -> tuple[float, float]:
    scale = min(box_width / width, box_height / height)
    return width * scale, height * scale


def _render_reference_pages(
    source_pdf: Path,
    selected_pages: list[dict[str, Any]],
    output_directory: Path,
) -> dict[int, Path]:
    document = pdfium.PdfDocument(str(source_pdf))
    references: dict[int, Path] = {}
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        for item in selected_pages:
            page_index = int(item["pdf_page_index"])
            if page_index < 1 or page_index > len(document):
                raise ValueError(f"selected PDF page is out of range: {page_index}")
            target = output_directory / f"page-{page_index:04d}.png"
            page = document[page_index - 1]
            try:
                bitmap = page.render(scale=2.0)
                image = bitmap.to_pil()
                image.save(target, "PNG")
            finally:
                page.close()
            references[page_index] = target
    finally:
        document.close()
    return references


def _draw_image_in_box(
    document: canvas.Canvas,
    path: Path,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    with Image.open(path) as image:
        image_width, image_height = image.size
    draw_width, draw_height = _fit(image_width, image_height, width, height)
    draw_x = x + (width - draw_width) / 2
    draw_y = y + (height - draw_height) / 2
    document.setStrokeColorRGB(0.75, 0.75, 0.75)
    document.rect(x, y, width, height)
    document.drawImage(
        ImageReader(str(path)),
        draw_x,
        draw_y,
        width=draw_width,
        height=draw_height,
        preserveAspectRatio=True,
        mask="auto",
    )


def _normalized_image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    return ImageOps.pad(image, (512, 512), color="white")


def _pixel_difference(first: Path, second: Path) -> float:
    difference = ImageChops.difference(
        _normalized_image(first),
        _normalized_image(second),
    )
    return sum(ImageStat.Stat(difference).mean) / 3


def _difference_label(value: float) -> str:
    if value >= 15:
        return "高差异（必须人工确认）"
    if value >= 8:
        return "中差异（建议重点查看）"
    return "低差异"


def _draw_checkbox(
    document: canvas.Canvas,
    x: float,
    y: float,
    label: str,
    font_name: str,
) -> None:
    document.setLineWidth(1)
    document.rect(x, y - 2, 10, 10)
    document.setFont(font_name, 11)
    document.drawString(x + 15, y, label)


def _build_pdf(
    output_path: Path,
    bundle: Path,
    plan: dict[str, Any],
    references: dict[int, Path],
) -> None:
    font_name = _register_review_font()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = _PAGE_SIZE
    document = canvas.Canvas(
        str(output_path),
        pagesize=_PAGE_SIZE,
        pageCompression=1,
    )
    document.setTitle("Project Athena 教材导入人工复核包")
    document.setAuthor("Project Athena")

    edition = plan["edition"]
    summary = plan["summary"]
    import_pipeline = plan.get("import_pipeline", {})
    document.setFont(font_name, 24)
    document.drawString(55, height - 70, "Project Athena 教材导入人工复核包")
    document.setFont(font_name, 14)
    textbook_label = " ".join(
        str(edition.get(key, "")) for key in ("publisher", "grade", "subject", "volume")
    ).strip()
    metadata = [
        f"教材：{textbook_label}",
        f"版本：{edition.get('edition_label', '')}",
        f"导入管线：{import_pipeline.get('version', 'unknown')}",
        f"源文件 SHA-256：{plan['source_sha256']}",
        f"状态：{plan['bundle_status']}（本复核包不会改变教材状态）",
        (
            f"抽样：总页数 {summary['page_count']}；警告页 "
            f"{summary['warning_page_count']}；抽查页 {summary['selected_page_count']}"
        ),
    ]
    y = height - 120
    for line in metadata:
        document.drawString(55, y, line)
        y -= 30

    document.setFont(font_name, 13)
    instructions = [
        "复核方法：每个抽样页左侧为导入管线页图，右侧为从原始 PDF 用 PDFium 独立渲染的对照页。",
        "逐页确认文字、公式、图片、页码和裁切一致；警告不等于错误，但必须人工查看。",
        "发现异常时记录 PDF 页序号和问题。请勿在完成复核前把教材标记为 approved 或 active。",
        "自动像素差异仅用于排序复核优先级，不能替代人工判断。",
        "本文件是人工检查辅助材料，不构成批准决定，也不会写入教材导入包。",
    ]
    y -= 20
    for line in instructions:
        document.drawString(55, y, line)
        y -= 28

    selected = ", ".join(str(item["pdf_page_index"]) for item in plan["selected_pages"])
    document.setFont(font_name, 11)
    document.drawString(55, y - 10, f"抽样 PDF 页序号：{selected}")
    document.showPage()

    box_margin = 45
    gap = 30
    box_width = (width - box_margin * 2 - gap) / 2
    box_height = height - 245
    box_y = 95
    for item in plan["selected_pages"]:
        page_index = int(item["pdf_page_index"])
        imported_relative = Path(str(item["render_uri"]))
        imported_path = (bundle / imported_relative).resolve(strict=True)
        if not imported_path.is_relative_to(bundle):
            raise ValueError(f"import render escapes bundle: {imported_relative}")
        reference_path = references[page_index]

        document.setFont(font_name, 17)
        difference = _pixel_difference(imported_path, reference_path)
        difference_label = _difference_label(difference)
        document.drawString(
            box_margin,
            height - 42,
            (
                f"PDF 第 {page_index} 页｜标签 {item.get('page_label')}｜"
                f"印刷页 {item.get('printed_page') or '无'}"
            ),
        )
        document.setFont(font_name, 11)
        categories = "、".join(item.get("categories", [])) or "未分类"
        warnings = "、".join(item.get("warning_signatures", [])) or "无"
        document.drawString(box_margin, height - 65, f"类别：{categories}")
        document.drawString(box_margin, height - 83, f"警告：{warnings}")
        if difference_label.startswith("高"):
            document.setFillColorRGB(0.75, 0.05, 0.05)
        else:
            document.setFillColorRGB(0.1, 0.1, 0.1)
        document.drawString(
            box_margin,
            height - 101,
            f"自动差异：{difference:.2f} / 255｜{difference_label}",
        )
        document.setFillColorRGB(0, 0, 0)
        document.setFont(font_name, 13)
        document.drawCentredString(
            box_margin + box_width / 2,
            height - 128,
            "导入管线页图",
        )
        document.drawCentredString(
            box_margin + box_width + gap + box_width / 2,
            height - 128,
            "原始 PDF 独立渲染",
        )
        _draw_image_in_box(
            document,
            imported_path,
            x=box_margin,
            y=box_y,
            width=box_width,
            height=box_height,
        )
        _draw_image_in_box(
            document,
            reference_path,
            x=box_margin + box_width + gap,
            y=box_y,
            width=box_width,
            height=box_height,
        )
        _draw_checkbox(document, box_margin, 64, "两侧内容一致", font_name)
        _draw_checkbox(
            document,
            box_margin + 175,
            64,
            "文字/公式/图片可辨认",
            font_name,
        )
        _draw_checkbox(
            document,
            box_margin + 405,
            64,
            "无裁切/错位/异常空白",
            font_name,
        )
        _draw_checkbox(
            document,
            box_margin + 650,
            64,
            "发现问题（另行记录）",
            font_name,
        )
        document.setFont(font_name, 9)
        document.drawRightString(
            width - box_margin,
            25,
            "仅供本地人工复核｜教材状态保持 needs_review",
        )
        document.showPage()

    document.save()


def build_review_packet(
    source_pdf: Path,
    bundle_path: Path,
    plan_path: Path,
    output_path: Path,
    reference_directory: Path,
) -> Path:
    source = source_pdf.resolve(strict=True)
    bundle = bundle_path.resolve(strict=True)
    plan = _load_plan(plan_path.resolve(strict=True))
    source_digest = _sha256_file(source)
    if source_digest != plan.get("source_sha256"):
        raise ValueError("source PDF checksum does not match the review plan")
    if plan.get("bundle_status") != "needs_review":
        raise ValueError("review packet requires a needs_review plan")

    selected_pages = plan.get("selected_pages")
    if not isinstance(selected_pages, list) or not selected_pages:
        raise ValueError("review plan has no selected pages")
    references = _render_reference_pages(source, selected_pages, reference_directory.resolve())
    output = output_path.resolve()
    _build_pdf(output, bundle, plan, references)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-textbook-review-packet")
    parser.add_argument("--source-pdf", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    output = build_review_packet(
        arguments.source_pdf,
        arguments.bundle,
        arguments.plan,
        arguments.output,
        arguments.reference_dir,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
