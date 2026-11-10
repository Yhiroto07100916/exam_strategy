from fastapi.testclient import TestClient

import api.main as api


def test_deleting_questions_recalculates_unit_analysis_and_trends(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "question-delete-analysis.sqlite3")

    with TestClient(api.app) as client:
        common = {
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
        }
        correct = client.post(
            "/api/questions",
            json={
                **common,
                "correct": True,
                "points": 4,
                "earned_points": 4,
            },
        )
        incorrect = client.post(
            "/api/questions",
            json={
                **common,
                "correct": False,
                "points": 6,
                "earned_points": 0,
            },
        )
        assert correct.status_code == 201
        assert incorrect.status_code == 201

        before = client.get("/api/analysis").json()
        assert before["weak_units"] == [
            {
                "exam_type": "模試",
                "subject": "数学",
                "unit": "二次関数",
                "questions": 2,
                "accuracy": 40.0,
                "calculation": "points",
            }
        ]
        assert len(before["unit_trends"]) == 1
        assert before["unit_trends"][0]["questions"] == 2
        assert before["unit_trends"][0]["accuracy"] == 40.0

        deleted = client.delete(f"/api/questions/{incorrect.json()['id']}")
        assert deleted.status_code == 204

        after_one_delete = client.get("/api/analysis").json()
        assert after_one_delete["weak_units"] == [
            {
                "exam_type": "模試",
                "subject": "数学",
                "unit": "二次関数",
                "questions": 1,
                "accuracy": 100.0,
                "calculation": "points",
            }
        ]
        assert len(after_one_delete["unit_trends"]) == 1
        assert after_one_delete["unit_trends"][0]["questions"] == 1
        assert after_one_delete["unit_trends"][0]["accuracy"] == 100.0
        assert len(client.get("/api/questions").json()) == 1

        deleted_last = client.delete(f"/api/questions/{correct.json()['id']}")
        assert deleted_last.status_code == 204

        after_last_delete = client.get("/api/analysis").json()
        assert after_last_delete["weak_units"] == []
        assert after_last_delete["unit_trends"] == []
        assert client.get("/api/questions").json() == []
        assert client.delete(
            f"/api/questions/{correct.json()['id']}"
        ).status_code == 404
