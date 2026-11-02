from __future__ import annotations

import io
import json
import math
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pypdf import PdfReader

from .ocr import MAX_PDF_BYTES, preview_pdf_ocr

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WEB = ROOT / "web"
DB = DATA / "exam_strategy.sqlite3"
from .main_models import SUBJECTS
from .target_routes import router as target_router
from .school_targeting import SchoolScoringModel, SchoolTargetAllocationRequest, allocate_school_targets
SCORE_COLUMNS = [
    "id", "date", "exam_name", "exam_type", "subject", "score",
    "max_score", "deviation", "rank", "examinees", "created_at",
]

@asynccontextmanager
async def lifespan(_: FastAPI):
    connection = db()
    connection.close()
    yield


app = FastAPI(title="Exam Strategy API", version="1.2.0", lifespan=lifespan)
app.include_router(target_router)


def db() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schools (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            prefecture TEXT NOT NULL,
            school_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(prefecture, name)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS school_rules (
            id TEXT PRIMARY KEY,
            school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
            admission_year INTEGER NOT NULL,
            course TEXT NOT NULL,
            selection_type TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            official_source_url TEXT,
            verified_on TEXT,
            rule_data TEXT NOT NULL,
            notes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(school_id, admission_year, course, selection_type)
        )
    """)
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
        if (self.points is None) != (self.earned_points is None):
            raise ValueError("配点と獲得点は両方入力するか、両方空欄にしてください")
        if self.points is not None and self.earned_points is not None:
            if self.earned_points > self.points:
                raise ValueError("獲得点は配点以下にしてください")
        return self


class Settings(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)


class OCRConfirmRequest(BaseModel):
    scores: list[Score] = Field(min_length=1, max_length=100)



class SchoolCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    prefecture: Literal["東京都", "神奈川県", "埼玉県", "千葉県"]
    school_type: Literal["公立", "私立"]


class SchoolRuleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    admission_year: int = Field(ge=2025, le=2100)
    course: str = Field(default="", max_length=120)
    selection_type: str = Field(min_length=1, max_length=120)
    verification_status: Literal["未確認", "確認済み", "要再確認"] = "未確認"
    official_source_url: str | None = Field(default=None, max_length=2048)
    verified_on: str | None = None
    rule_data: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)

    @field_validator("official_source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("公式資料URLはhttps://で入力してください")
        return value

    @field_validator("verified_on")
    @classmethod
    def validate_verified_date(cls, value: str | None) -> str | None:
        return parse_date(value) if value else value

    @model_validator(mode="after")
    def validate_verification(self):
        if self.verification_status == "確認済み":
            if not self.official_source_url or not self.verified_on or not self.rule_data:
                raise ValueError("確認済みには公式資料URL・確認日・確認した選抜データが必要です")
            try:
                SchoolScoringModel.model_validate(self.rule_data.get("scoring_model"))
            except (ValidationError, TypeError, ValueError) as error:
                raise ValueError(
                    "確認済みの選抜情報には、科目別配点・固定評価項目・資料ページを含むscoring_modelが必要です"
                ) from error
        return self




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
def score_duplicate_exists(
    connection: sqlite3.Connection,
    data: dict[str, Any],
    exclude_id: str | None = None,
) -> bool:
    query = """
        SELECT 1 FROM scores
        WHERE date=? AND exam_name=? AND exam_type=? AND subject=?
    """
    values = [data["date"], data["exam_name"], data["exam_type"], data["subject"]]
    if exclude_id is not None:
        query += " AND id<>?"
        values.append(exclude_id)
    return connection.execute(query + " LIMIT 1", values).fetchone() is not None


def add_score(item: Score):
    data = item.model_dump()
    data["id"] = str(uuid.uuid4())
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if score_duplicate_exists(connection, data):
            raise HTTPException(
                409,
                "同じ日付・模試名・試験種別・科目の成績が既に登録されています",
            )
        connection.execute(
            f"INSERT INTO scores ({','.join(SCORE_COLUMNS)}) VALUES ({','.join('?' for _ in SCORE_COLUMNS)})",
            tuple(data[key] for key in SCORE_COLUMNS),
        )
        connection.commit()
    finally:
        connection.close()
    return data


@app.put("/api/scores/{item_id}")
def update_score(item_id: str, item: Score):
    data = item.model_dump()
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT created_at FROM scores WHERE id = ?", (item_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "成績が見つかりません")
        if score_duplicate_exists(connection, data, exclude_id=item_id):
            raise HTTPException(
                409,
                "同じ日付・模試名・試験種別・科目の成績が既に登録されています",
            )
        connection.execute(
            """UPDATE scores SET date=?, exam_name=?, exam_type=?, subject=?,
               score=?, max_score=?, deviation=?, rank=?, examinees=?
               WHERE id=?""",
            (
                data["date"], data["exam_name"], data["exam_type"], data["subject"],
                data["score"], data["max_score"], data["deviation"], data["rank"],
                data["examinees"], item_id,
            ),
        )
        connection.commit()
        return {"id": item_id, **data, "created_at": existing["created_at"]}
    finally:
        connection.close()


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


@app.put("/api/questions/{item_id}")
def update_question(item_id: str, item: Question):
    data = item.model_dump()
    data["correct"] = int(data["correct"])
    connection = db()
    try:
        cursor = connection.execute(
            """UPDATE questions SET date=?, exam_name=?, subject=?, unit=?,
               correct=?, points=?, earned_points=? WHERE id=?""",
            (
                data["date"], data["exam_name"], data["subject"], data["unit"],
                data["correct"], data["points"], data["earned_points"], item_id,
            ),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "問題データが見つかりません")
        connection.commit()
    finally:
        connection.close()
    return {"id": item_id, **data}


@app.delete("/api/questions/{item_id}", status_code=204)
def delete_question(item_id: str):
    connection = db()
    try:
        cursor = connection.execute("DELETE FROM questions WHERE id = ?", (item_id,))
        connection.commit()
    finally:
        connection.close()
    if not cursor.rowcount:
        raise HTTPException(404, "問題データが見つかりません")

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
    summary = []
    latest_exam = None
    if score_rows:
        scores_df = pd.DataFrame([dict(row) for row in score_rows])
        scores_df["rate"] = scores_df["score"] / scores_df["max_score"] * 100
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
        latest_exam_record = latest_on_date.iloc[-1]
        latest_exam_name = latest_exam_record["exam_name"]
        latest_exam_type = latest_exam_record["exam_type"]
        latest_exam_rows = latest_on_date[
            (latest_on_date["exam_name"] == latest_exam_name)
            & (latest_on_date["exam_type"] == latest_exam_type)
        ]
        total = float(latest_exam_rows["score"].sum())
        max_total = float(latest_exam_rows["max_score"].sum())
        latest_exam = {
            "date": str(latest_date),
            "name": str(latest_exam_name),
            "exam_type": str(latest_exam_type),
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


@app.get("/api/schools/official-sources")
def list_official_sources():
    path = DATA / "official_sources.json"
    if not path.exists():
        return {"admission_year": None, "official_sources": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(500, "公式資料一覧を読み込めません")


@app.get("/api/schools")
def list_schools():
    connection = db()
    try:
        school_rows = connection.execute(
            "SELECT * FROM schools ORDER BY prefecture, name"
        ).fetchall()
        result = []
        for school in school_rows:
            item = dict(school)
            rule_rows = connection.execute(
                """SELECT * FROM school_rules WHERE school_id=?
                   ORDER BY admission_year DESC, course, selection_type""",
                (item["id"],),
            ).fetchall()
            item["rules"] = []
            for rule in rule_rows:
                rule_item = dict(rule)
                rule_item["rule_data"] = json.loads(rule_item["rule_data"])
                item["rules"].append(rule_item)
            result.append(item)
        return result
    finally:
        connection.close()


@app.post("/api/schools", status_code=201)
def create_school(item: SchoolCreate):
    data = item.model_dump()
    now = datetime.now(timezone.utc).isoformat()
    data.update({"id": str(uuid.uuid4()), "created_at": now, "updated_at": now})
    connection = db()
    try:
        connection.execute(
            "INSERT INTO schools VALUES(?,?,?,?,?,?)",
            tuple(data[key] for key in [
                "id", "name", "prefecture", "school_type", "created_at", "updated_at"
            ]),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "同じ都道府県・学校名の学校が登録されています")
    finally:
        connection.close()
    return {**data, "rules": []}


@app.post("/api/schools/{school_id}/rules", status_code=201)
def create_school_rule(school_id: str, item: SchoolRuleInput):
    data = item.model_dump()
    connection = db()
    now = datetime.now(timezone.utc).isoformat()
    data.update({
        "id": str(uuid.uuid4()),
        "school_id": school_id,
        "rule_data": json.dumps(data["rule_data"], ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    })
    try:
        if not connection.execute(
            "SELECT 1 FROM schools WHERE id=?", (school_id,)
        ).fetchone():
            raise HTTPException(404, "学校が見つかりません")
        connection.execute(
            """INSERT INTO school_rules (
                id, school_id, admission_year, course, selection_type,
                verification_status, official_source_url, verified_on,
                rule_data, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple(data[key] for key in [
                "id", "school_id", "admission_year", "course", "selection_type",
                "verification_status", "official_source_url", "verified_on",
                "rule_data", "notes", "created_at", "updated_at",
            ]),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "同じ年度・コース・選抜区分のルールが登録されています")
    finally:
        connection.close()
    data["rule_data"] = item.rule_data
    return data


@app.put("/api/school-rules/{rule_id}")
def update_school_rule(rule_id: str, item: SchoolRuleInput):
    data = item.model_dump()
    connection = db()
    try:
        cursor = connection.execute(
            """UPDATE school_rules SET admission_year=?, course=?, selection_type=?,
               verification_status=?, official_source_url=?, verified_on=?,
               rule_data=?, notes=?, updated_at=? WHERE id=?""",
            (
                data["admission_year"], data["course"], data["selection_type"],
                data["verification_status"], data["official_source_url"],
                data["verified_on"], json.dumps(data["rule_data"], ensure_ascii=False),
                data["notes"], datetime.now(timezone.utc).isoformat(), rule_id,
            ),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "選抜ルールが見つかりません")
        connection.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "同じ年度・コース・選抜区分のルールが登録されています")
    finally:
        connection.close()
    return {"id": rule_id, **data}


