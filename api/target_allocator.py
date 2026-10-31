from __future__ import annotations

from typing import Any


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
    for item in subjects:
        current = float(item["current_score"])
        maximum = float(item["max_score"])
        goal = min(maximum, current + allocations[item["subject"]])
        result.append({
            "subject": item["subject"],
            "current_score": round(current, 2),
            "target_score": round(goal, 2),
            "increase": round(goal - current, 2),
            "max_score": round(maximum, 2),
            "target_rate": round(goal / maximum * 100, 1),
            "weight": float(item["weight"]),
        })

    allocated_total = sum(item["target_score"] for item in result)
    return {
        "current_total": round(current_total, 2),
        "requested_total": round(float(target_total), 2),
        "planned_total": round(allocated_total, 2),
        "maximum_total": round(maximum_total, 2),
        "already_at_or_above_goal": current_total >= target_total,
        "subjects": result,
        "method": "weighted_headroom",
        "notice": "重みは学習上の優先度です。学校の公式配点・合格可能性を示すものではありません。",
    }
