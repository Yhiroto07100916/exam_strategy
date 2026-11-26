from fastapi.testclient import TestClient

import api.main as api


def test_ocr_confirm_skips_existing_and_in_batch_duplicates_without_overwriting(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(api, "DB", tmp_path / "ocr-confirm-duplicates.sqlite3")

    with TestClient(api.app) as client:
        existing = {
            "date": "2026-11-20",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 70,
            "max_score": 100,
        }
        created = client.post("/api/scores", json=existing)
        assert created.status_code == 201

        confirmed = client.post(
            "/api/import/ocr-confirm",
            json={
                "scores": [
                    {**existing, "score": 99},
                    {
                        "date": "2026-11-20",
                        "exam_name": "11月模試",
                        "exam_type": "模試",
                        "subject": "英語",
                        "score": 80,
                        "max_score": 100,
                    },
                    {
                        "date": "2026-11-20",
                        "exam_name": "11月模試",
                        "exam_type": "模試",
                        "subject": "英語",
                        "score": 88,
                        "max_score": 100,
                    },
                ]
            },
        )

        assert confirmed.status_code == 200
        assert confirmed.json() == {"imported": 1, "duplicates": 2}

        saved = {
            item["subject"]: item
            for item in client.get("/api/scores").json()
        }
        assert set(saved) == {"数学", "英語"}
        assert saved["数学"]["score"] == 70
        assert saved["英語"]["score"] == 80

        summary = {
            item["subject"]: item
            for item in client.get("/api/analysis").json()["summary"]
        }
        assert summary["数学"]["latest_score"] == 70
        assert summary["英語"]["latest_score"] == 80
