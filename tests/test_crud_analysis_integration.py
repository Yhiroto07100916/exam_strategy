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
            "exam_type_summary": [],
            "weak_units": [],
            "unit_trends": [],
            "latest_exam": None,
            "latest_exam_ambiguous": False,
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


def test_unit_trends_are_separated_by_exam_and_ignore_undated_legacy_rows(
    tmp_path, monkeypatch
):
    with make_client(tmp_path, monkeypatch) as client:
        rows = [
            {
                "date": "2026-10-01",
                "exam_name": "10月模試",
                "subject": "数学",
                "unit": "二次関数",
                "correct": True,
                "points": 10,
                "earned_points": 8,
            },
            {
                "date": "2026-10-01",
                "exam_name": "10月模試",
                "subject": "数学",
                "unit": "二次関数",
                "correct": False,
                "points": 10,
                "earned_points": 4,
            },
            {
                "date": "2026-11-01",
                "exam_name": "11月模試",
                "subject": "数学",
                "unit": "二次関数",
                "correct": True,
                "points": 10,
                "earned_points": 10,
            },
            {
                "date": None,
                "exam_name": None,
                "subject": "数学",
                "unit": "二次関数",
                "correct": False,
                "points": None,
                "earned_points": None,
            },
        ]
        for row in rows:
            response = client.post("/api/questions", json=row)
            assert response.status_code == 201

        result = client.get("/api/analysis").json()
        trends = result["unit_trends"]
        assert len(trends) == 2
        assert trends[0] == {
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "questions": 2,
            "accuracy": 60.0,
            "calculation": "points",
        }
        assert trends[1]["exam_name"] == "11月模試"
        assert trends[1]["accuracy"] == 100.0
        assert trends[1]["questions"] == 1

        # Legacy rows without an exam/date remain in the overall unit aggregate.
        assert result["weak_units"][0]["questions"] == 4


