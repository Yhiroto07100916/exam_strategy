from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

import fitz
import pytesseract
from PIL import Image


ALIASES = {
    "国語": ("国語", "現代文", "古文"),
    "数学": ("数学", "算数"),
    "英語": ("英語", "英文"),
    "理科": ("理科", "理科①", "理科②"),
    "社会": ("社会", "地理", "歴史", "公民"),
}
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 20


def parse_ocr_candidates(page_texts: list[str]) -> list[dict[str, Any]]:
    candidates = []
    for page_number, content in enumerate(page_texts, start=1):
        for line_number, line in enumerate(content.splitlines(), start=1):
            normalized = line.replace("：", ":").replace("／", "/").strip()
            if not normalized:
                continue
            numbers = re.findall(r"(?<!\d)(\d{1,3})(?:\s*/\s*(\d{1,3}))?", normalized)
            if not numbers:
                continue
            for subject, aliases in ALIASES.items():
                if not any(alias in normalized for alias in aliases):
                    continue
                score = int(numbers[-1][0])
                maximum = int(numbers[-1][1]) if numbers[-1][1] else 100
                if maximum <= 0 or score > maximum:
                    continue
                candidates.append({
                    "page": page_number,
                    "line": line_number,
                    "subject": subject,
                    "score_candidate": score,
                    "max_score_candidate": maximum,
                    "ocr_text": normalized,
                })
                break
    return candidates


def preview_pdf_ocr(content: bytes) -> dict[str, Any]:
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("PDFは20MB以下のファイルを選択してください")
    binary = shutil.which("tesseract")
    if not binary:
        raise RuntimeError(
            "Tesseractが見つかりません。macOSでは brew install tesseract tesseract-lang を実行してください。"
        )
    try:
        languages = subprocess.run(
            [binary, "--list-langs"], capture_output=True, text=True,
            check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Tesseractを起動できませんでした") from error
    if "jpn" not in (languages.stdout + languages.stderr):
        raise RuntimeError(
            "日本語OCRデータがありません。brew install tesseract-lang を確認してください。"
        )

    try:
        document = fitz.open(stream=content, filetype="pdf")
        if len(document) > MAX_PDF_PAGES:
            raise ValueError("OCRできるPDFは20ページまでです")
        texts = []
        for page in document:
            bounds = page.rect
            scale = min(2.0, 5000 / max(bounds.width, bounds.height))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            texts.append(
                pytesseract.image_to_string(image, lang="jpn+eng", timeout=30)
            )
        document.close()
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDFを画像として読み込めません") from error

    return {
        "pages": len(texts),
        "text": "\n\n".join(
            f"--- {index + 1}ページ ---\n{text}" for index, text in enumerate(texts)
        ),
        "candidates": parse_ocr_candidates(texts),
        "requires_manual_confirmation": True,
    }
