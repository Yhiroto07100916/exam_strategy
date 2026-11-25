from fastapi.testclient import TestClient

import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "question-update.sqlite3")
    return TestClient(api.app)


def test_invalid_question_update_preserves_record_and_unit_analysis(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        original = {
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 4,
        }
        created = client.post("/api/questions", json=original)
        assert created.status_code == 201
        item_id = created.json()["id"]

        before_questions = client.get("/api/questions").json()
        before_analysis = client.get("/api/analysis").json()
        assert before_analysis["weak_units"][0]["unit"] == "二次関数"
        assert before_analysis["weak_units"][0]["accuracy"] == 40.0
        assert before_analysis["unit_trends"][0]["unit"] == "二次関数"

        invalid_update = client.put(
            f"/api/questions/{item_id}",
            json={
                **original,
                "unit": "図形",
                "correct": True,
                "earned_points": 11,
            },
        )
        assert invalid_update.status_code == 422

        assert client.get("/api/questions").json() == before_questions
        assert client.get("/api/analysis").json() == before_analysis
