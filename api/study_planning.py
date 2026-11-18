from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StudyPlanGenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_date: str
    availability: dict[int, int] = Field(
        default_factory=lambda: {1: 60, 2: 60, 3: 60, 4: 60, 5: 60, 6: 120, 7: 120}
    )
    session_minutes: int = Field(default=50, ge=20, le=120)

    @field_validator("target_date")
    @classmethod
    def validate_target_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("目標日はYYYY-MM-DD形式で入力してください")
        today = date.today()
        if parsed < today:
            raise ValueError("目標日は今日以降の日付にしてください")
        if parsed > today + timedelta(days=365):
            raise ValueError("計画期間は1年以内にしてください")
        return parsed.isoformat()

    @model_validator(mode="after")
    def validate_availability(self):
        if not self.availability:
            raise ValueError("学習可能な曜日と時間を1日以上設定してください")
        for weekday, minutes in self.availability.items():
            if weekday not in range(1, 8):
                raise ValueError("曜日は1（月）〜7（日）で指定してください")
            if minutes < 0 or minutes > 600:
                raise ValueError("曜日ごとの学習時間は0〜600分で指定してください")
        if not any(self.availability.values()):
            raise ValueError("学習可能な時間を1日以上設定してください")
        return self


class StudyTaskProgressUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: str = Field(pattern="^(pending|completed|skipped)$")
    actual_minutes: int | None = Field(default=None, ge=0, le=600)
    note: str = Field(default="", max_length=500)


