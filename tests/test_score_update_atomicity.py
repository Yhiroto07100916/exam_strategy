from fastapi.testclient import TestClient

import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "score-update.sqlite3")
    return TestClient(api.app)


def test_score_update_is_atomic_and_preserves_creation_timestamp(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        original_payload = {
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 60,
            "max_score": 100,
        }
        first = client.post("/api/scores", json=original_payload)
        second = client.post("/api/scores", json={
            **original_payload,
            "date": "2026-10-02",
            "exam_name": "11月模試",
            "score": 75,
        })
        assert first.status_code == 201
        assert second.status_code == 201

        first_id = first.json()["id"]
        created_at = first.json()["created_at"]

        updated_payload = {
            **original_payload,
            "date": "2026-10-03",
            "exam_name": "12月模試",
            "score": 82,
            "deviation": 61.5,
        }
        updated = client.put(f"/api/scores/{first_id}", json=updated_payload)
        assert updated.status_code == 200
        assert updated.json()["created_at"] == created_at
        assert updated.json()["date"] == "2026-10-03"
        assert updated.json()["score"] == 82

        analysis_before_conflict = client.get("/api/analysis").json()
        assert analysis_before_conflict["latest_exam"]["name"] == "12月模試"
        assert analysis_before_conflict["latest_exam"]["total"] == 82
        assert analysis_before_conflict["summary"][0]["latest_score"] == 82

        conflicting_update = client.put(
            f"/api/scores/{first_id}",
            json={
                **updated_payload,
                "date": "2026-10-02",
                "exam_name": "11月模試",
                "score": 90,
            },
        )
        assert conflicting_update.status_code == 409

        saved = {
            row["id"]: row
            for row in client.get("/api/scores").json()
        }
        assert len(saved) == 2
        assert saved[first_id]["date"] == "2026-10-03"
        assert saved[first_id]["exam_name"] == "12月模試"
        assert saved[first_id]["score"] == 82
        assert saved[first_id]["created_at"] == created_at
        assert saved[second.json()["id"]]["score"] == 75

        analysis_after_conflict = client.get("/api/analysis").json()
        assert analysis_after_conflict["latest_exam"] == analysis_before_conflict["latest_exam"]
        assert analysis_after_conflict["summary"] == analysis_before_conflict["summary"]



def test_invalid_score_update_preserves_existing_record_and_analysis(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        payload = {
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 72,
            "max_score": 100,
        }
        created = client.post("/api/scores", json=payload)
        assert created.status_code == 201
        item_id = created.json()["id"]

        before_record = client.get("/api/scores").json()[0]
        before_analysis = client.get("/api/analysis").json()

        invalid_update = client.put(
            f"/api/scores/{item_id}",
            json={**payload, "score": 101},
        )
        assert invalid_update.status_code == 422

        after_records = client.get("/api/scores").json()
        after_analysis = client.get("/api/analysis").json()
        assert after_records == [before_record]
        assert after_analysis == before_analysis
