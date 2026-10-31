from fastapi.testclient import TestClient
import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "test.sqlite3")
    return TestClient(api.app)


def test_health_and_empty_state(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/analysis").json() == {
            "summary": [], "weak_units": [], "latest_exam": None, "target_gaps": []
        }


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
        assert client.post("/api/scores", json={**payload, "date": "2026/10/01"}).status_code == 422
        assert client.delete(f"/api/scores/{item_id}").status_code == 204
        assert client.delete(f"/api/scores/{item_id}").status_code == 404


def test_latest_exam_is_not_mixed_with_other_exam_on_same_date(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        for exam, subject, score in [
            ("模試A", "国語", 70), ("模試A", "数学", 60), ("模試B", "国語", 90)
        ]:
            response = client.post("/api/scores", json={
                "date": "2026-10-01", "exam_name": exam, "subject": subject,
                "score": score, "max_score": 100
            })
            assert response.status_code == 201
        latest = client.get("/api/analysis").json()["latest_exam"]
        assert latest["name"] == "模試B"
        assert latest["total"] == 90
        assert latest["max_total"] == 100
        assert latest["subjects_count"] == 1


def test_analysis_uses_correct_fallback_when_point_data_is_incomplete(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        client.post("/api/scores", json={
            "date": "2026-10-01", "exam_name": "10月模試", "subject": "英語",
            "score": 60, "max_score": 100, "deviation": 52
        })
        for correct, points, earned in [(True, 4, 4), (False, None, None)]:
            client.post("/api/questions", json={
                "date": "2026-10-01", "exam_name": "10月模試", "subject": "英語",
                "unit": "関係代名詞", "correct": correct,
                "points": points, "earned_points": earned
            })
        client.put("/api/settings", json={"profile": {}, "target": {
            "subjects": {"英語": {"target_score": 75}}
        }})
        result = client.get("/api/analysis").json()
        assert result["summary"][0]["latest_rate"] == 60
        assert result["weak_units"][0]["accuracy"] == 50
        assert result["weak_units"][0]["calculation"] == "correct_count"
        assert result["target_gaps"][0]["gap"] == 15


def test_question_validation_and_excel_report(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        invalid = client.post("/api/questions", json={
            "subject": "英語", "unit": "文法", "correct": True,
            "points": 2, "earned_points": 3
        })
        assert invalid.status_code == 422
        response = client.get("/api/reports/excel")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content[:2] == b"PK"


def test_csv_import(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = 'date,exam_name,subject,score,max_score\n2026-10-01,10月模試,国語,68,100\n'
        response = client.post(
            '/api/import/table',
            files={'file': ('scores.csv', csv_data.encode('utf-8-sig'), 'text/csv')}
        )
        assert response.status_code == 200
        assert response.json()['imported'] == 1
        assert response.json()['errors'] == []
        assert len(client.get('/api/scores').json()) == 1


def test_question_delete(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        item = client.post("/api/questions", json={
            "subject": "英語", "unit": "仮定法", "correct": False
        }).json()
        assert client.delete("/api/questions/" + item["id"]).status_code == 204
        assert client.delete("/api/questions/" + item["id"]).status_code == 404


def test_weighted_subject_target_allocation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/targets/allocate", json={
            "target_total": 160,
            "subjects": [
                {"subject": "数学", "current_score": 60, "max_score": 100, "weight": 2},
                {"subject": "英語", "current_score": 70, "max_score": 100, "weight": 1},
            ],
        })
        assert response.status_code == 200
        result = response.json()
        assert result["current_total"] == 130
        assert result["planned_total"] == 160
        targets = {item["subject"]: item for item in result["subjects"]}
        assert targets["数学"]["target_score"] == 80
        assert targets["英語"]["target_score"] == 80
        assert targets["数学"]["increase"] == 20
        assert targets["英語"]["increase"] == 10
        assert "合格可能性" in result["notice"]


def test_target_allocation_respects_subject_maximum_and_validation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        capped = client.post("/api/targets/allocate", json={
            "target_total": 160,
            "subjects": [
                {"subject": "数学", "current_score": 95, "max_score": 100, "weight": 2},
                {"subject": "英語", "current_score": 50, "max_score": 100, "weight": 1},
            ],
        })
        assert capped.status_code == 200
        targets = {item["subject"]: item for item in capped.json()["subjects"]}
        assert targets["数学"]["target_score"] == 100
        assert targets["英語"]["target_score"] == 60

        too_high = client.post("/api/targets/allocate", json={
            "target_total": 201,
            "subjects": [
                {"subject": "数学", "current_score": 50, "max_score": 100},
                {"subject": "英語", "current_score": 50, "max_score": 100},
            ],
        })
        assert too_high.status_code == 422

        duplicate = client.post("/api/targets/allocate", json={
            "target_total": 100,
            "subjects": [
                {"subject": "数学", "current_score": 50, "max_score": 100},
                {"subject": "数学", "current_score": 50, "max_score": 100},
            ],
        })
        assert duplicate.status_code == 422
