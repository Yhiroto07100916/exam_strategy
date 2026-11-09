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
