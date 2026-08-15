"""Poppler-backed page renderer with per-page failure isolation."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import RenderMode


@dataclass(frozen=True, slots=True)
class RenderResult:
    page_uris: dict[int, str]
    page_warnings: dict[int, tuple[str, ...]]
    warnings: tuple[str, ...]


def _renderer_path() -> str | None:
    renderer = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm")
    if renderer is None:
        return None
    path = Path(renderer)
    if path.suffix.lower() not in {".cmd", ".bat"}:
        return renderer
    dependency_root = path.parents[2] if len(path.parents) > 2 else None
    if dependency_root is not None:
        native = dependency_root / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
        if native.is_file():
            return str(native)
    return renderer


def render_pdf(
    pdf_path: Path,
    output_directory: Path,
    page_count: int,
    mode: RenderMode,
    dpi: int = 110,
) -> RenderResult:
    if mode == RenderMode.NONE:
        return RenderResult({}, {}, ("rendering_skipped",))
    renderer = _renderer_path()
    if renderer is None:
        return RenderResult({}, {}, ("pdftoppm_not_available",))

    output_directory.mkdir(parents=True, exist_ok=True)
    page_uris: dict[int, str] = {}
    page_warnings: dict[int, tuple[str, ...]] = {}
    failure_count = 0
    with tempfile.TemporaryDirectory(prefix="athena-render-") as scratch_directory:
        scratch = Path(scratch_directory)
        for index in range(1, page_count + 1):
            prefix = scratch / f"page-{index:04d}"
            completed = subprocess.run(
                [
                    renderer,
                    "-png",
                    "-cropbox",
                    "-r",
                    str(dpi),
                    "-f",
                    str(index),
                    "-l",
                    str(index),
                    "-singlefile",
                    str(pdf_path),
                    str(prefix),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            warnings: list[str] = []
            rendered = prefix.with_suffix(".png")
            if completed.returncode != 0:
                warnings.append(f"renderer_exit_code_{completed.returncode}")
            if completed.stderr.strip():
                compact = " ".join(completed.stderr.split())
                warnings.append(f"renderer_warning:{compact[:500]}")
            if rendered.is_file():
                final_output = output_directory / rendered.name
                shutil.move(str(rendered), final_output)
                page_uris[index] = final_output.relative_to(output_directory.parent).as_posix()
            else:
                warnings.append("page_render_missing")
                failure_count += 1
            if warnings:
                page_warnings[index] = tuple(warnings)

    summary: list[str] = []
    if page_warnings:
        summary.append(f"renderer_page_warning_count:{len(page_warnings)}")
    if failure_count:
        summary.append(f"renderer_page_failure_count:{failure_count}")
    if len(page_uris) != page_count:
        summary.append(f"rendered_page_count_mismatch:{len(page_uris)}/{page_count}")
    return RenderResult(page_uris, page_warnings, tuple(summary))
