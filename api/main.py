from __future__ import annotations

import io
import json
import math
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WEB = ROOT / "web"
DB = DATA / "exam_strategy.sqlite3"
SUBJECTS = ["国語", "数学", "英語", "理科", "社会"]
SCORE_COLUMNS = [
    "id", "date", "exam_name", "exam_type", "subject", "score",
    "max_score", "deviation", "rank", "examinees", "created_at",
]

app = FastAPI(title="Exam Strategy API", version="1.1.0")


def db() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id TEXT PRIMARY KEY, date TEXT NOT NULL, exam_name TEXT NOT NULL,
            exam_type TEXT NOT NULL, subject TEXT NOT NULL, score REAL NOT NULL,
            max_score REAL NOT NULL, deviation REAL, rank INTEGER,
            examinees INTEGER, created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY, date TEXT, exam_name TEXT,
            subject TEXT NOT NULL, unit TEXT NOT NULL, correct INTEGER NOT NULL,
            points REAL, earned_points REAL
        )
    """)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.commit()
    return connection


def parse_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError("日付はYYYY-MM-DD形式で入力してください")


class Score(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    exam_name: str = Field(min_length=1, max_length=120)
    exam_type: str = Field(default="模試", min_length=1, max_length=40)
    subject: str
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    deviation: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    rank: int | None = Field(default=None, ge=1)
    examinees: int | None = Field(default=None, ge=1)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return parse_date(value)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if value not in SUBJECTS:
            raise ValueError("科目は国語・数学・英語・理科・社会から選択してください")
        return value

    @model_validator(mode="after")
    def validate_score_range(self):
        if self.score > self.max_score:
            raise ValueError("得点は満点以下にしてください")
        if self.rank is not None and self.examinees is not None and self.rank > self.examinees:
            raise ValueError("順位は受験者数以下にしてください")
        return self


class Question(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str | None = None
    exam_name: str | None = Field(default=None, max_length=120)
    subject: str
    unit: str = Field(min_length=1, max_length=120)
    correct: bool
    points: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    earned_points: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def validate_optional_date(cls, value: str | None) -> str | None:
        return parse_date(value) if value else value

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if value not in SUBJECTS:
            raise ValueError("科目は国語・数学・英語・理科・社会から選択してください")
        return value

    @model_validator(mode="after")
    def validate_points(self):
        if self.points is not None and self.earned_points is not None:
            if self.earned_points > self.points:
                raise ValueError("獲得点は配点以下にしてください")
        return self


class Settings(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
def startup() -> None:
    connection = db()
    connection.close()


@app.get("/api/health")
def health():
    connection = db()
    connection.execute("SELECT 1")
    connection.close()
    return {"status": "ok", "version": app.version}


@app.get("/api/scores")
def scores():
    connection = db()
    rows = connection.execute(
        "SELECT * FROM scores ORDER BY date DESC, created_at DESC"
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


@app.post("/api/scores", status_code=201)
def add_score(item: Score):
    data = item.model_dump()
    data["id"] = str(uuid.uuid4())
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    connection = db()
    try:
        connection.execute(
            f"INSERT INTO scores ({','.join(SCORE_COLUMNS)}) VALUES ({','.join('?' for _ in SCORE_COLUMNS)})",
            tuple(data[key] for key in SCORE_COLUMNS),
        )
        connection.commit()
    finally:
        connection.close()
    return data


@app.delete("/api/scores/{item_id}", status_code=204)
def delete_score(item_id: str):
    connection = db()
    try:
        cursor = connection.execute("DELETE FROM scores WHERE id = ?", (item_id,))
        connection.commit()
    finally:
        connection.close()
    if not cursor.rowcount:
        raise HTTPException(404, "成績が見つかりません")


@app.get("/api/questions")
def questions():
    connection = db()
    rows = connection.execute(
        "SELECT * FROM questions ORDER BY date DESC, rowid DESC"
    ).fetchall()
    connection.close()
    return [dict(row) for row in rows]


@app.post("/api/questions", status_code=201)
def add_question(item: Question):
    data = item.model_dump()
    data["id"] = str(uuid.uuid4())
    data["correct"] = int(data["correct"])
    connection = db()
    try:
        connection.execute(
            "INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)",
            tuple(data[key] for key in [
                "id", "date", "exam_name", "subject", "unit",
                "correct", "points", "earned_points"
            ]),
        )
        connection.commit()
    finally:
        connection.close()
    return data


@app.get("/api/settings")
def get_settings():
    connection = db()
    rows = connection.execute("SELECT key, value FROM settings").fetchall()
    connection.close()
    values = {row["key"]: json.loads(row["value"]) for row in rows}
    return {"profile": values.get("profile", {}), "target": values.get("target", {})}


@app.put("/api/settings")
def put_settings(item: Settings):
    values = item.model_dump()
    connection = db()
    try:
        for key, value in values.items():
            connection.execute(
                """INSERT INTO settings(key, value) VALUES(?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        connection.commit()
    finally:
        connection.close()
    return values


@app.get("/api/analysis")
def analysis():
    connection = db()
    try:
        score_rows = connection.execute(
            "SELECT * FROM scores ORDER BY date, created_at"
        ).fetchall()
        question_rows = connection.execute("SELECT * FROM questions").fetchall()
        setting_rows = connection.execute("SELECT key, value FROM settings").fetchall()
    finally:
        connection.close()

    settings = {row["key"]: json.loads(row["value"]) for row in setting_rows}
    if not score_rows:
        return {"summary": [], "weak_units": [], "latest_exam": None, "target_gaps": []}

    scores_df = pd.DataFrame([dict(row) for row in score_rows])
    scores_df["rate"] = scores_df["score"] / scores_df["max_score"] * 100
    summary = []
    for subject, group in scores_df.groupby("subject"):
        latest = group.iloc[-1]
        summary.append({
            "subject": subject,
            "count": int(len(group)),
            "average_rate": round(float(group["rate"].mean()), 1),
            "latest_score": float(latest["score"]),
            "latest_max": float(latest["max_score"]),
            "latest_rate": round(float(latest["rate"]), 1),
            "latest_deviation": None if pd.isna(latest["deviation"]) else float(latest["deviation"]),
        })

    latest_date = scores_df["date"].max()
    latest_on_date = scores_df[scores_df["date"] == latest_date]
    latest_exam_name = latest_on_date.iloc[-1]["exam_name"]
    latest_exam_rows = latest_on_date[latest_on_date["exam_name"] == latest_exam_name]
    total = float(latest_exam_rows["score"].sum())
    max_total = float(latest_exam_rows["max_score"].sum())
    latest_exam = {
        "date": str(latest_date),
        "name": str(latest_exam_name),
        "total": total,
        "max_total": max_total,
        "rate": round(total / max_total * 100, 1) if max_total else 0,
        "subjects_count": int(len(latest_exam_rows)),
    }

    weak_units = []
    if question_rows:
        question_df = pd.DataFrame([dict(row) for row in question_rows])
        for (subject, unit), group in question_df.groupby(["subject", "unit"]):
            has_complete_points = (
                group["points"].notna().all()
                and group["earned_points"].notna().all()
                and float(group["points"].sum()) > 0
            )
            if has_complete_points:
                accuracy = float(group["earned_points"].sum() / group["points"].sum() * 100)
                method = "points"
            else:
                accuracy = float(group["correct"].mean() * 100)
                method = "correct_count"
            weak_units.append({
                "subject": subject,
                "unit": unit,
                "questions": int(len(group)),
                "accuracy": round(accuracy, 1),
                "calculation": method,
            })
    weak_units.sort(key=lambda item: (item["accuracy"], item["subject"], item["unit"]))

    target_subjects = settings.get("target", {}).get("subjects", {})
    target_gaps = []
    for subject_summary in summary:
        goal = target_subjects.get(subject_summary["subject"], {}).get("target_score")
        if goal is None:
            continue
        try:
            goal_value = float(goal)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(goal_value) or goal_value < 0:
            continue
        target_gaps.append({
            "subject": subject_summary["subject"],
            "current": subject_summary["latest_score"],
            "target": goal_value,
            "gap": round(goal_value - subject_summary["latest_score"], 1),
            "max_score": subject_summary["latest_max"],
        })

    return {
        "summary": summary,
        "weak_units": weak_units,
        "latest_exam": latest_exam,
        "target_gaps": target_gaps,
    }


@app.post("/api/import/table")
async def import_table(file: UploadFile = File(...)):
    content = await file.read()
    filename = (file.filename or "").lower()
    try:
        if filename.endswith((".xlsx", ".xls")):
            frame = pd.read_excel(io.BytesIO(content))
        elif filename.endswith(".csv"):
            frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        else:
            raise HTTPException(415, "CSVまたはExcelファイルを選択してください")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "ファイルを読み込めません。形式や内容を確認してください")

    required = {"subject", "score", "max_score"}
    if not required.issubset(frame.columns):
        raise HTTPException(422, "subject, score, max_score列が必要です")

    imported = 0
    errors = []
    default_name = Path(file.filename or "取り込み").stem or "取り込み"
    for index, row in frame.iterrows():
        try:
            def optional_number(column: str):
                value = row.get(column)
                return None if pd.isna(value) or value == "" else float(value)

            date_value = row.get("date")
            date_text = date.today().isoformat() if pd.isna(date_value) else str(date_value)[:10]
            exam_value = row.get("exam_name")
            exam_name = default_name if pd.isna(exam_value) or not str(exam_value).strip() else str(exam_value).strip()
            exam_type_value = row.get("exam_type")
            exam_type = "模試" if pd.isna(exam_type_value) or not str(exam_type_value).strip() else str(exam_type_value).strip()
            payload = Score(
                date=date_text,
                exam_name=exam_name,
                exam_type=exam_type,
                subject=str(row["subject"]).strip(),
                score=float(row["score"]),
                max_score=float(row["max_score"]),
                deviation=optional_number("deviation"),
                rank=optional_number("rank"),
                examinees=optional_number("examinees"),
            )
            add_score(payload)
            imported += 1
        except Exception as error:
            errors.append({"row": int(index) + 2, "error": str(error)})
    return {"imported": imported, "errors": errors}


