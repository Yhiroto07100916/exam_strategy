from fastapi.testclient import TestClient

import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "test.sqlite3")
    return TestClient(api.app)


def test_question_points_must_be_provided_together(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        base = {
            "subject": "数学",
            "unit": "二次関数",
            "correct": True,
        }

        missing_earned_points = client.post(
            "/api/questions",
            json={**base, "points": 5},
        )
        assert missing_earned_points.status_code == 422

        missing_points = client.post(
            "/api/questions",
            json={**base, "earned_points": 3},
        )
        assert missing_points.status_code == 422

        no_point_data = client.post(
            "/api/questions",
            json=base,
        )
        assert no_point_data.status_code == 201
        assert no_point_data.json()["points"] is None
        assert no_point_data.json()["earned_points"] is None

        complete_point_data = client.post(
            "/api/questions",
            json={**base, "points": 5, "earned_points": 3},
        )
        assert complete_point_data.status_code == 201

        over_maximum = client.post(
            "/api/questions",
            json={**base, "points": 5, "earned_points": 6},
        )
        assert over_maximum.status_code == 422


def test_invalid_question_point_update_does_not_change_saved_record(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        original = {
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 5,
            "earned_points": 2,
        }
        created = client.post("/api/questions", json=original)
        assert created.status_code == 201
        item_id = created.json()["id"]

        invalid_update = client.put(
            f"/api/questions/{item_id}",
            json={**original, "earned_points": None},
        )
        assert invalid_update.status_code == 422

        saved = next(
            item for item in client.get("/api/questions").json()
            if item["id"] == item_id
        )
        assert saved["points"] == 5
        assert saved["earned_points"] == 2
        assert saved["unit"] == "二次関数"
