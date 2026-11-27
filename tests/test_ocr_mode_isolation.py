from fastapi.testclient import TestClient

import api.main as api


def test_ocr_confirm_isolated_by_exam_mode_and_keeps_reviewed_values(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "ocr-mode-isolation.sqlite3")

    with TestClient(api.app) as client:
        reviewed_candidate = {
            "date": "2026-11-27",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "英語",
            "max_score": 100,
        }

        high_school_payload = {
            **reviewed_candidate,
            "score": 83,
            "deviation": 58.2,
        }
        high_school_result = client.post(
            "/api/import/ocr-confirm",
            json={"scores": [high_school_payload]},
        )
        assert high_school_result.status_code == 200
        assert high_school_result.json() == {"imported": 1, "duplicates": 0}

        university_payload = {
            **reviewed_candidate,
            "score": 91,
            "deviation": 65.3,
        }
        university_headers = {"X-Exam-Mode": "university"}
        university_result = client.post(
            "/api/import/ocr-confirm",
            headers=university_headers,
            json={"scores": [university_payload]},
        )
        assert university_result.status_code == 200
        assert university_result.json() == {"imported": 1, "duplicates": 0}

        high_school_scores = client.get("/api/scores").json()
        university_scores = client.get(
            "/api/scores", headers=university_headers
        ).json()
        assert len(high_school_scores) == 1
        assert len(university_scores) == 1
        assert high_school_scores[0]["score"] == 83
        assert high_school_scores[0]["deviation"] == 58.2
        assert university_scores[0]["score"] == 91
        assert university_scores[0]["deviation"] == 65.3

        high_school_summary = client.get("/api/analysis").json()["summary"]
        university_summary = client.get(
            "/api/analysis", headers=university_headers
        ).json()["summary"]
        assert high_school_summary[0]["latest_score"] == 83
        assert university_summary[0]["latest_score"] == 91
