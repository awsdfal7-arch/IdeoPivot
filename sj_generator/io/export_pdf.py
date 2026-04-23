from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from sj_generator.io.export_md import export_questions_to_markdown
from sj_generator.models import Question


def _is_pdf_option_line(text: str) -> bool:
    return bool(re.match(r"^\s*(?:[A-D][\.、．:：]|[\u2460-\u2473][\.、．:：]?)\s*", text))


def _prepare_markdown_for_pdf(text: str) -> str:
    # Prevent question numbers like "1. xxx" from being parsed as ordered lists,
    # otherwise QTextDocument may inject extra numbering before option lines.
    escaped = re.sub(r"(?m)^(\s*)(\d+)\.(\s+)", r"\1\2\\.\3", text)
    lines = escaped.splitlines()
    normalized_lines: list[str] = []
    in_answer_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## 答案与解析":
            in_answer_section = True
            normalized_lines.append(line)
            continue
        if (not in_answer_section) and _is_pdf_option_line(line):
            normalized_lines.append(f"\u3000{line}")
            continue
        normalized_lines.append(line)
    return "\n".join(f"{line}  " if line.strip() else "" for line in normalized_lines)


def export_questions_to_pdf(
    *,
    excel_file_name: str,
    export_date: date,
    questions: list[Question],
    target_path: Path,
    convertible_multi_mode: str = "keep_combo",
    include_answers: bool = True,
    include_analysis: bool = True,
) -> None:
    from PyQt6.QtCore import QSizeF
    from PyQt6.QtGui import QPageSize, QPdfWriter, QTextDocument

    markdown_text = export_questions_to_markdown(
        excel_file_name=excel_file_name,
        export_date=export_date,
        questions=questions,
        convertible_multi_mode=convertible_multi_mode,
        include_answers=include_answers,
        include_analysis=include_analysis,
    )

    target_path.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(target_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(96)

    doc = QTextDocument()
    doc.setDocumentMargin(36)
    if hasattr(doc, "setMarkdown"):
        # QTextDocument treats single newlines in Markdown as soft wraps.
        # Force hard breaks so option lines and analysis lines keep their row layout in PDF.
        doc.setMarkdown(_prepare_markdown_for_pdf(markdown_text))
    else:
        doc.setPlainText(markdown_text)
    page_size = writer.pageLayout().paintRectPixels(writer.resolution()).size()
    doc.setPageSize(QSizeF(page_size))
    doc.print(writer)
