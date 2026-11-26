from fastapi.testclient import TestClient

import api.main as api


def test_already_at_or_above_goal_never_displays_target_below_current(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "target-already-at-goal.sqlite3")

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
        for target_total in (2.0, 2.683):
            response = client.post(
                "/api/targets/allocate",
                json={"target_total": target_total, "subjects": subjects},
            )

            assert response.status_code == 200
            result = response.json()
            assert result["already_at_or_above_goal"] is True

            for item in result["subjects"]:
                assert item["current_score"] <= item["target_score"]
                assert item["target_score"] <= item["max_score"]
                assert item["increase"] >= 0

            target_sum = sum(item["target_score"] for item in result["subjects"])
            assert abs(result["planned_total"] - target_sum) < 1e-9
            assert abs(result["planned_total"] - result["current_total"]) < 1e-9
