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