def test_unit_trends_keep_same_day_exams_separate(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        for exam_name, earned in [("午前模試", 8), ("午後模試", 4)]:
            response = client.post("/api/questions", json={
                "date": "2026-11-01",
                "exam_name": exam_name,
                "exam_type": "模試",
                "subject": "数学",
                "unit": "二次関数",
                "correct": earned > 0,
                "points": 10,
                "earned_points": earned,
            })
            assert response.status_code == 201

        trends = client.get("/api/analysis").json()["unit_trends"]
        assert len(trends) == 2
        assert {item["exam_name"] for item in trends} == {"午前模試", "午後模試"}
        assert {item["accuracy"] for item in trends} == {40.0, 80.0}

def test_question_edit_moves_record_between_exam_unit_trends(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post("/api/questions", json={
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 2,
        })
        assert created.status_code == 201
        item_id = created.json()["id"]

        before = client.get("/api/analysis").json()
        assert len(before["weak_units"]) == 1
        assert before["weak_units"][0]["unit"] == "二次関数"
        assert before["weak_units"][0]["accuracy"] == 20.0
        assert before["unit_trends"][0]["exam_name"] == "10月模試"

        updated = client.put(f"/api/questions/{item_id}", json={
            "date": "2026-11-01",
            "exam_name": "11月定期考査",
            "exam_type": "定期考査",
            "subject": "数学",
            "unit": "図形",
            "correct": True,
            "points": 10,
            "earned_points": 9,
        })
        assert updated.status_code == 200

        after = client.get("/api/analysis").json()
        assert after["weak_units"] == [{
            "exam_type": "定期考査",
            "subject": "数学",
            "unit": "図形",
            "questions": 1,
            "accuracy": 90.0,
            "calculation": "points",
        }]
        assert after["unit_trends"] == [{
            "date": "2026-11-01",
            "exam_name": "11月定期考査",
            "exam_type": "定期考査",
            "subject": "数学",
            "unit": "図形",
            "questions": 1,
            "accuracy": 90.0,
            "calculation": "points",
        }]

        deleted = client.delete(f"/api/questions/{item_id}")
        assert deleted.status_code == 204
        final = client.get("/api/analysis").json()
        assert final["weak_units"] == []
        assert final["unit_trends"] == []


def test_score_and_question_crud_are_isolated_between_exam_modes(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        university_headers = {"X-Exam-Mode": "university"}

        high_school_score = client.post("/api/scores", json={
            "date": "2026-11-20",
            "exam_name": "高校受験模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 72,
            "max_score": 100,
        })
        high_school_question = client.post("/api/questions", json={
            "date": "2026-11-20",
            "exam_name": "高校受験模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 3,
        })
        university_score = client.post(
            "/api/scores",
            headers=university_headers,
            json={
                "date": "2026-11-21",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "score": 140,
                "max_score": 200,
            },
        )
        university_question = client.post(
            "/api/questions",
            headers=university_headers,
            json={
                "date": "2026-11-21",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "unit": "数列",
                "correct": False,
                "points": 10,
                "earned_points": 4,
            },
        )

        assert high_school_score.status_code == 201
        assert high_school_question.status_code == 201
        assert university_score.status_code == 201
        assert university_question.status_code == 201

        high_school_score_id = high_school_score.json()["id"]
        high_school_question_id = high_school_question.json()["id"]
        university_score_id = university_score.json()["id"]
        university_question_id = university_question.json()["id"]

        assert [row["id"] for row in client.get("/api/scores").json()] == [
            high_school_score_id
        ]
        assert [row["id"] for row in client.get("/api/questions").json()] == [
            high_school_question_id
        ]
        assert [
            row["id"]
            for row in client.get("/api/scores", headers=university_headers).json()
        ] == [university_score_id]
        assert [
            row["id"]
            for row in client.get("/api/questions", headers=university_headers).json()
        ] == [university_question_id]

        updated_score = client.put(
            f"/api/scores/{university_score_id}",
            headers=university_headers,
            json={
                "date": "2026-11-22",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "score": 150,
                "max_score": 200,
            },
        )
        updated_question = client.put(
            f"/api/questions/{university_question_id}",
            headers=university_headers,
            json={
                "date": "2026-11-21",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "unit": "ベクトル",
                "correct": False,
                "points": 10,
                "earned_points": 4,
            },
        )
        assert updated_score.status_code == 200
        assert updated_question.status_code == 200

        assert client.delete(f"/api/scores/{high_school_score_id}").status_code == 204
        assert client.delete(f"/api/questions/{high_school_question_id}").status_code == 204

        high_school_analysis = client.get("/api/analysis").json()
        assert client.get("/api/scores").json() == []
        assert client.get("/api/questions").json() == []
        assert high_school_analysis["summary"] == []
        assert high_school_analysis["weak_units"] == []
        assert high_school_analysis["unit_trends"] == []

        university_analysis = client.get(
            "/api/analysis", headers=university_headers
        ).json()
        assert [
            row["id"]
            for row in client.get("/api/scores", headers=university_headers).json()
        ] == [university_score_id]
        assert [
            row["id"]
            for row in client.get("/api/questions", headers=university_headers).json()
        ] == [university_question_id]
        university_subject = next(
            row for row in university_analysis["summary"]
            if row["subject"] == "数学IA"
        )
        assert university_subject["latest_score"] == 150
        assert university_analysis["weak_units"] == [{
            "exam_type": "共通テスト",
            "subject": "数学IA",
            "unit": "ベクトル",
            "questions": 1,
            "accuracy": 40.0,
            "calculation": "points",
        }]



def test_cross_mode_ids_cannot_be_read_updated_or_deleted(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        university_headers = {"X-Exam-Mode": "university"}

        high_school_score = client.post("/api/scores", json={
            "date": "2026-11-20",
            "exam_name": "高校受験模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 72,
            "max_score": 100,
        })
        high_school_question = client.post("/api/questions", json={
            "date": "2026-11-20",
            "exam_name": "高校受験模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 3,
        })
        university_score = client.post(
            "/api/scores",
            headers=university_headers,
            json={
                "date": "2026-11-21",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "score": 140,
                "max_score": 200,
            },
        )
        university_question = client.post(
            "/api/questions",
            headers=university_headers,
            json={
                "date": "2026-11-21",
                "exam_name": "大学受験模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "unit": "数列",
                "correct": False,
                "points": 10,
                "earned_points": 4,
            },
        )

        assert high_school_score.status_code == 201
        assert high_school_question.status_code == 201
        assert university_score.status_code == 201
        assert university_question.status_code == 201

        high_school_score_id = high_school_score.json()["id"]
        high_school_question_id = high_school_question.json()["id"]
        university_score_id = university_score.json()["id"]
        university_question_id = university_question.json()["id"]

        # University mode must not be able to mutate high-school records.
        assert client.put(
            f"/api/scores/{high_school_score_id}",
            headers=university_headers,
            json={
                "date": "2026-11-22",
                "exam_name": "誤更新テスト",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "score": 1,
                "max_score": 200,
            },
        ).status_code == 404
        assert client.delete(
            f"/api/scores/{high_school_score_id}",
            headers=university_headers,
        ).status_code == 404
        assert client.put(
            f"/api/questions/{high_school_question_id}",
            headers=university_headers,
            json={
                "date": "2026-11-22",
                "exam_name": "誤更新テスト",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "unit": "ベクトル",
                "correct": True,
                "points": 10,
                "earned_points": 10,
            },
        ).status_code == 404
        assert client.delete(
            f"/api/questions/{high_school_question_id}",
            headers=university_headers,
        ).status_code == 404

        # High-school mode must not be able to mutate university records.
        assert client.put(
            f"/api/scores/{university_score_id}",
            json={
                "date": "2026-11-22",
                "exam_name": "誤更新テスト",
                "exam_type": "模試",
                "subject": "数学",
                "score": 1,
                "max_score": 100,
            },
        ).status_code == 404
        assert client.delete(f"/api/scores/{university_score_id}").status_code == 404
        assert client.put(
            f"/api/questions/{university_question_id}",
            json={
                "date": "2026-11-22",
                "exam_name": "誤更新テスト",
                "exam_type": "模試",
                "subject": "数学",
                "unit": "図形",
                "correct": True,
                "points": 10,
                "earned_points": 10,
            },
        ).status_code == 404
        assert client.delete(f"/api/questions/{university_question_id}").status_code == 404

        # Failed cross-mode operations must leave both databases unchanged.
        high_school_scores = client.get("/api/scores").json()
        high_school_questions = client.get("/api/questions").json()
        university_scores = client.get(
            "/api/scores", headers=university_headers
        ).json()
        university_questions = client.get(
            "/api/questions", headers=university_headers
        ).json()

        assert [(row["id"], row["score"]) for row in high_school_scores] == [
            (high_school_score_id, 72)
        ]
        assert [(row["id"], row["unit"]) for row in high_school_questions] == [
            (high_school_question_id, "二次関数")
        ]
        assert [(row["id"], row["score"]) for row in university_scores] == [
            (university_score_id, 140)
        ]
        assert [(row["id"], row["unit"]) for row in university_questions] == [
            (university_question_id, "数列")
        ]

        high_school_analysis = client.get("/api/analysis").json()
        university_analysis = client.get(
            "/api/analysis", headers=university_headers
        ).json()
        assert high_school_analysis["summary"][0]["latest_score"] == 72
        assert high_school_analysis["weak_units"][0]["unit"] == "二次関数"
        assert university_analysis["summary"][0]["latest_score"] == 140
        assert university_analysis["weak_units"][0]["unit"] == "数列"
