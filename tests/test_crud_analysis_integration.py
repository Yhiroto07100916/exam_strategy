from fastapi.testclient import TestClient

import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "test.sqlite3")
    return TestClient(api.app)


def test_score_edit_and_delete_refresh_analysis(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post("/api/scores", json={
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 60,
            "max_score": 100,
        })
        second = client.post("/api/scores", json={
            "date": "2026-10-02",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 75,
            "max_score": 100,
        })
        assert first.status_code == 201
        assert second.status_code == 201

        second_id = second.json()["id"]
        first_id = first.json()["id"]

        initial = client.get("/api/analysis").json()
        assert initial["latest_exam"]["name"] == "11月模試"
        assert initial["latest_exam"]["total"] == 75
        assert initial["summary"][0]["latest_score"] == 75

        updated = client.put(f"/api/scores/{second_id}", json={
            "date": "2026-10-03",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 82,
            "max_score": 100,
        })
        assert updated.status_code == 200

        after_update = client.get("/api/analysis").json()
        assert after_update["latest_exam"]["date"] == "2026-10-03"
        assert after_update["latest_exam"]["total"] == 82
        assert after_update["summary"][0]["latest_score"] == 82

        assert client.delete(f"/api/scores/{second_id}").status_code == 204
        after_delete = client.get("/api/analysis").json()
        assert after_delete["latest_exam"]["name"] == "10月模試"
        assert after_delete["latest_exam"]["total"] == 60
        assert after_delete["summary"][0]["latest_score"] == 60

        assert client.delete(f"/api/scores/{first_id}").status_code == 204
        assert client.get("/api/analysis").json() == {
            "summary": [],
            "weak_units": [],
            "latest_exam": None,
            "target_gaps": [],
        }


def test_question_edit_and_delete_refresh_unit_analysis(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post("/api/questions", json={
            "subject": "英語",
            "unit": "関係代名詞",
            "correct": False,
            "points": 10,
            "earned_points": 2,
        })
        second = client.post("/api/questions", json={
            "subject": "英語",
            "unit": "関係代名詞",
            "correct": True,
            "points": 10,
            "earned_points": 10,
        })
        assert first.status_code == 201
        assert second.status_code == 201

        first_id = first.json()["id"]
        second_id = second.json()["id"]

        analysis = client.get("/api/analysis").json()
        assert analysis["summary"] == []
        assert analysis["latest_exam"] is None
        initial = analysis["weak_units"][0]
        assert initial["questions"] == 2
        assert initial["accuracy"] == 60
        assert initial["calculation"] == "points"

        updated = client.put(f"/api/questions/{first_id}", json={
            "subject": "英語",
            "unit": "関係代名詞",
            "correct": True,
            "points": 10,
            "earned_points": 8,
        })
        assert updated.status_code == 200

        after_update = client.get("/api/analysis").json()["weak_units"][0]
        assert after_update["questions"] == 2
        assert after_update["accuracy"] == 90

        assert client.delete(f"/api/questions/{second_id}").status_code == 204
        after_delete = client.get("/api/analysis").json()["weak_units"][0]
        assert after_delete["questions"] == 1
        assert after_delete["accuracy"] == 80

        assert client.delete(f"/api/questions/{first_id}").status_code == 204
        assert client.get("/api/analysis").json()["weak_units"] == []