def _unit_signals(questions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in questions:
        grouped[(str(item.get("subject", "")), str(item.get("unit", "")),
                 str(item.get("exam_type", "模試")))].append(item)

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (subject, unit, exam_type), items in grouped.items():
        has_points = all(
            item.get("points") is not None and item.get("earned_points") is not None
            for item in items
        ) and sum(float(item.get("points") or 0) for item in items) > 0
        if has_points:
            total = sum(float(item["points"]) for item in items)
            earned = sum(float(item["earned_points"]) for item in items)
            accuracy = earned / total * 100
        else:
            accuracy = sum(bool(item.get("correct")) for item in items) / len(items) * 100
        result[subject].append({
            "unit": unit,
            "exam_type": exam_type,
            "accuracy": round(accuracy, 1),
            "question_count": len(items),
            "confidence": "暫定" if len(items) < 5 else "参考",
        })
    for units in result.values():
        units.sort(key=lambda item: (item["accuracy"], item["unit"]))
    return result


def _score_signals(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scores:
        try:
            maximum = float(item.get("max_score") or 0)
            score = float(item.get("score") or 0)
            if maximum > 0:
                grouped[str(item.get("subject", ""))].append({
                    "date": str(item.get("date", "")),
                    "exam_name": str(item.get("exam_name", "")),
                    "rate": score / maximum * 100,
                })
        except (TypeError, ValueError):
            continue

    result = {}
    for subject, items in grouped.items():
        items.sort(key=lambda item: item["date"], reverse=True)
        recent = items[:3]
        latest_date = recent[0]["date"]
        latest_keys = {
            (item["exam_name"], item["date"]) for item in items
            if item["date"] == latest_date
        }
        result[subject] = {
            "average_rate": round(sum(item["rate"] for item in recent) / len(recent), 1),
            "records": len(items),
            "latest_ambiguous": len(latest_keys) > 1,
        }
    return result


def generate_study_plan(
    scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    target: dict[str, Any],
    subjects: list[str],
    request: StudyPlanGenerateRequest,
    today: date | None = None,
) -> dict[str, Any]:
    """Build a deterministic, evidence-linked monthly/weekly/daily plan.

    Time allocation and dates are computed server-side so an optional AI
    enrichment layer can never exceed the learner's stated availability.
    """
    start = today or date.today()
    finish = date.fromisoformat(request.target_date)
    if finish < start:
        raise ValueError("目標日は開始日以降にしてください")

    score_data = _score_signals(scores)
    unit_data = _unit_signals(questions)
    target_subjects = target.get("subjects", {}) if isinstance(target, dict) else {}

    observed_subjects = list(dict.fromkeys(
        [*score_data.keys(), *unit_data.keys(), *target_subjects.keys()]
    ))
    available_subjects = observed_subjects or list(subjects)
    signals = []
    for subject in available_subjects:
        units = unit_data.get(subject, [])
        weakest = units[:3]
        score = score_data.get(subject)
        target_config = target_subjects.get(subject, {}) if isinstance(target_subjects, dict) else {}
        target_score = target_config.get("target_score") if isinstance(target_config, dict) else None
        max_score = target_config.get("max_score") if isinstance(target_config, dict) else None
        target_gap = 0.0
        if target_score is not None and max_score:
            try:
                target_gap = max(0.0, float(target_score) / float(max_score) * 100 -
                                 (score["average_rate"] if score else 0.0))
            except (TypeError, ValueError, ZeroDivisionError):
                target_gap = 0.0
        weakness = (
            sum(100 - item["accuracy"] for item in weakest) / len(weakest) / 100
            if weakest else 0.25
        )
        score_gap = (
            max(0.0, 75.0 - score["average_rate"]) / 100
            if score else 0.2
        )
        weight = 1.0 + weakness * 2.0 + score_gap + target_gap / 100
        signals.append({
            "subject": subject,
            "weight": round(weight, 3),
            "average_rate": score["average_rate"] if score else None,
            "score_records": score["records"] if score else 0,
            "latest_ambiguous": score["latest_ambiguous"] if score else False,
            "target_gap_points": round(target_gap, 1),
            "weak_units": weakest,
        })

    if not signals:
        raise ValueError("計画対象の科目がありません")

    # Exclude subjects with no evidence only when the mode subject list is empty;
    # otherwise keep all registered subjects so the schedule remains balanced.
    total_weight = sum(item["weight"] for item in signals)
    for item in signals:
        item["share"] = item["weight"] / total_weight

    days = []
    current = start
    while current <= finish:
        minutes = int(request.availability.get(current.isoweekday(), 0))
        if minutes:
            days.append({"date": current.isoformat(), "minutes": minutes})
        current += timedelta(days=1)

    if not days:
        raise ValueError("目標日までに学習可能な日がありません")

    daily_tasks = []
    allocated_by_subject: dict[str, int] = defaultdict(int)
    allocated_by_unit: dict[tuple[str, str], int] = defaultdict(int)
    for day_item in days:
        remaining = day_item["minutes"]
        tasks = []
        while remaining > 0:
            duration = min(request.session_minutes, remaining)
            # Weighted deficit scheduling avoids simply repeating the first subject.
            ideal_so_far = sum(allocated_by_subject.values()) + duration
            chosen = max(
                signals,
                key=lambda item: item["share"] * ideal_so_far -
                allocated_by_subject[item["subject"]]
            )
            units = chosen["weak_units"]
            unit = (
                min(units, key=lambda item: allocated_by_unit[(chosen["subject"], item["unit"])])
                if units else None
            )
            task = {
                "id": str(uuid.uuid4()),
                "subject": chosen["subject"],
                "unit": unit["unit"] if unit else None,
                "title": (f"{unit['unit']}の理解・解き直し" if unit else
                          f"{chosen['subject']}の基礎確認と演習"),
                "instructions": ("間違えた問題を解き直し、解法を自分の言葉で説明する"
                                 if unit else "基本事項を確認してから標準問題に取り組む"),
                "duration_minutes": duration,
                "evidence": {
                    "unit_accuracy": unit["accuracy"] if unit else None,
                    "question_count": unit["question_count"] if unit else 0,
                    "confidence": unit["confidence"] if unit else "成績データなし",
                    "recent_average_rate": chosen["average_rate"],
                    "target_gap_points": chosen["target_gap_points"],
                },
                "status": "pending",
            }
            tasks.append(task)
            daily_tasks.append({**task, "date": day_item["date"]})
            allocated_by_subject[chosen["subject"]] += duration
            if unit:
                allocated_by_unit[(chosen["subject"], unit["unit"])] += duration
            remaining -= duration
        day_item["tasks"] = tasks
        day_item["total_minutes"] = sum(item["duration_minutes"] for item in tasks)

    weeks_by_key: dict[str, dict[str, Any]] = {}
    months_by_key: dict[str, dict[str, Any]] = {}
    for day_item in days:
        day_date = date.fromisoformat(day_item["date"])
        monday = day_date - timedelta(days=day_date.weekday())
        week_key = monday.isoformat()
        month_key = day_date.strftime("%Y-%m")
        if week_key not in weeks_by_key:
            weeks_by_key[week_key] = {
                "id": str(uuid.uuid4()), "week_start": week_key, "days": [],
                "total_minutes": 0, "focus_subjects": [],
            }
        week = weeks_by_key[week_key]
        week["days"].append(day_item)
        week["total_minutes"] += day_item["total_minutes"]
        if month_key not in months_by_key:
            months_by_key[month_key] = {
                "id": str(uuid.uuid4()), "month": month_key, "weeks": [],
                "total_minutes": 0, "focus_subjects": [],
            }
        month = months_by_key[month_key]
        month["total_minutes"] += day_item["total_minutes"]

    for week in weeks_by_key.values():
        used = {task["subject"] for day_item in week["days"] for task in day_item["tasks"]}
        week["focus_subjects"] = sorted(used)
    for month in months_by_key.values():
        month_weeks = [
            week for week in weeks_by_key.values()
            if any(day_item["date"].startswith(month["month"]) for day_item in week["days"])
        ]
        # A calendar week can span two months; include it only once per month
        # and derive month totals from its actual in-month days below.
        month_days = [
            day_item for week in month_weeks for day_item in week["days"]
            if day_item["date"].startswith(month["month"])
        ]
        month["weeks"] = [{
            **week,
            "days": [day_item for day_item in week["days"]
                     if day_item["date"].startswith(month["month"])],
            "total_minutes": sum(
                day_item["total_minutes"] for day_item in week["days"]
                if day_item["date"].startswith(month["month"])
            ),
        } for week in month_weeks]
        month["total_minutes"] = sum(item["total_minutes"] for item in month_days)
        month["focus_subjects"] = sorted({
            task["subject"] for day_item in month_days for task in day_item["tasks"]
        })

    total_minutes = sum(item["total_minutes"] for item in days)
    return {
        "id": str(uuid.uuid4()),
        "title": f"{start.isoformat()}から{finish.isoformat()}までの学習計画",
        "start_date": start.isoformat(),
        "target_date": finish.isoformat(),
        "generation_mode": "data_driven_v1",
        "total_minutes": total_minutes,
        "total_study_days": len(days),
        "session_minutes": request.session_minutes,
        "availability": {str(key): value for key, value in request.availability.items()},
        "subject_signals": signals,
        "months": list(months_by_key.values()),
        "created_at": None,
    }
