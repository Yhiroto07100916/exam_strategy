from __future__ import annotations

from typing import Any


def _display_score(
    value: float, *, minimum: float | None = None, maximum: float | None = None
) -> float:
    """Round to cents unless rounding would violate a real score boundary."""
    rounded = round(value, 2)
    if minimum is not None and rounded < minimum - 1e-9:
        return value
    if maximum is not None and rounded > maximum + 1e-9:
        return value
    return rounded


def _display_total(value: float) -> float:
    rounded = round(value, 2)
    return rounded if abs(value - rounded) < 1e-9 else value


def allocate_subject_targets(
    subjects: list[dict[str, Any]], target_total: float
) -> dict[str, Any]:
    """Allocate a total-score goal across subjects using weighted headroom.

    Weights express relative improvement priority, not school admission weights.
    The algorithm never assigns more than a subject's maximum score.
    """
    current_total = sum(float(item["current_score"]) for item in subjects)
    maximum_total = sum(float(item["max_score"]) for item in subjects)
    if target_total > maximum_total:
        raise ValueError("総合目標点は全科目の満点合計以下にしてください")

    planned_total = max(current_total, float(target_total))
    required = planned_total - current_total
    allocations = {item["subject"]: 0.0 for item in subjects}
    active = {
        item["subject"]: item
        for item in subjects
        if float(item["max_score"]) - float(item["current_score"]) > 0
    }

    while required > 1e-9 and active:
        total_weight = sum(float(item["weight"]) for item in active.values())
        if total_weight <= 0:
            break
        distributed = 0.0
        exhausted: list[str] = []
        for name, item in active.items():
            capacity = (
                float(item["max_score"])
                - float(item["current_score"])
                - allocations[name]
            )
            share = required * float(item["weight"]) / total_weight
            addition = min(capacity, share)
            allocations[name] += addition
            distributed += addition
            if capacity - addition <= 1e-9:
                exhausted.append(name)
        required -= distributed
        for name in exhausted:
            active.pop(name, None)
        if distributed <= 1e-9:
            break

    result = []
    exact_goals: dict[str, float] = {}
    for item in subjects:
        current = float(item["current_score"])
        maximum = float(item["max_score"])
        goal = min(maximum, current + allocations[item["subject"]])
        exact_goals[item["subject"]] = goal
        displayed_current = _display_score(current, minimum=0, maximum=maximum)
        displayed_goal = _display_score(
            goal, minimum=current, maximum=maximum
        )
        displayed_maximum = (
            round(maximum, 2) if abs(maximum - round(maximum, 2)) < 1e-9 else maximum
        )
        result.append({
            "subject": item["subject"],
            "current_score": displayed_current,
            "target_score": displayed_goal,
            "increase": round(displayed_goal - displayed_current, 2),
            "max_score": displayed_maximum,
            "target_rate": round(displayed_goal / maximum * 100, 1),
            "weight": float(item["weight"]),
        })

    # Reconcile ordinary cent-rounding differences without crossing real bounds.
    current_display_total = sum(item["current_score"] for item in result)
    desired_total = max(round(planned_total, 2), current_display_total)
    allocated_total = sum(item["target_score"] for item in result)
    residual = round(desired_total - allocated_total, 2)
    subject_inputs = {item["subject"]: item for item in subjects}

    while abs(residual) >= 0.01:
        if residual > 0:
            candidates = [
                item for item in result
                if item["target_score"] + 0.01
                <= float(subject_inputs[item["subject"]]["max_score"]) + 1e-9
            ]
            candidates.sort(
                key=lambda item: exact_goals[item["subject"]] - item["target_score"],
                reverse=True,
            )
            adjustment = 0.01
        else:
            candidates = [
                item for item in result
                if item["target_score"] - 0.01
                >= float(subject_inputs[item["subject"]]["current_score"]) - 1e-9
            ]
            candidates.sort(
                key=lambda item: exact_goals[item["subject"]] - item["target_score"]
            )
            adjustment = -0.01

        if not candidates:
            break

        item = candidates[0]
        item["target_score"] = round(item["target_score"] + adjustment, 2)
        item["increase"] = round(
            item["target_score"] - item["current_score"], 2
        )
        maximum = float(subject_inputs[item["subject"]]["max_score"])
        item["target_rate"] = round(item["target_score"] / maximum * 100, 1)
        allocated_total = sum(entry["target_score"] for entry in result)
        residual = round(desired_total - allocated_total, 2)

    return {
        "current_total": _display_total(current_total),
        "requested_total": _display_total(float(target_total)),
        "planned_total": _display_total(allocated_total),
        "maximum_total": _display_total(maximum_total),
        "already_at_or_above_goal": current_total >= target_total,
        "subjects": result,
        "method": "weighted_headroom",
        "notice": "重みは学習上の優先度です。学校の公式配点・合格可能性を示すものではありません。",
    }
