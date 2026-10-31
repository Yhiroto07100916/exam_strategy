from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from pypdf import PdfReader

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"

SCORE_COLUMNS = [
    "date", "exam_name", "exam_type", "subject", "score",
    "max_score", "deviation", "rank", "examinees"
]
QUESTION_COLUMNS = [
    "date", "exam_name", "subject", "unit", "question_id",
    "correct", "points", "earned_points"
]


def write_template() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    scores = pd.DataFrame([
        ["2026-10-01", "サンプル模試", "模試", "国語", 72, 100, 52.1, 120, 1000],
        ["2026-10-01", "サンプル模試", "模試", "数学", 58, 100, 48.0, 300, 1000],
        ["2026-10-01", "サンプル模試", "模試", "英語", 81, 100, 56.2, 80, 1000],
        ["2026-10-01", "サンプル模試", "模試", "理科", 65, 100, None, None, None],
        ["2026-10-01", "サンプル模試", "模試", "社会", 74, 100, None, None, None],
    ], columns=SCORE_COLUMNS)
    scores.to_excel(DATA_DIR / "scores_template.xlsx", index=False)
    pd.DataFrame(columns=QUESTION_COLUMNS).to_csv(
        DATA_DIR / "questions_template.csv", index=False, encoding="utf-8-sig"
    )
    target = {
        "school_name": "志望校名", "prefecture": "", "admission_year": 2027,
        "subjects": {
            s: {"target_score": None, "max_score": 100, "weight": 1.0}
            for s in ["国語", "数学", "英語", "理科", "社会"]
        },
        "total_target": None, "source_note": ""
    }
    (DATA_DIR / "target_template.json").write_text(
        json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    profile = {
        "name": "", "grade": "中学3年", "prefecture": "",
        "exam_date": "", "weekly_study_hours": None, "notes": ""
    }
    (DATA_DIR / "profile_template.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"テンプレートを作成しました: {DATA_DIR}")


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp932")
    raise ValueError(f"未対応の表形式ファイルです: {path}")


def load_scores(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    df = read_table(path)
    missing = [c for c in ["subject", "score", "max_score"] if c not in df.columns]
    if missing:
        raise ValueError(f"成績ファイルに必要な列がありません: {', '.join(missing)}")
    for col in SCORE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["max_score"] = pd.to_numeric(df["max_score"], errors="coerce")
    df["deviation"] = pd.to_numeric(df["deviation"], errors="coerce")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["examinees"] = pd.to_numeric(df["examinees"], errors="coerce")
    valid = df["score"].notna() & df["max_score"].notna() & (df["max_score"] > 0)
    if not valid.all():
        raise ValueError("得点・満点が空欄、または満点が0以下の行があります。")
    if ((df["score"] < 0) | (df["score"] > df["max_score"])).any():
        raise ValueError("満点の範囲外の得点があります。入力を確認してください。")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["得点率"] = df["score"] / df["max_score"] * 100
    return df


def load_questions(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=QUESTION_COLUMNS)
    df = read_table(path)
    for col in QUESTION_COLUMNS:
        if col not in df.columns:
            df[col] = None
    if df.empty:
        return df
    df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
    df["points"] = pd.to_numeric(df["points"], errors="coerce")
    df["earned_points"] = pd.to_numeric(df["earned_points"], errors="coerce")
    df["正誤"] = df["correct"].map({1: "正解", 0: "不正解"})
    df["得点率"] = df["earned_points"] / df["points"] * 100
    return df


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(scores: pd.DataFrame, questions: pd.DataFrame,
            target: dict[str, Any], profile: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    summary_rows = []
    if not scores.empty:
        for subject, group in scores.groupby("subject"):
            avg_rate = group["得点率"].mean()
            deviations = group["deviation"].dropna()
            summary_rows.append({
                "科目": subject,
                "試験回数": len(group),
                "平均得点率(%)": round(avg_rate, 1),
                "最新得点率(%)": round(group.sort_values("date")["得点率"].iloc[-1], 1),
                "最新偏差値": deviations.iloc[-1] if len(deviations) else None,
                "得点率の最高(%)": round(group["得点率"].max(), 1),
                "得点率の最低(%)": round(group["得点率"].min(), 1),
            })
    summary = pd.DataFrame(summary_rows)

    target_rows = []
    subject_targets = target.get("subjects", {})
    if not scores.empty:
        latest = scores.sort_values("date").groupby("subject", as_index=False).tail(1)
        for _, row in latest.iterrows():
            spec = subject_targets.get(str(row["subject"]), {})
            goal = spec.get("target_score")
            if goal is not None:
                target_rows.append({
                    "科目": row["subject"],
                    "最新得点": row["score"],
                    "目標点": goal,
                    "目標との差": round(float(row["score"]) - float(goal), 1),
                    "目標達成": "達成" if row["score"] >= goal else "未達"
                })
    target_df = pd.DataFrame(target_rows)

    unit_rows = []
    if not questions.empty:
        valid = questions.dropna(subset=["subject", "unit", "correct"])
        if not valid.empty:
            unit_df = valid.groupby(["subject", "unit"]).agg(
                問題数=("correct", "count"),
                正答率=("correct", lambda x: (x == 1).mean() * 100),
                配点合計=("points", "sum"),
                獲得点=("earned_points", "sum"),
            ).reset_index()
            unit_df["正答率"] = unit_df["正答率"].round(1)
            unit_rows = unit_df.to_dict("records")
    units = pd.DataFrame(unit_rows)

    recommendations = []
    if not summary.empty:
        ranked = summary.sort_values("平均得点率(%)")
        for _, row in ranked.head(3).iterrows():
            recommendations.append(
                f"{row['科目']}: 平均得点率が{row['平均得点率(%)']}%。"
                "直近の答案を見直し、失点原因を知識不足・解法・読み違い・時間配分に分類する。"
            )
    if not units.empty:
        weak = units.sort_values("正答率").head(5)
        for _, row in weak.iterrows():
            recommendations.append(
                f"{row['subject']} / {row['unit']}: 正答率{row['正答率']}%。"
                "基礎事項の確認後、類題で定着を確認する。"
            )
    if not recommendations:
        recommendations.append("分析データが不足しています。成績または問題別正誤データを追加してください。")

    report_path = REPORT_DIR / "exam_analysis.xlsx"
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        (scores if not scores.empty else pd.DataFrame(columns=SCORE_COLUMNS)).to_excel(
            writer, sheet_name="成績データ", index=False
        )
        summary.to_excel(writer, sheet_name="科目分析", index=False)
        target_df.to_excel(writer, sheet_name="志望校との差", index=False)
        units.to_excel(writer, sheet_name="単元分析", index=False)
        pd.DataFrame({"学習提案": recommendations}).to_excel(
            writer, sheet_name="学習戦略", index=False
        )
        if not questions.empty:
            questions.to_excel(writer, sheet_name="問題別データ", index=False)

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column_cells in sheet.columns:
                max_len = max((len(str(c.value or "")) for c in column_cells), default=10)
                sheet.column_dimensions[column_cells[0].column_letter].width = min(max_len + 2, 36)

    print(f"分析レポートを出力しました: {report_path}")
    print(f"志望校: {target.get('school_name', '未設定')}")
    if profile.get("prefecture"):
        print(f"都道府県: {profile['prefecture']}")
    print("\\n学習上の注目点:")
    for item in recommendations:
        print(f"- {item}")
    return report_path


def extract_pdf(pdf_path: Path, output: Path) -> None:
    reader = PdfReader(str(pdf_path))
    text_parts = []
    for index, page in enumerate(reader.pages, start=1):
        text_parts.append(f"--- {index}ページ ---\\n{page.extract_text() or ''}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\\n\\n".join(text_parts), encoding="utf-8")
    print(f"PDFのテキストを抽出しました: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="高校受験向け成績・学習戦略分析")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("template", help="入力テンプレートを作成")

    analyze_parser = sub.add_parser("analyze", help="成績を分析してExcelレポートを作成")
    analyze_parser.add_argument("--scores", type=Path)
    analyze_parser.add_argument("--questions", type=Path)
    analyze_parser.add_argument("--target", type=Path)
    analyze_parser.add_argument("--profile", type=Path)

    pdf_parser = sub.add_parser("extract-pdf", help="テキストPDFから文字を抽出")
    pdf_parser.add_argument("pdf", type=Path)
    pdf_parser.add_argument("--output", type=Path, default=DATA_DIR / "pdf_text.txt")

    args = parser.parse_args()
    if args.command == "template":
        write_template()
    elif args.command == "analyze":
        scores = load_scores(args.scores)
        questions = load_questions(args.questions)
        target = load_json(args.target)
        profile = load_json(args.profile)
        analyze(scores, questions, target, profile)
    elif args.command == "extract-pdf":
        extract_pdf(args.pdf, args.output)


if __name__ == "__main__":
    main()
