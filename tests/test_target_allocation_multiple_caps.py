from fastapi.testclient import TestClient

import api.main as api


def test_target_allocation_redistributes_after_multiple_subjects_reach_maximum(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "target-allocation.sqlite3")

    with TestClient(api.app) as client:
        response = client.post(
            "/api/targets/allocate",
            json={
                "target_total": 230,
                "subjects": [
                    {
                        "subject": "数学",
                        "current_score": 95,
                        "max_score": 100,
                        "weight": 5,
                    },
                    {
                        "subject": "英語",
                        "current_score": 95,
                        "max_score": 100,
                        "weight": 3,
                    },
                    {
                        "subject": "理科",
                        "current_score": 0,
                        "max_score": 100,
                        "weight": 1,
                    },
                ],
            },
        )

    assert response.status_code == 200
    result = response.json()
    targets = {item["subject"]: item for item in result["subjects"]}

    assert targets["数学"]["target_score"] == 100
    assert targets["英語"]["target_score"] == 100
    assert targets["理科"]["target_score"] == 30
    assert all(
        item["current_score"] <= item["target_score"] <= item["max_score"]
        for item in result["subjects"]
    )
    assert sum(item["target_score"] for item in result["subjects"]) == 230
    assert result["planned_total"] == 230
    assert result["already_at_or_above_goal"] is False


def test_target_allocation_preserves_bounds_when_scores_have_more_than_two_decimals(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "target-allocation-precision.sqlite3")

    with TestClient(api.app) as client:
        response = client.post(
            "/api/targets/allocate",
            json={
                "target_total": 1.006,
                "subjects": [
                    {
                        "subject": "数学",
                        "current_score": 1.006,
                        "max_score": 1.006,
                        "weight": 1,
                    },
                    {
                        "subject": "英語",
                        "current_score": 0,
                        "max_score": 1,
                        "weight": 1,
                    },
                ],
            },
        )

    assert response.status_code == 200
    result = response.json()
    math = next(item for item in result["subjects"] if item["subject"] == "数学")

    assert math["current_score"] == 1.006
    assert math["target_score"] == 1.006
    assert math["max_score"] == 1.006
    assert math["current_score"] <= math["target_score"] <= math["max_score"]
    assert result["planned_total"] == sum(
        item["target_score"] for item in result["subjects"]
    )


def test_target_allocation_cent_reconciliation_never_drops_below_raw_current_score(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "target-allocation-reconciliation.sqlite3")

    subjects = [
        {
            "subject": "数学",
            "current_score": 0.949,
            "max_score": 100,
            "weight": 6.77,
        },
        {
            "subject": "英語",
            "current_score": 1.734,
            "max_score": 100,
            "weight": 0.14,
        },
    ]

    with TestClient(api.app) as client:
        response = client.post(
            "/api/targets/allocate",
            json={"target_total": 2.763774, "subjects": subjects},
        )

    assert response.status_code == 200
    result = response.json()
    targets = {item["subject"]: item for item in result["subjects"]}

    assert targets["英語"]["target_score"] >= 1.734
    assert targets["数学"]["target_score"] >= 0.949
    assert all(
        subject["current_score"] <= subject["target_score"] <= subject["max_score"]
        for subject in result["subjects"]
    )
    assert result["planned_total"] == sum(
        subject["target_score"] for subject in result["subjects"]
    )
