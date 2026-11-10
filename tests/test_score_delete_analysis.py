from fastapi.testclient import TestClient

import api.main as api


def test_deleting_latest_score_refreshes_analysis_and_preserves_questions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "score-delete-analysis.sqlite3")

    with TestClient(api.app) as client:
        settings = client.put(
            "/api/settings",
            json={
                "profile": {},
                "target": {
                    "subjects": {
                        "英語": {"target_score": 80, "max_score": 100}
                    }
                },
            },
        )
        assert settings.status_code == 200

        older = client.post(
            "/api/scores",
            json={
                "date": "2026-10-01",
                "exam_name": "10月模試",
                "exam_type": "模試",
                "subject": "英語",
                "score": 60,
                "max_score": 100,
            },
        )
        latest = client.post(
            "/api/scores",
            json={
                "date": "2026-11-01",
                "exam_name": "11月模試",
                "exam_type": "模試",
                "subject": "英語",
                "score": 75,
                "max_score": 100,
            },
        )
        question = client.post(
            "/api/questions",
            json={
                "date": "2026-11-01",
                "exam_name": "11月模試",
                "exam_type": "模試",
                "subject": "英語",
                "unit": "関係代名詞",
                "correct": False,
                "points": 4,
                "earned_points": 0,
            },
        )
        assert older.status_code == 201
        assert latest.status_code == 201
        assert question.status_code == 201

        before = client.get("/api/analysis").json()
        before_subject = next(
            item for item in before["summary"] if item["subject"] == "英語"
        )
        assert before_subject["count"] == 2
        assert before_subject["latest_score"] == 75
        assert before["latest_exam"]["name"] == "11月模試"
        assert before["target_gaps"][0]["gap"] == 5

        deleted = client.delete(f"/api/scores/{latest.json()['id']}")
        assert deleted.status_code == 204

        after = client.get("/api/analysis").json()
        after_subject = next(
            item for item in after["summary"] if item["subject"] == "英語"
        )
        assert after_subject["count"] == 1
        assert after_subject["latest_score"] == 60
        assert after_subject["latest_date"] == "2026-10-01"
        assert after["latest_exam"]["name"] == "10月模試"
        assert after["target_gaps"][0]["gap"] == 20

        saved_questions = client.get("/api/questions").json()
        assert len(saved_questions) == 1
        assert saved_questions[0]["id"] == question.json()["id"]
        assert after["weak_units"] == [
            {
                "exam_type": "模試",
                "subject": "英語",
                "unit": "関係代名詞",
                "questions": 1,
                "accuracy": 0.0,
                "calculation": "points",
            }
        ]
        assert len(after["unit_trends"]) == 1
        assert after["unit_trends"][0]["exam_name"] == "11月模試"

        deleted_last = client.delete(f"/api/scores/{older.json()['id']}")
        assert deleted_last.status_code == 204

        empty_score_analysis = client.get("/api/analysis").json()
        assert empty_score_analysis["summary"] == []
        assert empty_score_analysis["latest_exam"] is None
        assert empty_score_analysis["latest_exam_ambiguous"] is False
        assert empty_score_analysis["target_gaps"] == []
        assert len(empty_score_analysis["weak_units"]) == 1
        assert len(empty_score_analysis["unit_trends"]) == 1
