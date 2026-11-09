from fastapi.testclient import TestClient

import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "ocr-confirm.sqlite3")
    return TestClient(api.app)


def test_ocr_confirm_skips_existing_and_in_batch_duplicates(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        existing = {
            "date": "2026-11-04",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 70,
            "max_score": 100,
        }
        created = client.post("/api/scores", json=existing)
        assert created.status_code == 201

        new_score = {
            "date": "2026-11-05",
            "exam_name": "11月確認テスト",
            "exam_type": "定期試験",
            "subject": "英語",
            "score": 60,
            "max_score": 100,
        }
        response = client.post(
            "/api/import/ocr-confirm",
            json={
                "scores": [
                    {**existing, "score": 80},
                    new_score,
                    {**new_score, "score": 90},
                ]
            },
        )

        assert response.status_code == 200
        assert response.json() == {"imported": 1, "duplicates": 2}

        saved = client.get("/api/scores").json()
        assert len(saved) == 2
        by_key = {
            (item["date"], item["exam_name"], item["subject"]): item
            for item in saved
        }
        assert by_key[("2026-11-04", "11月模試", "数学")]["score"] == 70
        assert by_key[("2026-11-05", "11月確認テスト", "英語")]["score"] == 60


def test_ocr_confirm_rejects_invalid_batch_without_partial_writes(
    tmp_path, monkeypatch
):
    with make_client(tmp_path, monkeypatch) as client:
        valid = {
            "date": "2026-11-05",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 70,
            "max_score": 100,
        }
        invalid = {
            "date": "2026-11-05",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "英語",
            "score": 101,
            "max_score": 100,
        }

        response = client.post(
            "/api/import/ocr-confirm",
            json={"scores": [valid, invalid]},
        )

        assert response.status_code == 422
        assert client.get("/api/scores").json() == []