@app.post("/api/import/pdf")
async def import_pdf(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDFファイルを選択してください")
    try:
        pages = PdfReader(io.BytesIO(await file.read())).pages
        texts = [page.extract_text() or "" for page in pages]
    except Exception:
        raise HTTPException(400, "PDFを読み込めません。ファイルが破損していないか確認してください")
    extracted = "\n\n".join(
        f"--- {index + 1}ページ ---\n{text}" for index, text in enumerate(texts)
    )
    return {
        "pages": len(texts),
        "text": extracted,
        "needs_ocr": not any(text.strip() for text in texts),
    }


@app.get("/api/reports/excel")
def report():
    connection = db()
    try:
        scores_df = pd.read_sql_query(
            """SELECT date, exam_name, exam_type, subject, score, max_score,
                      deviation, rank, examinees FROM scores ORDER BY date, exam_name""",
            connection,
        )
        questions_df = pd.read_sql_query(
            """SELECT date, exam_name, subject, unit, correct, points, earned_points
               FROM questions ORDER BY date, exam_name""",
            connection,
        )
    finally:
        connection.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        scores_df.to_excel(writer, sheet_name="成績データ", index=False)
        questions_df.to_excel(writer, sheet_name="問題別データ", index=False)
        if not scores_df.empty:
            scores_df["得点率"] = scores_df["score"] / scores_df["max_score"] * 100
            scores_df.groupby("subject")["得点率"].agg(
                ["count", "mean", "max", "min"]
            ).round(1).to_excel(writer, sheet_name="科目分析")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=exam_strategy_report.xlsx"},
    )


if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
