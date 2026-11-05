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
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pypdf import PdfReader

from .ocr import MAX_PDF_BYTES, MAX_PDF_PAGES, preview_pdf_ocr

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WEB = ROOT / "web"
DB = DATA / "exam_strategy.sqlite3"
from .main_models import is_valid_subject
from .exam_mode import EXAM_MODES, exam_mode_context, get_exam_mode
from .target_routes import router as target_router
from .school_targeting import SchoolScoringModel, SchoolTargetAllocationRequest, allocate_school_targets
MAX_IMPORT_ROWS = 10000

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


@app.middleware("http")
async def select_exam_mode(request: Request, call_next):
    mode = request.headers.get("x-exam-mode", "high_school")
    if mode not in EXAM_MODES:
        return JSONResponse(status_code=400, content={"detail": "受験モードが不正です"})
    token = exam_mode_context.set(mode)
    try:
        return await call_next(request)
    finally:
        exam_mode_context.reset(token)



def db() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    database_path = DB if get_exam_mode() == 'high_school' else DB.with_name('university_' + DB.name)
    connection = sqlite3.connect(database_path)
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
            points REAL, earned_points REAL, exam_type TEXT NOT NULL DEFAULT '模試'
        )
    """)
    question_columns = {row["name"] for row in connection.execute("PRAGMA table_info(questions)").fetchall()}
    if "exam_type" not in question_columns:
        connection.execute("ALTER TABLE questions ADD COLUMN exam_type TEXT NOT NULL DEFAULT '模試'")
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
        if not is_valid_subject(value):
            raise ValueError("選択中の受験モードで利用できない科目です")
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
    exam_type: str = Field(default="模試", min_length=1, max_length=40)
    subject: str
    unit: str = Field(min_length=1, max_length=120)
    correct: bool
    points: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    earned_points: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def validate_optional_date(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return parse_date(value)

    @field_validator("exam_name")
    @classmethod
    def normalize_exam_name(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if not is_valid_subject(value):
            raise ValueError("選択中の受験モードで利用できない科目です")
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

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: dict[str, Any]) -> dict[str, Any]:
        subjects = value.get("subjects", {})
        if not isinstance(subjects, dict):
            raise ValueError("科目別目標はオブジェクトで指定してください")
        if len(subjects) > 20:
            raise ValueError("科目別目標は20科目以内で指定してください")

        for subject, config in subjects.items():
            if not isinstance(subject, str) or not is_valid_subject(subject):
                raise ValueError("選択中の受験モードで利用できない科目です")
            if not isinstance(config, dict):
                raise ValueError(f"{subject}の目標設定が不正です")

            target_score = config.get("target_score")
            max_score = config.get("max_score")
            weight = config.get("weight")

            for field_name, field_value in (
                ("目標点", target_score),
                ("満点", max_score),
                ("優先度", weight),
            ):
                if field_value is None:
                    continue
                if isinstance(field_value, bool):
                    raise ValueError(f"{subject}の{field_name}は数値で指定してください")
                try:
                    number = float(field_value)
                except (TypeError, ValueError, OverflowError):
                    raise ValueError(f"{subject}の{field_name}は数値で指定してください")
                if not math.isfinite(number):
                    raise ValueError(f"{subject}の{field_name}は有限の数値で指定してください")
                if field_name == "目標点" and number < 0:
                    raise ValueError(f"{subject}の目標点は0以上にしてください")
                if field_name == "満点" and number <= 0:
                    raise ValueError(f"{subject}の満点は0より大きくしてください")
                if field_name == "優先度" and not 0 < number <= 10:
                    raise ValueError(f"{subject}の優先度は0より大きく10以下にしてください")

            if target_score is not None and max_score is not None:
                if float(target_score) > float(max_score):
                    raise ValueError(f"{subject}の目標点は満点以下にしてください")

        university = value.get("university")
        if university is not None:
            if not isinstance(university, dict):
                raise ValueError("大学情報の形式が不正です")
            for field_name in ("university_name", "faculty", "department", "admission_method"):
                field_value = university.get(field_name, "")
                if not isinstance(field_value, str) or len(field_value) > 120:
                    raise ValueError(f"大学情報の{field_name}は120文字以内で入力してください")

        return value


class OCRConfirmRequest(BaseModel):
    scores: list[Score] = Field(min_length=1, max_length=100)


class ImportConfirmRequest(BaseModel):
    scores: list[Score] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)



class BackupRestoreRequest(BaseModel):
    format_version: int
    exam_mode: str
    confirm_replace: bool = False
    exported_at: str
    scores: list[dict[str, Any]] = Field(default_factory=list, max_length=50000)
    questions: list[dict[str, Any]] = Field(default_factory=list, max_length=100000)
    settings: dict[str, Any] = Field(default_factory=dict)
    schools: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    school_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)



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


@app.post("/api/scores", status_code=201)
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


def validate_question_exam_reference(
    item: Question,
    existing: sqlite3.Row | None = None,
) -> None:
    has_date = item.date is not None
    has_exam_name = item.exam_name is not None
    if has_date == has_exam_name:
        return
    if existing is not None and (
        item.date == (existing["date"] or None)
        and item.exam_name == (existing["exam_name"] or None)
    ):
        return
    raise HTTPException(
        422,
        "試験別分析を行う場合は実施日と試験名を両方入力してください。"
        "未紐付けの問題として登録する場合は両方空欄にしてください",
    )


@app.post("/api/questions", status_code=201)
def add_question(item: Question):
    validate_question_exam_reference(item)
    data = item.model_dump()
    data["id"] = str(uuid.uuid4())
    data["correct"] = int(data["correct"])
    connection = db()
    try:
        connection.execute(
            """INSERT INTO questions
               (id, date, exam_name, subject, unit, correct, points, earned_points, exam_type)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            tuple(data[key] for key in [
                "id", "date", "exam_name", "subject", "unit",
                "correct", "points", "earned_points", "exam_type"
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
        existing = connection.execute(
            "SELECT date, exam_name FROM questions WHERE id = ?", (item_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(404, "問題データが見つかりません")
        validate_question_exam_reference(item, existing)
        cursor = connection.execute(
            """UPDATE questions SET date=?, exam_name=?, exam_type=?, subject=?, unit=?,
               correct=?, points=?, earned_points=? WHERE id=?""",
            (
                data["date"], data["exam_name"], data["exam_type"], data["subject"], data["unit"],
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


@app.get("/api/backup")
def export_backup():
    connection = db()
    try:
        backup = {
            "format_version": 1,
            "exam_mode": get_exam_mode(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "scores": [dict(row) for row in connection.execute(
                "SELECT * FROM scores ORDER BY date, created_at"
            ).fetchall()],
            "questions": [dict(row) for row in connection.execute(
                "SELECT * FROM questions ORDER BY date, exam_name, subject, unit"
            ).fetchall()],
            "settings": {
                row["key"]: json.loads(row["value"])
                for row in connection.execute("SELECT key, value FROM settings").fetchall()
            },
            "schools": [dict(row) for row in connection.execute(
                "SELECT * FROM schools ORDER BY prefecture, name"
            ).fetchall()],
            "school_rules": [
                {**dict(row), "rule_data": json.loads(row["rule_data"])}
                for row in connection.execute(
                    "SELECT * FROM school_rules ORDER BY admission_year, selection_type"
                ).fetchall()
            ],
        }
    finally:
        connection.close()
    payload = json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="exam_strategy_backup.json"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/backup/restore")
def restore_backup(backup: BackupRestoreRequest, request: Request):
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 20 * 1024 * 1024:
        raise HTTPException(413, "バックアップファイルは20MB以下にしてください")
    if backup.format_version != 1:
        raise HTTPException(422, "対応していないバックアップ形式です")
    if backup.exam_mode != get_exam_mode():
        raise HTTPException(409, "バックアップの受験モードが現在のモードと異なります")
    if backup.confirm_replace is not True:
        raise HTTPException(400, "既存データを置き換える確認が必要です")

    try:
        score_items = []
        for raw in backup.scores:
            item = Score.model_validate(raw)
            data = item.model_dump()
            data["id"] = str(raw["id"])
            data["created_at"] = str(raw["created_at"])
            score_items.append(data)

        question_items = []
        for raw in backup.questions:
            item = Question.model_validate({
                **raw,
                "correct": raw["correct"],
            })
            data = item.model_dump()
            data["correct"] = int(data["correct"])
            data["id"] = str(raw["id"])
            question_items.append(data)

        school_items = []
        for raw in backup.schools:
            item = SchoolCreate.model_validate({
                "name": raw["name"],
                "prefecture": raw["prefecture"],
                "school_type": raw["school_type"],
            })
            school_items.append({
                **item.model_dump(),
                "id": str(raw["id"]),
                "created_at": str(raw["created_at"]),
                "updated_at": str(raw["updated_at"]),
            })

        school_ids = {item["id"] for item in school_items}
        if len(school_ids) != len(school_items):
            raise ValueError("学校IDが重複しています")
        school_keys = [(item["prefecture"], item["name"]) for item in school_items]
        if len(set(school_keys)) != len(school_keys):
            raise ValueError("同じ都県・学校名の学校が重複しています")

        school_rule_items = []
        for raw in backup.school_rules:
            if str(raw["school_id"]) not in school_ids:
                raise ValueError("選抜ルールの参照先学校が存在しません")
            item = SchoolRuleInput.model_validate({
                "admission_year": raw["admission_year"],
                "course": raw["course"],
                "selection_type": raw["selection_type"],
                "verification_status": raw["verification_status"],
                "official_source_url": raw.get("official_source_url"),
                "verified_on": raw.get("verified_on"),
                "rule_data": raw.get("rule_data", {}),
                "notes": raw.get("notes", ""),
            })
            school_rule_items.append({
                **item.model_dump(),
                "id": str(raw["id"]),
                "school_id": str(raw["school_id"]),
                "rule_data": json.dumps(item.rule_data, ensure_ascii=False),
                "created_at": str(raw["created_at"]),
                "updated_at": str(raw["updated_at"]),
            })

        settings_item = Settings.model_validate({
            "profile": backup.settings.get("profile", {}),
            "target": backup.settings.get("target", {}),
        })
        if len({item["id"] for item in score_items}) != len(score_items):
            raise ValueError("成績IDが重複しています")
        if len({item["id"] for item in question_items}) != len(question_items):
            raise ValueError("問題データIDが重複しています")
        if len({item["id"] for item in school_rule_items}) != len(school_rule_items):
            raise ValueError("選抜ルールIDが重複しています")
        school_rule_keys = [
            (item["school_id"], item["admission_year"], item["course"], item["selection_type"])
            for item in school_rule_items
        ]
        if len(set(school_rule_keys)) != len(school_rule_keys):
            raise ValueError("同じ学校・年度・コース・選抜区分の選抜ルールが重複しています")
        if len({
            (item["date"], item["exam_name"], item["exam_type"], item["subject"])
            for item in score_items
        }) != len(score_items):
            raise ValueError("同じ試験・科目の成績が重複しています")
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise HTTPException(422, f"バックアップの内容が不正です: {error}")

    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM school_rules")
        connection.execute("DELETE FROM schools")
        connection.execute("DELETE FROM questions")
        connection.execute("DELETE FROM scores")
        connection.execute("DELETE FROM settings")

        for item in score_items:
            connection.execute(
                f"INSERT INTO scores ({','.join(SCORE_COLUMNS)}) VALUES ({','.join('?' for _ in SCORE_COLUMNS)})",
                tuple(item[key] for key in SCORE_COLUMNS),
            )
        for item in question_items:
            connection.execute(
                """INSERT INTO questions (
                    id, date, exam_name, subject, unit, correct, points,
                    earned_points, exam_type
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                tuple(item[key] for key in [
                    "id", "date", "exam_name", "subject", "unit", "correct",
                    "points", "earned_points", "exam_type",
                ]),
            )
        for key, value in settings_item.model_dump().items():
            connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        for item in school_items:
            connection.execute(
                "INSERT INTO schools VALUES(?,?,?,?,?,?)",
                tuple(item[key] for key in [
                    "id", "name", "prefecture", "school_type", "created_at", "updated_at",
                ]),
            )
        for item in school_rule_items:
            connection.execute(
                """INSERT INTO school_rules (
                    id, school_id, admission_year, course, selection_type,
                    verification_status, official_source_url, verified_on,
                    rule_data, notes, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(item[key] for key in [
                    "id", "school_id", "admission_year", "course", "selection_type",
                    "verification_status", "official_source_url", "verified_on",
                    "rule_data", "notes", "created_at", "updated_at",
                ]),
            )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise HTTPException(422, f"バックアップ内のデータに整合性エラーがあります: {error}")
    except Exception:
        connection.rollback()
        raise HTTPException(500, "復元に失敗しました。既存データは変更されていません")
    finally:
        connection.close()

    return {
        "restored": {
            "scores": len(score_items),
            "questions": len(question_items),
            "schools": len(school_items),
            "school_rules": len(school_rule_items),
        },
        "exam_mode": get_exam_mode(),
    }


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

    exam_type_summary = []
    if score_rows:
        for (exam_type, subject), group in scores_df.groupby(
            ["exam_type", "subject"], sort=True
        ):
            latest = group.iloc[-1]
            exam_type_summary.append({
                "exam_type": str(exam_type),
                "subject": str(subject),
                "count": int(len(group)),
                "average_rate": round(float(group["rate"].mean()), 1),
                "latest_date": str(latest["date"]),
                "latest_exam_name": str(latest["exam_name"]),
                "latest_score": float(latest["score"]),
                "latest_max": float(latest["max_score"]),
                "latest_rate": round(float(latest["rate"]), 1),
            })

    weak_units = []
    if question_rows:
        question_df = pd.DataFrame([dict(row) for row in question_rows])
        for (exam_type, subject, unit), group in question_df.groupby(
            ["exam_type", "subject", "unit"], sort=True
        ):
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
                "exam_type": str(exam_type),
                "subject": subject,
                "unit": unit,
                "questions": int(len(group)),
                "accuracy": round(accuracy, 1),
                "calculation": method,
            })
    weak_units.sort(
        key=lambda item: (item["accuracy"], item["exam_type"], item["subject"], item["unit"])
    )

    unit_trends = []
    dated_questions = [
        row for row in question_rows
        if row["date"] and row["exam_name"]
    ]
    if dated_questions:
        trend_df = pd.DataFrame([dict(row) for row in dated_questions])
        for (exam_date, exam_name, exam_type, subject, unit), group in trend_df.groupby(
            ["date", "exam_name", "exam_type", "subject", "unit"], sort=True
        ):
            has_complete_points = (
                group["points"].notna().all()
                and group["earned_points"].notna().all()
                and float(group["points"].sum()) > 0
            )
            if has_complete_points:
                accuracy = float(
                    group["earned_points"].sum() / group["points"].sum() * 100
                )
                method = "points"
            else:
                accuracy = float(group["correct"].mean() * 100)
                method = "correct_count"
            unit_trends.append({
                "date": str(exam_date),
                "exam_name": str(exam_name),
                "exam_type": str(exam_type),
                "subject": str(subject),
                "unit": str(unit),
                "questions": int(len(group)),
                "accuracy": round(accuracy, 1),
                "calculation": method,
            })
    unit_trends.sort(
        key=lambda item: (
            item["date"], item["exam_name"], item["exam_type"], item["subject"], item["unit"]
        )
    )

    target_subjects = settings.get("target", {}).get("subjects", {})
    target_gaps = []
    for subject_summary in summary:
        target_config = target_subjects.get(subject_summary["subject"], {})
        goal = target_config.get("target_score")
        if goal is None:
            continue
        try:
            goal_value = float(goal)
            target_max = float(target_config.get("max_score") or subject_summary["latest_max"])
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(goal_value)
            or not math.isfinite(target_max)
            or goal_value < 0
            or target_max <= 0
            or goal_value > target_max
        ):
            continue
        current_rate = float(subject_summary["latest_rate"])
        comparable_current = current_rate / 100 * target_max
        target_gaps.append({
            "subject": subject_summary["subject"],
            "current": subject_summary["latest_score"],
            "current_max_score": subject_summary["latest_max"],
            "current_rate": round(current_rate, 1),
            "comparable_current": round(comparable_current, 1),
            "target": goal_value,
            "target_max_score": target_max,
            "gap": round(goal_value - comparable_current, 1),
            "max_score": target_max,
        })

    return {
        "summary": summary,
        "exam_type_summary": exam_type_summary,
        "weak_units": weak_units,
        "unit_trends": unit_trends,
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


def parse_import_table(content: bytes, filename: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, "CSV・Excelファイルは20MB以下にしてください")
    normalized_filename = filename.lower()
    try:
        if normalized_filename.endswith((".xlsx", ".xls")):
            frame = pd.read_excel(io.BytesIO(content))
        elif normalized_filename.endswith(".csv"):
            frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        else:
            raise HTTPException(415, "CSVまたはExcelファイルを選択してください")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "ファイルを読み込めません。形式や内容を確認してください")

    normalized_columns = [
        str(column).replace("\ufeff", "").strip()
        for column in frame.columns
    ]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise HTTPException(422, "列名が重複しています。列名を整理してください")
    frame.columns = normalized_columns

    required = {"subject", "score", "max_score"}
    if not required.issubset(frame.columns):
        raise HTTPException(422, "subject, score, max_score列が必要です")
    if len(frame.index) == 0:
        raise HTTPException(422, "取り込めるデータ行がありません")
    if len(frame.index) > MAX_IMPORT_ROWS:
        raise HTTPException(413, f"一度に取り込めるデータは{MAX_IMPORT_ROWS}行までです")

    errors: list[dict[str, Any]] = []
    parsed: list[dict[str, Any]] = []
    default_name = Path(filename or "取り込み").stem or "取り込み"

    def missing(value: Any) -> bool:
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    def optional_number(row: pd.Series, column: str, integer: bool = False):
        value = row.get(column)
        if missing(value):
            return None
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{column}は有限の数値で入力してください")
        if integer:
            if not number.is_integer():
                raise ValueError(f"{column}は整数で入力してください")
            return int(number)
        return number

    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        try:
            row_warnings = []
            date_value = row.get("date")
            if missing(date_value):
                date_text = date.today().isoformat()
                row_warnings.append("試験日が空欄のため今日の日付を設定しました")
            else:
                date_text = str(date_value)[:10]
            exam_value = row.get("exam_name")
            if missing(exam_value) or not str(exam_value).strip():
                exam_name = default_name
                row_warnings.append("試験名が空欄のためファイル名を設定しました")
            else:
                exam_name = str(exam_value).strip()
            exam_type_value = row.get("exam_type")
            if missing(exam_type_value) or not str(exam_type_value).strip():
                exam_type = "模試"
                row_warnings.append("試験種別が空欄のため「模試」を設定しました")
            else:
                exam_type = str(exam_type_value).strip()
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
            parsed.append({
                "row": row_number,
                "data": payload.model_dump(),
                "warnings": row_warnings,
            })
        except Exception as error:
            errors.append({"row": row_number, "error": str(error)[:300]})

    return parsed, errors, len(frame.index)


def score_import_key(data: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        data["date"],
        data["exam_name"],
        data["exam_type"],
        data["subject"],
    )


def persist_import_scores(items: list[dict[str, Any]]) -> tuple[int, int]:
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
        for item in items:
            data = dict(item)
            key = score_import_key(data)
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
    except Exception as error:
        connection.rollback()
        raise HTTPException(
            500,
            "取り込み中にエラーが発生したため、データは保存されていません",
        ) from error
    finally:
        connection.close()
    return imported, duplicates


@app.post("/api/import/table")
async def import_table(file: UploadFile = File(...)):
    content = await file.read(MAX_PDF_BYTES + 1)
    parsed, errors, total_rows = parse_import_table(
        content, file.filename or "取り込み"
    )
    imported, duplicates = persist_import_scores(
        [item["data"] for item in parsed]
    )
    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total_rows": total_rows,
    }


@app.post("/api/import/table/preview")
async def preview_import_table(file: UploadFile = File(...)):
    content = await file.read(MAX_PDF_BYTES + 1)
    parsed, errors, total_rows = parse_import_table(
        content, file.filename or "取り込み"
    )
    connection = db()
    try:
        rows = connection.execute(
            "SELECT date, exam_name, exam_type, subject FROM scores"
        ).fetchall()
    finally:
        connection.close()

    existing_keys = {
        (row["date"], row["exam_name"], row["exam_type"], row["subject"])
        for row in rows
    }
    records = []
    duplicates = 0
    for item in parsed:
        duplicate = score_import_key(item["data"]) in existing_keys
        if duplicate:
            duplicates += 1
        else:
            existing_keys.add(score_import_key(item["data"]))
        records.append({
            "row": item["row"],
            "data": item["data"],
            "duplicate": duplicate,
            "warnings": item["warnings"],
        })

    return {
        "records": records,
        "errors": errors,
        "duplicates": duplicates,
        "total_rows": total_rows,
    }


@app.post("/api/import/table/confirm")
def confirm_table_import(request: ImportConfirmRequest):
    imported, duplicates = persist_import_scores(
        [item.model_dump() for item in request.scores]
    )
    return {"imported": imported, "duplicates": duplicates}


@app.post("/api/import/pdf")
async def import_pdf(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDFファイルを選択してください")
    content = await file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDFは20MB以下のファイルを選択してください")
    try:
        pages = PdfReader(io.BytesIO(content)).pages
        if len(pages) > MAX_PDF_PAGES:
            raise HTTPException(413, "読み込めるPDFは20ページまでです")
        texts = [page.extract_text() or "" for page in pages]
    except HTTPException:
        raise
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
        return preview_pdf_ocr(await file.read(MAX_PDF_BYTES + 1), mode=get_exam_mode())
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
                      deviation, rank, examinees FROM scores ORDER BY date, exam_name, exam_type, subject""",
            connection,
        )
        questions_df = pd.read_sql_query(
            """SELECT date, exam_name, exam_type, subject, unit, correct, points, earned_points
               FROM questions ORDER BY date, exam_name, exam_type, subject, unit""",
            connection,
        )
        setting_rows = connection.execute(
            "SELECT key, value FROM settings"
        ).fetchall()
    finally:
        connection.close()

    settings = {row["key"]: json.loads(row["value"]) for row in setting_rows}
    profile = settings.get("profile", {})
    target = settings.get("target", {})
    university = target.get("university", {}) if isinstance(target, dict) else {}
    subject_targets = target.get("subjects", {}) if isinstance(target, dict) else {}

    def safe_excel_text(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        first_visible = value.lstrip(" \\t\\r\\n")[:1]
        return "'" + value if first_visible in {"=", "+", "-", "@"} else value

    for frame in (scores_df, questions_df):
        for column in frame.select_dtypes(include=["object"]).columns:
            frame[column] = frame[column].map(safe_excel_text)

    subject_analysis = pd.DataFrame(
        columns=["科目", "記録数", "平均得点率", "最高得点率", "最低得点率"]
    )
    exam_type_analysis = pd.DataFrame(
        columns=["試験種別", "科目", "記録数", "平均得点率", "最新日", "最新試験", "最新得点率"]
    )
    if not scores_df.empty:
        analysis_scores = scores_df.copy()
        analysis_scores["得点率"] = (
            analysis_scores["score"] / analysis_scores["max_score"] * 100
        )
        subject_analysis = (
            analysis_scores.groupby("subject")["得点率"]
            .agg(["count", "mean", "max", "min"])
            .round(1)
            .reset_index()
            .rename(columns={
                "subject": "科目", "count": "記録数", "mean": "平均得点率",
                "max": "最高得点率", "min": "最低得点率",
            })
        )
        exam_rows = []
        for (exam_type, subject), group in analysis_scores.groupby(
            ["exam_type", "subject"], sort=True
        ):
            latest = group.iloc[-1]
            exam_rows.append({
                "試験種別": exam_type,
                "科目": subject,
                "記録数": int(len(group)),
                "平均得点率": round(float(group["得点率"].mean()), 1),
                "最新日": str(latest["date"]),
                "最新試験": str(latest["exam_name"]),
                "最新得点率": round(float(latest["得点率"]), 1),
            })
        exam_type_analysis = pd.DataFrame(exam_rows)

    target_rows = []
    for subject, config in subject_targets.items():
        if not isinstance(config, dict):
            continue
        target_rows.append({
            "科目": subject,
            "目標点": config.get("target_score"),
            "満点": config.get("max_score"),
            "学習優先度": config.get("weight", 1),
        })
    target_df = pd.DataFrame(
        target_rows, columns=["科目", "目標点", "満点", "学習優先度"]
    )

    profile_rows = [
        {"項目": "受験モード", "内容": "大学受験" if get_exam_mode() == "university" else "高校受験"},
        {"項目": "志望大学", "内容": university.get("university_name", "")},
        {"項目": "学部", "内容": university.get("faculty", "")},
        {"項目": "学科", "内容": university.get("department", "")},
        {"項目": "入試方式", "内容": university.get("admission_method", "")},
    ]
    if isinstance(profile, dict):
        for key, value in profile.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                profile_rows.append({"項目": str(key), "内容": value})
    profile_df = pd.DataFrame(profile_rows)

    unit_rows = []
    if not questions_df.empty:
        for (exam_type, subject, unit), group in questions_df.groupby(
            ["exam_type", "subject", "unit"], sort=True
        ):
            complete_points = (
                group["points"].notna().all()
                and group["earned_points"].notna().all()
                and float(group["points"].sum()) > 0
            )
            if complete_points:
                accuracy = float(group["earned_points"].sum() / group["points"].sum() * 100)
                method = "配点ベース"
            else:
                accuracy = float(group["correct"].mean() * 100)
                method = "正答数ベース"
            unit_rows.append({
                "試験種別": exam_type, "科目": subject, "単元": unit,
                "問題数": int(len(group)),
                "正答率・得点率": round(accuracy, 1), "集計方法": method,
            })
    unit_analysis = pd.DataFrame(
        unit_rows,
        columns=["試験種別", "科目", "単元", "問題数", "正答率・得点率", "集計方法"],
    )

    trend_rows = []
    dated_questions = questions_df.dropna(subset=["date", "exam_name"])
    if not dated_questions.empty:
        for (exam_date, exam_name, exam_type, subject, unit), group in dated_questions.groupby(
            ["date", "exam_name", "exam_type", "subject", "unit"], sort=True
        ):
            complete_points = (
                group["points"].notna().all()
                and group["earned_points"].notna().all()
                and float(group["points"].sum()) > 0
            )
            if complete_points:
                accuracy = float(group["earned_points"].sum() / group["points"].sum() * 100)
                method = "配点ベース"
            else:
                accuracy = float(group["correct"].mean() * 100)
                method = "正答数ベース"
            trend_rows.append({
                "日付": str(exam_date), "試験名": str(exam_name),
                "試験種別": str(exam_type), "科目": str(subject), "単元": str(unit),
                "問題数": int(len(group)), "正答率・得点率": round(accuracy, 1),
                "集計方法": method,
            })
    unit_trend_analysis = pd.DataFrame(
        trend_rows,
        columns=["日付", "試験名", "試験種別", "科目", "単元", "問題数", "正答率・得点率", "集計方法"],
    )

    for frame in (
        subject_analysis, exam_type_analysis, target_df, profile_df,
        unit_analysis, unit_trend_analysis,
    ):
        for column in frame.select_dtypes(include=["object"]).columns:
            frame[column] = frame[column].map(safe_excel_text)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        scores_df.to_excel(writer, sheet_name="成績データ", index=False)
        questions_df.to_excel(writer, sheet_name="問題別データ", index=False)
        subject_analysis.to_excel(writer, sheet_name="科目分析", index=False)
        exam_type_analysis.to_excel(writer, sheet_name="試験種別分析", index=False)
        target_df.to_excel(writer, sheet_name="科目別目標", index=False)
        profile_df.to_excel(writer, sheet_name="志望情報", index=False)
        unit_analysis.to_excel(writer, sheet_name="単元分析", index=False)
        unit_trend_analysis.to_excel(writer, sheet_name="単元推移", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                max_length = max(
                    (len(str(cell.value)) for cell in column_cells if cell.value is not None),
                    default=0,
                )
                worksheet.column_dimensions[column_cells[0].column_letter].width = min(
                    max(max_length + 2, 10), 40
                )

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=exam_strategy_report.xlsx"},
    )


if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
