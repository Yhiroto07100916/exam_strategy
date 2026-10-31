from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SCORES = DATA / "scores.csv"
SUBJECTS = ["国語", "数学", "英語", "理科", "社会"]
ALIASES = {
    "国語": ["国語", "現代文", "古文"],
    "数学": ["数学", "算数"],
    "英語": ["英語", "英文"],
    "理科": ["理科", "理科①", "理科②"],
    "社会": ["社会", "地理", "歴史", "公民"],
}

def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSVの文字コードを読み取れませんでした。")

def normalize_scores(path: Path, exam_name: str | None, exam_date: str | None) -> pd.DataFrame:
    df = read_table(path)
    lookup = {str(c).strip().lower(): c for c in df.columns}
    def find(*names):
        for name in names:
            if name.lower() in lookup:
                return lookup[name.lower()]
        return None

    subject_col = find("subject", "科目", "教科")
    score_col = find("score", "得点", "点数", "素点")
    max_col = find("max_score", "満点", "配点")
    if not subject_col or not score_col:
        raise ValueError("科目/教科 と 得点/点数 の列が必要です。")
    date_col = find("date", "日付", "実施日")
    name_col = find("exam_name", "模試名", "試験名", "テスト名")
    type_col = find("exam_type", "種別", "試験種別")
    dev_col = find("deviation", "偏差値")
    rank_col = find("rank", "順位")
    examinees_col = find("examinees", "受験者数")
    out = pd.DataFrame()
    out["date"] = df[date_col] if date_col else (exam_date or date.today().isoformat())
    out["exam_name"] = df[name_col] if name_col else (exam_name or path.stem)
    out["exam_type"] = df[type_col] if type_col else "模試"
    out["subject"] = df[subject_col].astype(str).str.strip()
    out["score"] = pd.to_numeric(df[score_col], errors="coerce")
    out["max_score"] = pd.to_numeric(df[max_col], errors="coerce") if max_col else 100
    out["deviation"] = pd.to_numeric(df[dev_col], errors="coerce") if dev_col else None
    out["rank"] = pd.to_numeric(df[rank_col], errors="coerce") if rank_col else None
    out["examinees"] = pd.to_numeric(df[examinees_col], errors="coerce") if examinees_col else None
    out = out.dropna(subset=["score", "max_score"])
    if out.empty:
        raise ValueError("有効な得点データがありません。")
    if ((out["score"] < 0) | (out["max_score"] <= 0) | (out["score"] > out["max_score"])).any():
        raise ValueError("得点または満点が不正です。")
    return out[["date", "exam_name", "exam_type", "subject", "score", "max_score", "deviation", "rank", "examinees"]]

def merge_scores(new: pd.DataFrame, destination: Path = SCORES) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        old = read_table(destination)
        combined = pd.concat([old, new], ignore_index=True)
    else:
        combined = new.copy()
    before = len(combined)
    key = ["date", "exam_name", "exam_type", "subject", "score", "max_score"]
    combined = combined.drop_duplicates(subset=key, keep="last")
    combined.to_csv(destination, index=False, encoding="utf-8-sig")
    return len(combined) - (before - len(new))

def ocr_file(path: Path, output_dir: Path) -> tuple[Path, Path]:
    if not shutil.which("tesseract"):
        raise RuntimeError(
            "Tesseractが見つかりません。macOSなら `brew install tesseract tesseract-lang` を実行してください。"
        )
    lang_check = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    langs = lang_check.stdout + lang_check.stderr
    if "jpn" not in langs:
        raise RuntimeError("日本語OCRデータ(jpn)がありません。`brew install tesseract-lang` を確認してください。")

    import pytesseract
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[tuple[str, str]] = []
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF画像化にはPyMuPDFが必要です。`pip install pymupdf` を実行してください。") from exc
        doc = fitz.open(path)
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pages.append((f"ページ{idx}", pytesseract.image_to_string(img, lang="jpn+eng")))
    else:
        img = Image.open(path).convert("RGB")
        pages.append(("画像", pytesseract.image_to_string(img, lang="jpn+eng")))

    raw_path = output_dir / f"{path.stem}_ocr.txt"
    raw_path.write_text("\n\n".join(f"--- {label} ---\n{text}" for label, text in pages), encoding="utf-8")
    candidates = []
    for label, content in pages:
        for line_no, line in enumerate(content.splitlines(), start=1):
            normalized = line.replace("：", ":").replace("／", "/").strip()
            if not normalized:
                continue
            for subject, aliases in ALIASES.items():
                if not any(a in normalized for a in aliases):
                    continue
                nums = re.findall(r"(?<!\d)(\d{1,3})(?:\s*/\s*(\d{1,3}))?", normalized)
                if not nums:
                    continue
                score = int(nums[-1][0])
                max_score = int(nums[-1][1]) if nums[-1][1] else 100
                if max_score <= 0 or score > max_score:
                    continue
                candidates.append({
                    "page": label, "line": line_no, "subject": subject,
                    "score_candidate": score, "max_score_candidate": max_score,
                    "ocr_text": normalized, "confirmed": "",
                })
    review_path = output_dir / f"{path.stem}_ocr_review.csv"
    pd.DataFrame(candidates, columns=[
        "page", "line", "subject", "score_candidate", "max_score_candidate", "ocr_text", "confirmed"
    ]).to_csv(review_path, index=False, encoding="utf-8-sig")
    return raw_path, review_path

def main():
    parser = argparse.ArgumentParser(description="模試成績の取り込み・OCR補助")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="Excel/CSVの模試成績を統合")
    imp.add_argument("file", type=Path)
    imp.add_argument("--name")
    imp.add_argument("--date")
    imp.add_argument("--output", type=Path, default=SCORES)
    ocr = sub.add_parser("ocr", help="PDF/画像をOCRして確認用ファイルを作成")
    ocr.add_argument("file", type=Path)
    ocr.add_argument("--output-dir", type=Path, default=DATA / "ocr")
    args = parser.parse_args()

    if not args.file.exists():
        parser.error(f"ファイルが見つかりません: {args.file}")
    if args.command == "import":
        frame = normalize_scores(args.file, args.name, args.date)
        count = merge_scores(frame, args.output)
        print(f"取り込み完了: {len(frame)}行 / 保存先: {args.output}")
        print(f"統合後の新規行数: {count}")
    else:
        raw, review = ocr_file(args.file, args.output_dir)
        print(f"OCRテキスト: {raw}")
        print(f"確認用候補一覧: {review}")
        print("OCR候補は自動確定されません。CSVのscore_candidate/max_score_candidateを確認してください。")

if __name__ == "__main__":
    main()
