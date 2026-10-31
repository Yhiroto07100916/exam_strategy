from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

SUBJECTS_5 = ["国語", "数学", "英語", "社会", "理科"]
SUBJECTS_3 = ["国語", "数学", "英語"]
ALL_REPORT_SUBJECTS = [
    "国語", "数学", "英語", "社会", "理科",
    "音楽", "美術", "保健体育", "技術・家庭"
]
PRACTICAL_SUBJECTS = ["音楽", "美術", "保健体育", "技術・家庭"]


def calculate_report_score(grades: dict[str, int], exam_subjects: list[str],
                           report_ratio: int) -> tuple[int, int, int]:
    """東京都の調査書点を計算。返り値は(換算点, 素点, 素点満点)。"""
    missing = [s for s in ALL_REPORT_SUBJECTS if s not in grades]
    if missing:
        raise ValueError(f"調査書評定が不足しています: {', '.join(missing)}")

    for subject, grade in grades.items():
        if subject in ALL_REPORT_SUBJECTS and (
            not isinstance(grade, int) or not 1 <= grade <= 5
        ):
            raise ValueError(f"{subject}の評定は1〜5の整数にしてください")

    raw = sum(grades[s] * (2 if s not in exam_subjects else 1)
              for s in ALL_REPORT_SUBJECTS)
    raw_max = 65 if len(exam_subjects) == 5 else 75
    converted = math.floor(report_ratio * raw / raw_max)
    return converted, raw, raw_max


def calculate_method(exam_scores: dict[str, float], grades: dict[str, int],
                     method: str) -> dict:
    if method == "7:3":
        exam_subjects, exam_ratio, report_ratio = SUBJECTS_5, 700, 300
    elif method == "6:4":
        exam_subjects, exam_ratio, report_ratio = SUBJECTS_3, 600, 400
    elif method == "10:0":
        exam_subjects, exam_ratio, report_ratio = SUBJECTS_5, 1000, 0
    else:
        raise ValueError(f"未対応の選抜比率: {method}")

    missing = [s for s in exam_subjects if s not in exam_scores]
    if missing:
        raise ValueError(f"{method}に必要な学力検査得点が不足: {', '.join(missing)}")

    exam_raw = sum(float(exam_scores[s]) for s in exam_subjects)
    exam_max = 100 * len(exam_subjects)
    exam_converted = math.floor(exam_ratio * exam_raw / exam_max)

    if report_ratio:
        report_converted, report_raw, report_max = calculate_report_score(
            grades, exam_subjects, report_ratio
        )
    else:
        report_converted, report_raw, report_max = 0, None, None

    return {
        "選抜比率": method,
        "学力検査素点": exam_raw,
        "学力検査換算点": exam_converted,
        "調査書素点": report_raw,
        "調査書素点満点": report_max,
        "調査書換算点": report_converted,
        "総合得点": exam_converted + report_converted,
        "総合満点": 1000,
    }


def main():
    parser = argparse.ArgumentParser(description="東京都立高校・学力検査に基づく選抜の得点換算")
    parser.add_argument("--input", type=Path, default=Path("data/tokyo_public_template.xlsx"))
    parser.add_argument("--config", type=Path, default=Path("data/tokyo_public_config.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/tokyo_public_result.xlsx"))
    args = parser.parse_args()

    exam_df = pd.read_excel(args.input, sheet_name="学力検査")
    report_df = pd.read_excel(args.input, sheet_name="調査書")
    config = json.loads(args.config.read_text(encoding="utf-8"))

    exam_scores = dict(zip(exam_df["科目"], pd.to_numeric(exam_df["得点"])))
    grades = dict(zip(report_df["科目"], pd.to_numeric(report_df["評定"]).astype(int)))
    methods = config.get("selection_methods", ["7:3"])
    if not methods or any(m not in {"7:3", "6:4", "10:0"} for m in methods):
        raise ValueError("selection_methodsは7:3、6:4、10:0から指定してください")

    results = [calculate_method(exam_scores, grades, method) for method in methods]
    result_df = pd.DataFrame(results)
    if len(results) > 1:
        best = max(results, key=lambda x: x["総合得点"])
        result_df["学校指定方式内の最高得点"] = ""
        result_df.loc[result_df["選抜比率"] == best["選抜比率"],
                      "学校指定方式内の最高得点"] = best["総合得点"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        result_df.to_excel(writer, sheet_name="換算結果", index=False)
        exam_df.to_excel(writer, sheet_name="入力_学力検査", index=False)
        report_df.to_excel(writer, sheet_name="入力_調査書", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                width = max(len(str(c.value or "")) for c in cells)
                sheet.column_dimensions[cells[0].column_letter].width = min(width + 3, 32)

    print(f"東京都立高校の換算結果を出力しました: {args.output}")
    print(result_df[["選抜比率", "学力検査換算点", "調査書換算点", "総合得点"]].to_string(index=False))


if __name__ == "__main__":
    main()
