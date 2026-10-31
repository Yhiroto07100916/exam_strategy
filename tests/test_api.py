from fastapi.testclient import TestClient
import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "test.sqlite3")
    return TestClient(api.app)


def test_health_and_empty_state(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        result = client.get("/api/analysis").json()
        assert result == {"summary": [], "weak_units": [], "latest_exam": None, "target_gaps": []}


def test_score_crud_and_validation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        payload = {
            "date": "2026-10-01", "exam_name": "10月模試", "exam_type": "模試",
            "subject": "数学", "score": 72, "max_score": 100, "deviation": 58.4
        }
        created = client.post("/api/scores", json=payload)
        assert created.status_code == 201
        item_id = created.json()["id"]
        assert len(client.get("/api/scores").json()) == 1
        assert client.post("/api/scores", json={**payload, "score": 101}).status_code == 422
        assert client.post("/api/scores", json={**payload, "subject": "音楽"}).status_code == 422
        assert client.delete(f"/api/scores/{item_id}").status_code == 204
        assert client.delete(f"/api/scores/{item_id}").status_code == 404


def test_analysis_uses_question_accuracy_and_target_gap(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        client.post("/api/scores", json={
            "date": "2026-10-01", "exam_name": "10月模試", "subject": "英語",
            "score": 60, "max_score": 100, "deviation": 52
        })
        client.post("/api/questions", json={
            "date": "2026-10-01", "exam_name": "10月模試", "subject": "英語",
            "unit": "関係代名詞", "correct": False, "points": 4, "earned_points": 0
        })
        client.put("/api/settings", json={"profile": {}, "target": {
            "subjects": {"英語": {"target_score": 75}}
        }})
        result = client.get("/api/analysis").json()
        assert result["summary"][0]["latest_rate"] == 60
        assert result["weak_units"][0]["accuracy"] == 0
        assert result["target_gaps"][0]["gap"] == 15


def test_excel_report_download(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/reports/excel")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"
