import pytest
from fastapi.testclient import TestClient

import api.main as api


@pytest.mark.parametrize(
    "question_reference",
    [
        {"date": "2026-11-02", "exam_name": None},
        {"date": None, "exam_name": "11月模試"},
    ],
)
def test_backup_restore_rejects_incomplete_question_exam_reference_without_replacing_data(
    tmp_path, monkeypatch, question_reference
):
    monkeypatch.setattr(api, "DB", tmp_path / "backup-validation.sqlite3")

    with TestClient(api.app) as client:
        existing_score = client.post(
            "/api/scores",
            json={
                "date": "2026-11-01",
                "exam_name": "既存模試",
                "subject": "数学",
                "score": 60,
                "max_score": 100,
            },
        )
        assert existing_score.status_code == 201

        existing_question = client.post(
            "/api/questions",
            json={
                "date": "2026-11-01",
                "exam_name": "既存模試",
                "subject": "数学",
                "unit": "二次関数",
                "correct": True,
            },
        )
        assert existing_question.status_code == 201

        backup = {
            "format_version": 1,
            "exam_mode": "high_school",
            "confirm_replace": True,
            "exported_at": "2026-11-17T00:00:00+00:00",
            "scores": [],
            "questions": [
                {
                    "id": "incomplete-question-reference",
                    **question_reference,
                    "subject": "数学",
                    "unit": "図形",
                    "correct": True,
                    "exam_type": "模試",
                }
            ],
            "settings": {},
            "schools": [],
            "school_rules": [],
        }

        response = client.post("/api/backup/restore", json=backup)

        assert response.status_code == 422
        assert client.get("/api/scores").json() == [existing_score.json()]
        assert client.get("/api/questions").json() == [existing_question.json()]
