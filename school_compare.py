from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_school(school: dict[str, Any], student: dict[str, Any]) -> dict[str, Any]:
    """各校が設定した選抜要素を同一ルールで換算。未知の方式は推測しない。"""
    rule = school.get("scoring_rule", {})
    components = rule.get("components", [])
    if not components:
        return {
            "学校名": school.get("school_name", "名称未設定"),
            "都県": school.get("prefecture", ""),
            "区分": school.get("school_type", ""),
            "方式": school.get("selection_type", ""),
            "計算状態": "方式未登録",
            "換算得点": None,
            "満点": None,
            "目標点": rule.get("target_total"),
            "目標との差": None,
            "不足データ": "選抜方式の公式情報を登録してください",
            "情報確認状態": school.get("verification_status", "未確認"),
        }

    total = 0.0
    total_max = 0.0
    missing = []
    details = []

    for component in components:
        key = component["input_key"]
        label = component.get("label", key)
        max_score = float(component["max_score"])
        weight = float(component["weight"])
        if max_score <= 0 or weight < 0:
            raise ValueError(f"{school.get('school_name')}: max_score/weightの設定が不正です")
        value = student.get("scores", {}).get(key)
        if value is None:
            if component.get("required", True):
                missing.append(label)
            continue
        value = float(value)
        if value < 0 or value > max_score:
            raise ValueError(
                f"{school.get('school_name')}: {label}={value} は0〜{max_score}の範囲外です"
            )
        converted = value / max_score * weight
        total += converted
        total_max += weight
        details.append({
            "項目": label,
            "入力値": value,
            "入力満点": max_score,
            "換算点": round(converted, 2),
            "換算満点": weight,
        })

    if missing:
        status = "入力不足"
        final_score = None
        gap = None
    elif total_max == 0:
        status = "計算不可"
        final_score = None
        gap = None
    else:
        status = "計算完了"
        final_score = round(total, 2)
        target = rule.get("target_total")
        gap = round(final_score - float(target), 2) if target is not None else None

    return {
        "学校名": school.get("school_name", "名称未設定"),
        "都県": school.get("prefecture", ""),
        "区分": school.get("school_type", ""),
        "方式": school.get("selection_type", ""),
        "計算状態": status,
        "換算得点": final_score,
        "満点": round(total_max, 2) if total_max else None,
        "目標点": rule.get("target_total"),
        "目標との差": gap,
        "不足データ": "、".join(missing),
        "情報確認状態": school.get("verification_status", "未確認"),
        "_details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="複数高校の選抜方式・得点比較")
    parser.add_argument("--schools", type=Path, default=Path("data/schools_template.json"))
    parser.add_argument("--student", type=Path, default=Path("data/student_exam_template.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/school_comparison.xlsx"))
    args = parser.parse_args()

    schools_data = load_json(args.schools)
    student = load_json(args.student)
    results = [score_school(s, student) for s in schools_data.get("schools", [])]
    if not results:
        raise ValueError("学校データがありません。schools_template.jsonに学校を追加してください。")

    summary = pd.DataFrame([{k: v for k, v in r.items() if k != "_details"} for r in results])
    details = []
    for r in results:
        for d in r.get("_details", []):
            details.append({"学校名": r["学校名"], "方式": r["方式"], **d})
    detail_df = pd.DataFrame(details)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="学校比較", index=False)
        detail_df.to_excel(writer, sheet_name="換算内訳", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                width = max((len(str(c.value or "")) for c in cells), default=10)
                sheet.column_dimensions[cells[0].column_letter].width = min(width + 2, 40)

    print(f"比較レポートを作成しました: {args.output}")
    print(summary.to_string(index=False))
    print("\\n注意: この結果は登録された選抜方式の得点換算であり、合格可能性の判定ではありません。")


if __name__ == "__main__":
    main()