@app.post("/api/schools/{school_id}/rules/{rule_id}/allocate")
def allocate_school_rule(
    school_id: str,
    rule_id: str,
    request: SchoolTargetAllocationRequest,
):
    connection = db()
    try:
        row = connection.execute(
            """SELECT verification_status, official_source_url, verified_on, rule_data
               FROM school_rules WHERE id=? AND school_id=?""",
            (rule_id, school_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise HTTPException(404, "学校または選抜ルールが見つかりません")
    if row["verification_status"] != "確認済み":
        raise HTTPException(409, "公式資料を確認済みにした選抜ルールだけ計算に使用できます")
    if not row["official_source_url"] or not row["verified_on"]:
        raise HTTPException(409, "公式資料URLと確認日が登録されていません")
    try:
        rule_data = json.loads(row["rule_data"])
        scoring_model = SchoolScoringModel.model_validate(rule_data.get("scoring_model"))
        return allocate_school_targets(scoring_model, request)
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(422, detail=str(error) or "選抜ルールの計算形式を確認してください")


@app.delete("/api/school-rules/{rule_id}", status_code=204)
def delete_school_rule(rule_id: str):
    connection = db()
    try:
        cursor = connection.execute("DELETE FROM school_rules WHERE id=?", (rule_id,))
        connection.commit()
    finally:
        connection.close()
    if not cursor.rowcount:
        raise HTTPException(404, "選抜ルールが見つかりません")


@app.delete("/api/schools/{school_id}", status_code=204)
def delete_school(school_id: str):
    connection = db()
    try:
        cursor = connection.execute("DELETE FROM schools WHERE id=?", (school_id,))
        connection.commit()
    finally:
        connection.close()
    if not cursor.rowcount:
        raise HTTPException(404, "学校が見つかりません")


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

    errors = []
    parsed = []
    duplicates = 0
    default_name = Path(file.filename or "取り込み").stem or "取り込み"

    def missing(value: Any) -> bool:
        return value is None or bool(pd.isna(value)) or value == ""

    def optional_number(row: pd.Series, column: str, integer: bool = False):
        value = row.get(column)
        if missing(value):
            return None
        number = float(value)
        if integer:
            if not number.is_integer():
                raise ValueError(f"{column}は整数で入力してください")
            return int(number)
        return number

    for index, row in frame.iterrows():
        try:
            date_value = row.get("date")
            date_text = date.today().isoformat() if missing(date_value) else str(date_value)[:10]
            exam_value = row.get("exam_name")
            exam_name = default_name if missing(exam_value) or not str(exam_value).strip() else str(exam_value).strip()
            exam_type_value = row.get("exam_type")
            exam_type = "模試" if missing(exam_type_value) or not str(exam_type_value).strip() else str(exam_type_value).strip()
            payload = Score(
                date=date_text,
                exam_name=exam_name,
                exam_type=exam_type,
                subject=str(row["subject"]).strip(),
                score=float(row["score"]),
                max_score=float(row["max_score"]),
                deviation=optional_number(row, "deviation"),
                rank=optional_number(row, "rank", integer=True),
                examinees=optional_number(row, "examinees", integer=True),
            )
            parsed.append(payload.model_dump())
        except Exception as error:
            errors.append({"row": int(index) + 2, "error": str(error)})

    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_rows = connection.execute(
            "SELECT date, exam_name, exam_type, subject FROM scores"
        ).fetchall()
        existing_keys = {
            (row["date"], row["exam_name"], row["exam_type"], row["subject"])
            for row in existing_rows
        }
        accepted = []
        for data in parsed:
            key = (data["date"], data["exam_name"], data["exam_type"], data["subject"])
            if key in existing_keys:
                duplicates += 1
                continue
            existing_keys.add(key)
            data["id"] = str(uuid.uuid4())
            data["created_at"] = datetime.now(timezone.utc).isoformat()
            accepted.append(data)

        for data in accepted:
            connection.execute(
                f"INSERT INTO scores ({','.join(SCORE_COLUMNS)}) VALUES ({','.join('?' for _ in SCORE_COLUMNS)})",
                tuple(data[key] for key in SCORE_COLUMNS),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise HTTPException(500, "取り込み中にエラーが発生したため、データは保存されていません")
    finally:
        connection.close()

    return {"imported": len(accepted), "duplicates": duplicates, "errors": errors}


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


@app.post("/api/import/pdf/ocr-preview")
async def preview_pdf_ocr_endpoint(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDFファイルを選択してください")
    try:
        return preview_pdf_ocr(await file.read(MAX_PDF_BYTES + 1))
    except RuntimeError as error:
        raise HTTPException(503, str(error))
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.post("/api/import/ocr-confirm")
def confirm_ocr_import(request: OCRConfirmRequest):
    items = [item.model_dump() for item in request.scores]
    duplicates = 0
    imported = 0
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT date, exam_name, exam_type, subject FROM scores"
        ).fetchall()
        existing_keys = {
            (row["date"], row["exam_name"], row["exam_type"], row["subject"])
            for row in rows
        }
        for data in items:
            key = (data["date"], data["exam_name"], data["exam_type"], data["subject"])
            if key in existing_keys:
                duplicates += 1
                continue
            existing_keys.add(key)
            data["id"] = str(uuid.uuid4())
            data["created_at"] = datetime.now(timezone.utc).isoformat()
            connection.execute(
                f"INSERT INTO scores ({','.join(SCORE_COLUMNS)}) VALUES ({','.join('?' for _ in SCORE_COLUMNS)})",
                tuple(data[column] for column in SCORE_COLUMNS),
            )
            imported += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise HTTPException(500, "OCR結果の保存に失敗しました。データは保存されていません")
    finally:
        connection.close()
    return {"imported": imported, "duplicates": duplicates}


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
