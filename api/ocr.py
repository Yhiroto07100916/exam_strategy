from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

import fitz
import pytesseract
from PIL import Image


HIGH_SCHOOL_ALIASES = {
    "国語": ("国語", "現代文", "古文"),
    "数学": ("数学", "算数"),
    "英語": ("英語", "英文"),
    "理科": ("理科", "理科①", "理科②"),
    "社会": ("社会", "地理", "歴史", "公民"),
}
UNIVERSITY_ALIASES = {
    "国語": ("国語", "現代文", "古文"),
    "英語": ("英語", "英文"),
    "英語リーディング": ("英語リーディング", "英語Ｒ", "リーディング", "Reading"),
    "英語リスニング": ("英語リスニング", "英語Ｌ", "リスニング", "Listening"),
    "数学IA": ("数学IA", "数学ⅠA", "数学I・A", "数学1A", "数学Ⅰ・Ａ"),
    "数学IIBC": ("数学IIBC", "数学ⅡBC", "数学II・BC", "数学2BC", "数学Ⅱ・ＢＣ"),
    "数学III": ("数学III", "数学Ⅲ", "数学3"),
    "物理": ("物理基礎", "物理"),
    "化学": ("化学基礎", "化学"),
    "生物": ("生物基礎", "生物"),
    "地学": ("地学基礎", "地学"),
    "地理総合・地理探究": ("地理総合・地理探究", "地理総合", "地理探究", "地理"),
    "歴史総合・日本史探究": ("歴史総合・日本史探究", "日本史探究", "歴史総合", "日本史"),
    "歴史総合・世界史探究": ("歴史総合・世界史探究", "世界史探究", "歴史総合", "世界史"),
    "公共・政治経済": ("公共・政治経済", "政治・経済", "政治経済", "公共"),
    "情報I": ("情報I", "情報Ⅰ", "情報１", "情報"),
    "小論文": ("小論文",),
    "面接": ("面接",),
}
ALIASES_BY_MODE = {
    "high_school": HIGH_SCHOOL_ALIASES,
    "university": UNIVERSITY_ALIASES,
}
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 20


def parse_ocr_candidates(
    page_texts: list[str], mode: str = "high_school"
) -> list[dict[str, Any]]:
    aliases_by_subject = ALIASES_BY_MODE.get(mode, HIGH_SCHOOL_ALIASES)
    alias_entries = [
        (alias, subject)
        for subject, aliases in aliases_by_subject.items()
        for alias in aliases
    ]
    candidates = []
    for page_number, content in enumerate(page_texts, start=1):
        for line_number, line in enumerate(content.splitlines(), start=1):
            normalized = line.replace("：", ":").replace("／", "/").strip()
            if not normalized:
                continue

            matches = [
                (normalized.find(alias), -len(alias), alias, subject)
                for alias, subject in alias_entries
                if alias in normalized
            ]
            if not matches:
                continue
            position, _, subject_alias, subject = min(matches)
            subject_text = normalized[position + len(subject_alias):]
            fractions = re.findall(
                r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)",
                subject_text,
            )
            if fractions:
                score = int(fractions[0][0])
                maximum = int(fractions[0][1])
            else:
                standalone_numbers = re.findall(
                    r"(?<!\d)(\d{1,3})(?!\d)", subject_text
                )
                if len(standalone_numbers) != 1:
                    continue
                score = int(standalone_numbers[0])
                maximum = 100

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
    return candidates

def preview_pdf_ocr(content: bytes, mode: str = "high_school") -> dict[str, Any]:
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
    except Exception as error:
        raise ValueError("PDFを画像として読み込めません") from error

    texts = []
    with document:
        if len(document) > MAX_PDF_PAGES:
            raise ValueError("OCRできるPDFは20ページまでです")
        for page in document:
            try:
                bounds = page.rect
                scale = min(2.0, 5000 / max(bounds.width, bounds.height))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            except Exception as error:
                raise ValueError("PDFを画像として読み込めません") from error
            try:
                texts.append(
                    pytesseract.image_to_string(image, lang="jpn+eng", timeout=30)
                )
            except RuntimeError as error:
                raise RuntimeError(
                    "OCR処理がタイムアウトしました。ページ数を減らして再試行してください。"
                ) from error
            except pytesseract.TesseractError as error:
                raise RuntimeError(
                    "TesseractでOCRを実行できませんでした。日本語データとインストール状態を確認してください。"
                ) from error

    return {
        "pages": len(texts),
        "text": "\n\n".join(
            f"--- {index + 1}ページ ---\n{text}" for index, text in enumerate(texts)
        ),
        "candidates": parse_ocr_candidates(texts, mode=mode),
        "requires_manual_confirmation": True,
    }
