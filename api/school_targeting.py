from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .main_models import SUBJECTS
from .target_allocator import allocate_subject_targets


class ExamSubjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str
    raw_max_score: float = Field(gt=0, allow_inf_nan=False)
    contribution_max_score: float = Field(gt=0, allow_inf_nan=False)
    source_page: int = Field(ge=1)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if value not in SUBJECTS:
            raise ValueError("選抜対象科目は国語・数学・英語・理科・社会から指定してください")
        return value


class FixedComponentRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    source_page: int = Field(ge=1)


class ScoringAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=80)
    exam_subjects: list[ExamSubjectRule] = Field(min_length=1, max_length=5)
    fixed_components: list[FixedComponentRule] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_components(self):
        subjects = [item.subject for item in self.exam_subjects]
        if len(subjects) != len(set(subjects)):
            raise ValueError("代替方式の学力検査科目が重複しています")
        names = [item.name for item in self.fixed_components]
        if len(names) != len(set(names)):
            raise ValueError("代替方式の固定評価項目名が重複しています")
        return self


class SchoolScoringModel(BaseModel):
    """Source-cited scoring model for one exact admission route."""

    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(pattern=r"^weighted_components_v1$")
    method_label: str = Field(default="基本方式", min_length=1, max_length=80)
    exam_subjects: list[ExamSubjectRule] = Field(min_length=1, max_length=5)
    fixed_components: list[FixedComponentRule] = Field(default_factory=list, max_length=10)
    alternatives: list[ScoringAlternative] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_components(self):
        subjects = [item.subject for item in self.exam_subjects]
        if len(subjects) != len(set(subjects)):
            raise ValueError("学力検査科目が重複しています")
        names = [item.name for item in self.fixed_components]
        if len(names) != len(set(names)):
            raise ValueError("固定評価項目名が重複しています")

        labels = [self.method_label, *(item.label for item in self.alternatives)]
        if len(labels) != len(set(labels)):
            raise ValueError("選抜方式の名称が重複しています")

        primary_subjects = {item.subject: item.raw_max_score for item in self.exam_subjects}
        primary_max = sum(item.contribution_max_score for item in self.exam_subjects) + sum(
            item.max_score for item in self.fixed_components
        )
        for alternative in self.alternatives:
            alternative_subjects = {
                item.subject: item.raw_max_score for item in alternative.exam_subjects
            }
            if alternative_subjects != primary_subjects:
                raise ValueError("比較方式では学力検査科目と素点満点を同一にしてください")
            alternative_max = sum(
                item.contribution_max_score for item in alternative.exam_subjects
            ) + sum(item.max_score for item in alternative.fixed_components)
            if not math.isclose(alternative_max, primary_max, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("比較方式の選抜総合点の満点は同じにしてください")
        return self


class SubjectCurrentScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    current_score: float = Field(ge=0, allow_inf_nan=False)
    priority: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if value not in SUBJECTS:
            raise ValueError("科目は国語・数学・英語・理科・社会から選択してください")
        return value


class SchoolTargetAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    target_total: float = Field(ge=0, allow_inf_nan=False)
    subjects: list[SubjectCurrentScore] = Field(min_length=1, max_length=5)
    fixed_component_scores: dict[str, float] = Field(default_factory=dict)
    alternative_fixed_component_scores: dict[str, dict[str, float]] = Field(default_factory=dict)

    @field_validator("fixed_component_scores", "alternative_fixed_component_scores")
    @classmethod
    def validate_fixed_scores(cls, value):
        score_maps = value.values() if value and all(isinstance(x, dict) for x in value.values()) else [value]
        for score_map in score_maps:
            if any(not math.isfinite(score) or score < 0 for score in score_map.values()):
                raise ValueError("固定評価項目の得点は0以上の有限値で入力してください")
        return value

    @model_validator(mode="after")
    def validate_subjects(self):
        names = [item.subject for item in self.subjects]
        if len(names) != len(set(names)):
            raise ValueError("科目を重複して指定できません")
        return self


def _allocate_one_method(
    label: str,
    exam_rules: list[ExamSubjectRule],
    fixed_rules_list: list[FixedComponentRule],
    request: SchoolTargetAllocationRequest,
    fixed_scores_input: dict[str, float],
) -> dict[str, Any]:
    rules_by_subject = {item.subject: item for item in exam_rules}
    current_by_subject = {item.subject: item for item in request.subjects}
    if set(current_by_subject) != set(rules_by_subject):
        missing = sorted(set(rules_by_subject) - set(current_by_subject))
        extra = sorted(set(current_by_subject) - set(rules_by_subject))
        details = []
        if missing:
            details.append("不足科目：" + "・".join(missing))
        if extra:
            details.append("対象外科目：" + "・".join(extra))
        raise ValueError("選抜方式の対象科目と入力科目が一致しません（" + " / ".join(details) + "）")

    fixed_rules = {item.name: item for item in fixed_rules_list}
    if set(fixed_scores_input) != set(fixed_rules):
        raise ValueError(f"{label}：調査書・面接等の固定評価項目をすべて入力してください")

    fixed_scores: dict[str, float] = {}
    for name, rule in fixed_rules.items():
        score = fixed_scores_input[name]
        if score < 0 or score > rule.max_score:
            raise ValueError(f"{label}：{name}の得点は0〜{rule.max_score:g}点で入力してください")
        fixed_scores[name] = float(score)

    effective_subjects = []
    raw_current: dict[str, float] = {}
    for subject, rule in rules_by_subject.items():
        current = current_by_subject[subject]
        if current.current_score > rule.raw_max_score:
            raise ValueError(
                f"{subject}の現在点は満点（{rule.raw_max_score:g}点）以下にしてください"
            )
        raw_current[subject] = float(current.current_score)
        effective_subjects.append({
            "subject": subject,
            "current_score": (
                current.current_score / rule.raw_max_score * rule.contribution_max_score
            ),
            "max_score": rule.contribution_max_score,
            "weight": current.priority,
        })

    fixed_total = sum(fixed_scores.values())
    exam_max_total = sum(item.contribution_max_score for item in exam_rules)
    exam_current_total = sum(
        raw_current[item.subject] / item.raw_max_score * item.contribution_max_score
        for item in exam_rules
    )
    current_total = fixed_total + exam_current_total
    maximum_with_fixed_scores = fixed_total + exam_max_total
    if request.target_total > maximum_with_fixed_scores:
        raise ValueError(
            f"{label}：入力した調査書等の得点を固定した場合、目標点が到達可能な上限を超えています"
        )

    target_exam_contribution = max(
        exam_current_total,
        request.target_total - fixed_total,
    )
    allocation = allocate_subject_targets(effective_subjects, target_exam_contribution)
    targets = []
    for item in allocation["subjects"]:
        rule = rules_by_subject[item["subject"]]
        target_raw = (
            item["target_score"] / rule.contribution_max_score * rule.raw_max_score
        )
        targets.append({
            "subject": item["subject"],
            "current_score": round(raw_current[item["subject"]], 2),
            "raw_max_score": rule.raw_max_score,
            "target_score": round(min(rule.raw_max_score, target_raw), 2),
            "increase": round(
                max(0, min(rule.raw_max_score, target_raw) - raw_current[item["subject"]]),
                2,
            ),
            "current_contribution": round(item["current_score"], 2),
            "target_contribution": item["target_score"],
            "contribution_max_score": rule.contribution_max_score,
            "target_rate": round(
                min(rule.raw_max_score, target_raw) / rule.raw_max_score * 100, 1
            ),
            "priority": item["weight"],
            "source_page": rule.source_page,
        })

    planned_total = fixed_total + allocation["planned_total"]
    return {
        "method_label": label,
        "model_version": "weighted_components_v1",
        "current_total": round(current_total, 2),
        "requested_total": round(request.target_total, 2),
        "planned_total": round(planned_total, 2),
        "fixed_components": [
            {
                "name": name,
                "score": score,
                "max_score": fixed_rules[name].max_score,
                "source_page": fixed_rules[name].source_page,
            }
            for name, score in fixed_scores.items()
        ],
        "subjects": targets,
        "already_at_or_above_goal": current_total >= request.target_total,
    }


def allocate_school_targets(
    scoring_model: SchoolScoringModel,
    request: SchoolTargetAllocationRequest,
) -> dict[str, Any]:
    methods = [
        (
            scoring_model.method_label,
            scoring_model.exam_subjects,
            scoring_model.fixed_components,
            request.fixed_component_scores,
        )
    ]
    known_alternatives = {item.label for item in scoring_model.alternatives}
    unknown_alternatives = set(request.alternative_fixed_component_scores) - known_alternatives
    if unknown_alternatives:
        raise ValueError("登録されていない比較方式の固定評価項目が入力されています")

    for alternative in scoring_model.alternatives:
        methods.append((
            alternative.label,
            alternative.exam_subjects,
            alternative.fixed_components,
            request.alternative_fixed_component_scores.get(alternative.label, {}),
        ))

    results = []
    successful_results = []
    for label, exam_rules, fixed_rules, fixed_scores in methods:
        try:
            result = _allocate_one_method(label, exam_rules, fixed_rules, request, fixed_scores)
            results.append(result)
            successful_results.append(result)
        except ValueError as error:
            results.append({
                "method_label": label,
                "requested_total": round(request.target_total, 2),
                "error": str(error),
            })
    if not successful_results:
        raise ValueError("登録された全ての選抜方式で計算できません。各方式の入力値と目標点を確認してください")
    best = max(successful_results, key=lambda item: item["current_total"])
    best_current_method = best["method_label"]
    return {
        **best,
        "best_current_method": best_current_method,
        "method_results": results,
        "notice": (
            "登録された確認済み選抜ルールを使った点数計画です。合格可能性や合格を保証するものではありません。"
            "固定評価項目は入力値のまま変化しない前提です。模試の素点と入試本番の得点は同一とは限りません。"
            "複数方式がある場合は各方式の結果を並べて表示します。"
        ),
    }
