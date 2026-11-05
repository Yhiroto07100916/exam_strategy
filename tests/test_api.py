import io

import pandas as pd
from fastapi.testclient import TestClient
import api.main as api


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "test.sqlite3")
    return TestClient(api.app)


def test_health_and_empty_state(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/analysis").json() == {
            "summary": [],
            "exam_type_summary": [],
            "weak_units": [],
            "unit_trends": [],
            "latest_exam": None,
            "latest_exam_ambiguous": False,
            "target_gaps": [],
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
        result = client.get("/api/analysis").json()
        assert result["latest_exam"] is None
        assert result["latest_exam_ambiguous"] is True


def test_latest_exam_is_isolated_by_exam_type_when_name_matches(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        for exam_type, subject, score in [
            ("模試", "国語", 70),
            ("定期考査", "数学", 80),
        ]:
            response = client.post("/api/scores", json={
                "date": "2026-10-01",
                "exam_name": "同名テスト",
                "exam_type": exam_type,
                "subject": subject,
                "score": score,
                "max_score": 100,
            })
            assert response.status_code == 201

        result = client.get("/api/analysis").json()
        assert result["latest_exam"] is None
        assert result["latest_exam_ambiguous"] is True


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


def test_question_exam_type_can_be_changed_when_editing(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        item = client.post("/api/questions", json={
            "date": "2026-11-01",
            "exam_name": "英語演習",
            "exam_type": "模試",
            "subject": "英語",
            "unit": "長文読解",
            "correct": False,
        }).json()
        updated = client.put("/api/questions/" + item["id"], json={
            "date": "2026-11-01",
            "exam_name": "英語演習",
            "exam_type": "過去問",
            "subject": "英語",
            "unit": "長文読解",
            "correct": True,
        })
        assert updated.status_code == 200
        assert updated.json()["exam_type"] == "過去問"
        trend = client.get("/api/analysis").json()["unit_trends"]
        assert len(trend) == 1
        assert trend[0]["exam_type"] == "過去問"
        assert trend[0]["accuracy"] == 100.0


def test_unit_trends_keep_common_test_and_past_papers_separate(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        for exam_type, correct in [("共通テスト", False), ("過去問", True)]:
            response = client.post("/api/questions", headers=headers, json={
                "date": "2026-11-01",
                "exam_name": "英語演習",
                "exam_type": exam_type,
                "subject": "英語リーディング",
                "unit": "長文読解",
                "correct": correct,
            })
            assert response.status_code == 201

        trends = client.get("/api/analysis", headers=headers).json()["unit_trends"]
        assert len(trends) == 2
        assert {row["exam_type"] for row in trends} == {"共通テスト", "過去問"}
        assert {row["accuracy"] for row in trends} == {0.0, 100.0}


def test_settings_reject_invalid_target_subjects_and_scores(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.put("/api/settings", json={
            "profile": {},
            "target": {"subjects": {"情報I": {"target_score": 70, "max_score": 100}}},
        }).status_code == 422

        assert client.put("/api/settings", json={
            "profile": {},
            "target": {"subjects": {"数学": {"target_score": 110, "max_score": 100}}},
        }).status_code == 422

        assert client.put("/api/settings", json={
            "profile": {},
            "target": {"subjects": {"数学": {"target_score": 50, "max_score": "Infinity"}}},
        }).status_code == 422

        valid = client.put("/api/settings", json={
            "profile": {},
            "target": {"subjects": {"数学": {"target_score": 75, "max_score": 100}}},
        })
        assert valid.status_code == 200


def test_university_settings_accept_university_subject_targets(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.put("/api/settings", headers={"X-Exam-Mode": "university"}, json={
            "profile": {},
            "target": {
                "university": {
                    "university_name": "志望大学",
                    "faculty": "理工学部",
                    "department": "情報系",
                    "admission_method": "一般選抜",
                },
                "subjects": {"情報I": {"target_score": 80, "max_score": 100}},
            },
        })
        assert response.status_code == 200


def test_target_gap_normalizes_scores_to_configured_maximum(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        score = client.post("/api/scores", headers=headers, json={
            "date": "2026-11-01",
            "exam_name": "共通テスト模試",
            "exam_type": "共通テスト",
            "subject": "数学IA",
            "score": 120,
            "max_score": 200,
        })
        assert score.status_code == 201
        saved = client.put("/api/settings", headers=headers, json={
            "profile": {},
            "target": {
                "subjects": {
                    "数学IA": {"target_score": 150, "max_score": 200}
                }
            },
        })
        assert saved.status_code == 200

        gap = client.get("/api/analysis", headers=headers).json()["target_gaps"][0]
        assert gap["current"] == 120
        assert gap["current_rate"] == 60
        assert gap["comparable_current"] == 120
        assert gap["target"] == 150
        assert gap["target_max_score"] == 200
        assert gap["gap"] == 30


def test_question_exam_metadata_must_be_complete(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        base = {
            "subject": "数学",
            "unit": "二次関数",
            "correct": True,
        }

        date_only = client.post(
            "/api/questions",
            json={**base, "date": "2026-11-01"},
        )
        assert date_only.status_code == 422

        name_only = client.post(
            "/api/questions",
            json={**base, "exam_name": "11月模試"},
        )
        assert name_only.status_code == 422

        unlinked = client.post("/api/questions", json=base)
        assert unlinked.status_code == 201
        assert unlinked.json()["date"] is None
        assert unlinked.json()["exam_name"] is None

        linked = client.post(
            "/api/questions",
            json={**base, "date": "2026-11-01", "exam_name": "11月模試"},
        )
        assert linked.status_code == 201
        trends = client.get("/api/analysis").json()["unit_trends"]
        assert len(trends) == 1
        assert trends[0]["date"] == "2026-11-01"
        assert trends[0]["exam_name"] == "11月模試"
        assert trends[0]["exam_type"] == "模試"


def test_existing_question_table_is_migrated_without_losing_rows(tmp_path, monkeypatch):
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("""
        CREATE TABLE questions (
            id TEXT PRIMARY KEY, date TEXT, exam_name TEXT,
            subject TEXT NOT NULL, unit TEXT NOT NULL, correct INTEGER NOT NULL,
            points REAL, earned_points REAL
        )
    """)
    connection.execute(
        "INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)",
        ("before-migration", "2026-10-01", "旧模試", "数学", "二次関数", 1, 10, 10),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(api, "DB", database)

    with TestClient(api.app) as client:
        rows = client.get("/api/questions").json()
        assert len(rows) == 1
        assert rows[0]["id"] == "before-migration"
        assert rows[0]["exam_type"] == "模試"
        columns = {
            row[1] for row in sqlite3.connect(database).execute(
                "PRAGMA table_info(questions)"
            ).fetchall()
        }
        assert "exam_type" in columns


def test_legacy_incomplete_question_metadata_remains_editable(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        connection = api.db()
        connection.executemany(
            """INSERT INTO questions
               (id, date, exam_name, subject, unit, correct, points, earned_points)
               VALUES(?,?,?,?,?,?,?,?)""",
            [
                ("legacy-question", "2026-10-01", None, "数学", "二次関数", 0, None, None),
                ("legacy-empty-question", "", "旧試験", "国語", "漢字", 1, None, None),
            ],
        )
        connection.commit()
        connection.close()

        legacy_edit = client.put("/api/questions/legacy-question", json={
            "date": "2026-10-01",
            "exam_name": "",
            "subject": "数学",
            "unit": "図形",
            "correct": True,
        })
        assert legacy_edit.status_code == 200
        assert legacy_edit.json()["unit"] == "図形"
        assert legacy_edit.json()["exam_name"] is None

        changed_partial_reference = client.put(
            "/api/questions/legacy-question",
            json={
                "date": "2026-11-01",
                "exam_name": "",
                "subject": "数学",
                "unit": "図形",
                "correct": True,
            },
        )
        assert changed_partial_reference.status_code == 422

        completed_reference = client.put(
            "/api/questions/legacy-question",
            json={
                "date": "2026-11-01",
                "exam_name": "11月模試",
                "subject": "数学",
                "unit": "図形",
                "correct": True,
            },
        )
        assert completed_reference.status_code == 200
        trends = client.get("/api/analysis").json()["unit_trends"]
        assert len(trends) == 1
        assert trends[0]["date"] == "2026-11-01"
        assert trends[0]["exam_name"] == "11月模試"

        empty_date_edit = client.put(
            "/api/questions/legacy-empty-question",
            json={
                "date": "",
                "exam_name": "旧試験",
                "subject": "国語",
                "unit": "語彙",
                "correct": True,
            },
        )
        assert empty_date_edit.status_code == 200
        assert empty_date_edit.json()["date"] is None
        assert empty_date_edit.json()["unit"] == "語彙"


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


def test_csv_import_preview_does_not_write_and_marks_file_duplicates(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = (
            "date,exam_name,exam_type,subject,score,max_score\n"
            "2026-10-01,10月模試,模試,国語,68,100\n"
            "2026-10-01,10月模試,模試,国語,68,100\n"
            "2026-10-01,10月模試,模試,音楽,80,100\n"
        )
        response = client.post(
            "/api/import/table/preview",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["total_rows"] == 3
        assert result["duplicates"] == 1
        assert [item["row"] for item in result["records"]] == [2, 3]
        assert [item["duplicate"] for item in result["records"]] == [False, True]
        assert result["records"][0]["data"]["subject"] == "国語"
        assert result["records"][0]["warnings"] == []
        assert result["errors"][0]["row"] == 4
        assert client.get("/api/scores").json() == []


def test_csv_import_preview_marks_automatically_filled_fields_for_review(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = "subject,score,max_score\n国語,68,100\n"
        response = client.post(
            "/api/import/table/preview",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )

        assert response.status_code == 200
        record = response.json()["records"][0]
        assert record["data"]["date"]
        assert record["data"]["exam_name"] == "scores"
        assert record["data"]["exam_type"] == "模試"
        assert len(record["warnings"]) == 3


def test_csv_import_confirm_rechecks_duplicates_and_imports_selected_rows(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = (
            "date,exam_name,subject,score,max_score\n"
            "2026-10-01,10月模試,国語,68,100\n"
            "2026-10-01,10月模試,数学,74,100\n"
        )
        preview = client.post(
            "/api/import/table/preview",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )
        assert preview.status_code == 200
        records = preview.json()["records"]

        externally_created = client.post(
            "/api/scores",
            json={
                "date": "2026-10-01",
                "exam_name": "10月模試",
                "subject": "国語",
                "score": 68,
                "max_score": 100,
            },
        )
        assert externally_created.status_code == 201

        confirmed = client.post(
            "/api/import/table/confirm",
            json={"scores": [records[0]["data"], records[1]["data"]]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json() == {"imported": 1, "duplicates": 1}
        saved = client.get("/api/scores").json()
        assert {item["subject"] for item in saved} == {"国語", "数学"}

        invalid = client.post(
            "/api/import/table/confirm",
            json={"scores": [{**records[1]["data"], "score": 101}]},
        )
        assert invalid.status_code == 422
        assert len(client.get("/api/scores").json()) == 2


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


def test_target_allocation_distributes_rounding_remainder(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/targets/allocate", json={
            "target_total": 1,
            "subjects": [
                {"subject": "国語", "current_score": 0, "max_score": 100},
                {"subject": "数学", "current_score": 0, "max_score": 100},
                {"subject": "英語", "current_score": 0, "max_score": 100},
            ],
        })

        assert response.status_code == 200
        result = response.json()
        target_sum = sum(item["target_score"] for item in result["subjects"])
        assert target_sum == 1
        assert result["planned_total"] == 1
        assert sorted(item["target_score"] for item in result["subjects"]) == [
            0.33, 0.33, 0.34
        ]


def test_target_allocation_does_not_reduce_scores_when_goal_is_already_met(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/targets/allocate", json={
            "target_total": 20,
            "subjects": [
                {"subject": "国語", "current_score": 10, "max_score": 100},
                {"subject": "数学", "current_score": 12, "max_score": 100},
            ],
        })

        assert response.status_code == 200
        result = response.json()
        targets = {item["subject"]: item["target_score"] for item in result["subjects"]}
        assert targets == {"国語": 10, "数学": 12}
        assert result["planned_total"] == 22
        assert result["already_at_or_above_goal"] is True


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



def test_target_allocation_rejects_invalid_inputs(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        base_subjects = [
            {"subject": "数学", "current_score": 50, "max_score": 100},
            {"subject": "英語", "current_score": 50, "max_score": 100},
        ]
        invalid_payloads = [
            {"target_total": -1, "subjects": base_subjects},
            {"target_total": 50, "subjects": [{"subject": "数学", "current_score": 50, "max_score": 100}]},
            {"target_total": 50, "subjects": [{**base_subjects[0], "current_score": 101}, base_subjects[1]]},
            {"target_total": 50, "subjects": [{**base_subjects[0], "weight": 0}, base_subjects[1]]},
            {"target_total": 50, "subjects": [{**base_subjects[0], "weight": 10.1}, base_subjects[1]]},
        ]
        for payload in invalid_payloads:
            assert client.post("/api/targets/allocate", json=payload).status_code == 422

        university_subject = {"subject": "情報I", "current_score": 50, "max_score": 100}
        assert client.post("/api/targets/allocate", json={
            "target_total": 100,
            "subjects": [university_subject, base_subjects[1]],
        }).status_code == 422
        valid_university = client.post("/api/targets/allocate", headers={
            "X-Exam-Mode": "university",
        }, json={
            "target_total": 100,
            "subjects": [university_subject, {"subject": "数学IA", "current_score": 50, "max_score": 100}],
        })
        assert valid_university.status_code == 200


def test_target_allocation_uses_only_selected_subjects(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/targets/allocate", json={
            "target_total": 150,
            "subjects": [
                {"subject": "数学", "current_score": 50, "max_score": 100},
                {"subject": "英語", "current_score": 50, "max_score": 100},
            ],
        })
        assert response.status_code == 200
        result = response.json()
        assert {item["subject"] for item in result["subjects"]} == {"数学", "英語"}
        assert result["maximum_total"] == 200

def test_score_update_and_validation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        original = {
            "date": "2026-10-01", "exam_name": "10月模試", "exam_type": "模試",
            "subject": "数学", "score": 72, "max_score": 100, "deviation": 58.4,
            "rank": 12, "examinees": 100
        }
        created = client.post("/api/scores", json=original).json()
        item_id = created["id"]
        changed = {**original, "exam_name": "11月模試", "score": 81, "subject": "英語"}
        response = client.put(f"/api/scores/{item_id}", json=changed)
        assert response.status_code == 200
        assert response.json()["exam_name"] == "11月模試"
        assert response.json()["score"] == 81
        assert response.json()["rank"] == 12
        assert response.json()["examinees"] == 100
        assert response.json()["id"] == item_id
        assert response.json()["created_at"] == created["created_at"]
        assert client.put(
            f"/api/scores/{item_id}", json={**changed, "score": 101}
        ).status_code == 422
        assert client.put("/api/scores/missing", json=changed).status_code == 404


def test_question_update_and_validation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        original = {
            "date": "2026-10-01", "exam_name": "10月模試", "subject": "英語",
            "unit": "関係代名詞", "correct": False, "points": 4, "earned_points": 0
        }
        created = client.post("/api/questions", json=original).json()
        item_id = created["id"]
        changed = {**original, "unit": "仮定法", "correct": True, "earned_points": 4}
        response = client.put(f"/api/questions/{item_id}", json=changed)
        assert response.status_code == 200
        assert response.json()["unit"] == "仮定法"
        assert response.json()["correct"] == 1
        assert client.put(
            f"/api/questions/{item_id}", json={**changed, "earned_points": 5}
        ).status_code == 422
        assert client.put("/api/questions/missing", json=changed).status_code == 404


def test_score_analysis_recalculates_after_update_and_delete(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        older = client.post("/api/scores", json={
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "subject": "数学",
            "score": 60,
            "max_score": 100,
        }).json()
        newer = client.post("/api/scores", json={
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "subject": "数学",
            "score": 80,
            "max_score": 100,
        }).json()

        updated = client.put(
            f"/api/scores/{newer['id']}",
            json={
                "date": "2026-11-01",
                "exam_name": "11月模試",
                "subject": "数学",
                "score": 70,
                "max_score": 100,
            },
        )
        assert updated.status_code == 200
        analysis = client.get("/api/analysis").json()
        assert analysis["latest_exam"]["name"] == "11月模試"
        assert analysis["latest_exam"]["total"] == 70
        assert analysis["summary"][0]["latest_score"] == 70

        assert client.delete(f"/api/scores/{newer['id']}").status_code == 204
        analysis = client.get("/api/analysis").json()
        assert analysis["latest_exam"]["name"] == "10月模試"
        assert analysis["latest_exam"]["total"] == 60
        assert analysis["summary"][0]["latest_score"] == 60
        assert analysis["summary"][0]["count"] == 1

        assert client.delete(f"/api/scores/{older['id']}").status_code == 204
        analysis = client.get("/api/analysis").json()
        assert analysis["latest_exam"] is None
        assert analysis["summary"] == []


def test_question_analysis_recalculates_after_update_and_delete(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post("/api/questions", json={
            "date": "2026-10-01",
            "exam_name": "10月模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 0,
        })
        assert created.status_code == 201
        item_id = created.json()["id"]

        initial = client.get("/api/analysis").json()
        assert len(initial["unit_trends"]) == 1
        assert initial["unit_trends"][0]["unit"] == "二次関数"
        assert initial["weak_units"][0]["accuracy"] == 0

        updated = client.put(f"/api/questions/{item_id}", json={
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "subject": "数学",
            "unit": "図形",
            "correct": True,
            "points": 10,
            "earned_points": 10,
        })
        assert updated.status_code == 200

        after_update = client.get("/api/analysis").json()
        assert len(after_update["unit_trends"]) == 1
        assert after_update["unit_trends"][0]["date"] == "2026-11-01"
        assert after_update["unit_trends"][0]["exam_name"] == "11月模試"
        assert after_update["unit_trends"][0]["unit"] == "図形"
        assert after_update["unit_trends"][0]["accuracy"] == 100
        assert after_update["weak_units"][0]["unit"] == "図形"
        assert after_update["weak_units"][0]["accuracy"] == 100

        assert client.delete(f"/api/questions/{item_id}").status_code == 204
        after_delete = client.get("/api/analysis").json()
        assert after_delete["unit_trends"] == []
        assert after_delete["weak_units"] == []


def test_csv_import_skips_existing_and_in_file_duplicates(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = (
            "date,exam_name,subject,score,max_score\n"
            "2026-10-01,10月模試,国語,68,100\n"
            "2026-10-01,10月模試,国語,68,100\n"
        )
        first = client.post(
            "/api/import/table",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )
        assert first.status_code == 200
        assert first.json()["imported"] == 1
        assert first.json()["duplicates"] == 1
        assert first.json()["errors"] == []

        second = client.post(
            "/api/import/table",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )
        assert second.status_code == 200
        assert second.json()["imported"] == 0
        assert second.json()["duplicates"] == 2
        assert len(client.get("/api/scores").json()) == 1


def test_csv_import_keeps_valid_rows_and_reports_invalid_rows(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = (
            "date,exam_name,subject,score,max_score\n"
            "2026-10-01,10月模試,国語,68,100\n"
            "2026-10-01,10月模試,音楽,80,100\n"
        )
        response = client.post(
            "/api/import/table",
            files={"file": ("scores.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["imported"] == 1
        assert response.json()["duplicates"] == 0
        assert len(response.json()["errors"]) == 1
        assert len(client.get("/api/scores").json()) == 1


def test_xlsx_import(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        output = io.BytesIO()
        pd.DataFrame([{
            "date": "2026-10-01", "exam_name": "Excel模試",
            "subject": "数学", "score": 74, "max_score": 100
        }]).to_excel(output, index=False)
        response = client.post(
            "/api/import/table",
            files={"file": ("scores.xlsx", output.getvalue(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == 200
        assert response.json()["imported"] == 1
        assert response.json()["duplicates"] == 0
        assert response.json()["errors"] == []


def test_school_and_admission_rule_crud_with_source_validation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/schools").json() == []

        school_payload = {
            "name": "都立サンプル高校",
            "prefecture": "東京都",
            "school_type": "公立",
        }
        created = client.post("/api/schools", json=school_payload)
        assert created.status_code == 201
        school_id = created.json()["id"]
        assert client.post("/api/schools", json=school_payload).status_code == 409

        unverified = {
            "admission_year": 2027,
            "course": "普通科",
            "selection_type": "一般選抜",
            "verification_status": "未確認",
            "rule_data": {},
            "notes": "公式資料を確認するまで得点計算に使わない",
        }
        rule = client.post(f"/api/schools/{school_id}/rules", json=unverified)
        assert rule.status_code == 201
        rule_id = rule.json()["id"]
        unverified_calc = client.post(
            f"/api/schools/{school_id}/rules/{rule_id}/allocate",
            json={
                "target_total": 470,
                "subjects": [
                    {"subject": "数学", "current_score": 60},
                    {"subject": "英語", "current_score": 70},
                ],
                "fixed_component_scores": {"調査書": 80},
            },
        )
        assert unverified_calc.status_code == 409

        invalid_verified = {
            **unverified,
            "verification_status": "確認済み",
            "rule_data": {"exam_weight": 1},
        }
        assert client.post(
            f"/api/schools/{school_id}/rules", json=invalid_verified
        ).status_code == 422

        verified = {
            **unverified,
            "verification_status": "確認済み",
            "official_source_url": "https://www.example.metro.tokyo.jp/admission",
            "verified_on": "2026-10-31",
            "rule_data": {
                "scoring_model": {
                    "model_version": "weighted_components_v1",
                    "exam_subjects": [
                        {"subject": "数学", "raw_max_score": 100, "contribution_max_score": 300, "source_page": 12},
                        {"subject": "英語", "raw_max_score": 100, "contribution_max_score": 200, "source_page": 12}
                    ],
                    "fixed_components": [
                        {"name": "調査書", "max_score": 100, "source_page": 13}
                    ],
                    "alternatives": [
                        {
                            "label": "10:0方式",
                            "exam_subjects": [
                                {"subject": "数学", "raw_max_score": 100, "contribution_max_score": 200, "source_page": 14},
                                {"subject": "英語", "raw_max_score": 100, "contribution_max_score": 300, "source_page": 14}
                            ],
                            "fixed_components": [
                                {"name": "調査書", "max_score": 100, "source_page": 14}
                            ]
                        }
                    ]
                }
            },
        }
        updated = client.put(f"/api/school-rules/{rule_id}", json=verified)
        assert updated.status_code == 200
        assert updated.json()["verification_status"] == "確認済み"

        allocation = client.post(
            f"/api/schools/{school_id}/rules/{rule_id}/allocate",
            json={
                "target_total": 470,
                "subjects": [
                    {"subject": "数学", "current_score": 60, "priority": 1},
                    {"subject": "英語", "current_score": 70, "priority": 1},
                ],
                "fixed_component_scores": {"調査書": 80},
                "alternative_fixed_component_scores": {
                    "10:0方式": {"調査書": 80}
                },
            },
        )
        assert allocation.status_code == 200
        result = allocation.json()
        assert result["current_total"] == 410
        assert result["best_current_method"] == "10:0方式"
        assert result["planned_total"] == 470
        assert len(result["method_results"]) == 2
        primary_result, alternative_result = result["method_results"]
        assert primary_result["current_total"] == 400
        assert primary_result["planned_total"] == 470
        assert primary_result["subjects"][0]["target_score"] == 71.67
        assert primary_result["subjects"][1]["target_score"] == 87.5
        assert alternative_result["current_total"] == 410
        assert alternative_result["planned_total"] == 470
        assert alternative_result["method_label"] == "10:0方式"
        assert result["fixed_components"][0]["score"] == 80

        impossible = client.post(
            f"/api/schools/{school_id}/rules/{rule_id}/allocate",
            json={
                "target_total": 581,
                "subjects": [
                    {"subject": "数学", "current_score": 60},
                    {"subject": "英語", "current_score": 70},
                ],
                "fixed_component_scores": {"調査書": 80},
                "alternative_fixed_component_scores": {
                    "10:0方式": {"調査書": 80}
                },
            },
        )
        assert impossible.status_code == 422

        partial = client.post(
            f"/api/schools/{school_id}/rules/{rule_id}/allocate",
            json={
                "target_total": 550,
                "subjects": [
                    {"subject": "数学", "current_score": 60},
                    {"subject": "英語", "current_score": 70},
                ],
                "fixed_component_scores": {"調査書": 80},
                "alternative_fixed_component_scores": {
                    "10:0方式": {"調査書": 0}
                },
            },
        )
        assert partial.status_code == 200
        assert partial.json()["method_results"][0]["planned_total"] == 550
        assert "error" in partial.json()["method_results"][1]

        listed = client.get("/api/schools").json()
        assert listed[0]["rules"][0]["rule_data"]["scoring_model"]["exam_subjects"][0]["source_page"] == 12
        assert client.delete(f"/api/schools/{school_id}").status_code == 204
        assert client.get("/api/schools").json() == []


def test_school_rule_requires_https_source_url(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "私立サンプル高校", "prefecture": "神奈川県", "school_type": "私立"
        }).json()
        response = client.post(f"/api/schools/{school['id']}/rules", json={
            "admission_year": 2027,
            "selection_type": "一般入試",
            "verification_status": "未確認",
            "official_source_url": "http://example.com/rule",
        })
        assert response.status_code == 422


def test_official_school_source_directory():
    from fastapi.testclient import TestClient
    with TestClient(api.app) as client:
        response = client.get("/api/schools/official-sources")
        assert response.status_code == 200
        result = response.json()
        assert result["admission_year"] == 2027
        assert {item["prefecture"] for item in result["official_sources"]} == {
            "東京都", "神奈川県", "埼玉県", "千葉県"
        }
        source_pairs = {
            (item["prefecture"], item["category"])
            for item in result["official_sources"]
        }
        assert ("埼玉県", "私立") in source_pairs
        assert ("千葉県", "私立") in source_pairs
        assert result["last_checked"] == "2026-11-06"
        urls = {item["url"] for item in result["official_sources"]}
        assert "https://www.kyoiku.metro.tokyo.lg.jp/admission/high_school/exam/boshuguide20261023" in urls
        assert "https://www.pref.kanagawa.jp/docs/dc4/nyusen/nyusen/kanagawa.html" in urls


def test_verified_school_rule_requires_source_cited_scoring_model(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "配点検証高校", "prefecture": "東京都", "school_type": "公立"
        }).json()
        response = client.post(f"/api/schools/{school['id']}/rules", json={
            "admission_year": 2027,
            "selection_type": "一般選抜",
            "verification_status": "確認済み",
            "official_source_url": "https://www.example.metro.tokyo.jp/rule",
            "verified_on": "2026-10-31",
            "rule_data": {
                "scoring_model": {
                    "model_version": "weighted_components_v1",
                    "exam_subjects": [
                        {"subject": "数学", "raw_max_score": 100,
                         "contribution_max_score": 100}
                    ],
                    "fixed_components": [],
                }
            },
        })
        assert response.status_code == 422


def test_school_scoring_alternatives_require_comparable_total_maxima(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "複数方式高校", "prefecture": "東京都", "school_type": "公立"
        }).json()
        response = client.post(f"/api/schools/{school['id']}/rules", json={
            "admission_year": 2027,
            "selection_type": "一般選抜",
            "verification_status": "確認済み",
            "official_source_url": "https://www.example.metro.tokyo.jp/rule",
            "verified_on": "2026-10-31",
            "rule_data": {
                "scoring_model": {
                    "model_version": "weighted_components_v1",
                    "exam_subjects": [
                        {"subject": "数学", "raw_max_score": 100,
                         "contribution_max_score": 100, "source_page": 1}
                    ],
                    "fixed_components": [],
                    "alternatives": [{
                        "label": "別方式",
                        "exam_subjects": [
                            {"subject": "数学", "raw_max_score": 100,
                             "contribution_max_score": 90, "source_page": 2}
                        ],
                        "fixed_components": [],
                    }],
                }
            },
        })
        assert response.status_code == 422


def test_manual_score_create_and_update_reject_duplicates_without_mutation(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        base = {
            "date": "2026-11-01",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 72,
            "max_score": 100,
        }
        first = client.post("/api/scores", json=base)
        assert first.status_code == 201

        duplicate = client.post("/api/scores", json={**base, "score": 80})
        assert duplicate.status_code == 409
        assert len(client.get("/api/scores").json()) == 1

        different_type = client.post(
            "/api/scores", json={**base, "exam_type": "定期考査"}
        )
        different_subject = client.post(
            "/api/scores", json={**base, "subject": "英語"}
        )
        assert different_type.status_code == 201
        assert different_subject.status_code == 201

        english_id = different_subject.json()["id"]
        collision = client.put(
            f"/api/scores/{english_id}",
            json={**base, "subject": "数学", "score": 88},
        )
        assert collision.status_code == 409

        saved = next(
            row for row in client.get("/api/scores").json()
            if row["id"] == english_id
        )
        assert saved["subject"] == "英語"
        assert saved["score"] == 72

        self_update = client.put(
            f"/api/scores/{first.json()['id']}", json={**base, "score": 75}
        )
        assert self_update.status_code == 200
        assert self_update.json()["score"] == 75


def test_exam_modes_keep_score_and_question_data_separate(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        high_school_score = {
            "date": "2026-11-04", "exam_name": "高校模試",
            "exam_type": "模試", "subject": "数学", "score": 72, "max_score": 100,
        }
        university_score = {
            "date": "2026-11-04", "exam_name": "大学模試",
            "exam_type": "模試", "subject": "数学IA", "score": 68, "max_score": 100,
        }
        university_headers = {"X-Exam-Mode": "university"}

        assert client.post("/api/scores", json=high_school_score).status_code == 201
        assert client.post(
            "/api/scores", json=university_score, headers=university_headers
        ).status_code == 201
        assert len(client.get("/api/scores").json()) == 1
        university_rows = client.get(
            "/api/scores", headers=university_headers
        ).json()
        assert len(university_rows) == 1
        assert university_rows[0]["subject"] == "数学IA"

        assert client.post(
            "/api/scores", json={**high_school_score, "subject": "数学IA"}
        ).status_code == 422
        assert client.post(
            "/api/scores",
            json={**university_score, "subject": "数学IIBC"},
            headers=university_headers,
        ).status_code == 201

        question = {
            "date": "2026-11-04", "exam_name": "大学模試",
            "subject": "物理", "unit": "力学", "correct": True,
        }
        assert client.post(
            "/api/questions", json=question, headers=university_headers
        ).status_code == 201
        assert client.get("/api/questions").json() == []
        assert len(client.get(
            "/api/questions", headers=university_headers
        ).json()) == 1
        assert client.get(
            "/api/scores", headers={"X-Exam-Mode": "unknown"}
        ).status_code == 400


def test_university_target_allocation_accepts_university_subjects(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        response = client.post("/api/targets/allocate", headers=headers, json={
            "target_total": 300,
            "subjects": [
                {"subject": "英語リーディング", "current_score": 60, "max_score": 100, "weight": 1},
                {"subject": "英語リスニング", "current_score": 55, "max_score": 100, "weight": 1},
                {"subject": "数学IA", "current_score": 65, "max_score": 100, "weight": 1},
                {"subject": "数学IIBC", "current_score": 50, "max_score": 100, "weight": 1},
                {"subject": "情報I", "current_score": 70, "max_score": 100, "weight": 1},
            ],
        })
        assert response.status_code == 200
        assert len(response.json()["subjects"]) == 5


def test_university_target_profile_and_exam_types_are_isolated(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        university_headers = {"X-Exam-Mode": "university"}
        university_settings = {
            "profile": {"name": "大学受験モード"},
            "target": {
                "school_name": "東京大学 / 理学部 / 数学科",
                "admission_year": 2027,
                "university": {
                    "university_name": "東京大学",
                    "faculty": "理学部",
                    "department": "数学科",
                    "admission_method": "一般選抜・前期日程",
                },
                "subjects": {"数学IA": {"target_score": 170, "max_score": 200}},
            },
        }
        saved = client.put(
            "/api/settings", json=university_settings, headers=university_headers
        )
        assert saved.status_code == 200
        assert client.get("/api/settings").json()["target"] == {}
        assert client.get(
            "/api/settings", headers=university_headers
        ).json()["target"]["university"]["admission_method"] == "一般選抜・前期日程"
        assert client.get(
            "/api/settings", headers=university_headers
        ).json()["target"]["subjects"]["数学IA"]["max_score"] == 200

        common_test = {
            "date": "2026-11-04", "exam_name": "共通テスト模試",
            "exam_type": "共通テスト", "subject": "情報I",
            "score": 78, "max_score": 100,
        }
        individual = {
            **common_test, "exam_name": "大学別模試",
            "exam_type": "個別試験", "subject": "数学III",
        }
        assert client.post(
            "/api/scores", json=common_test, headers=university_headers
        ).status_code == 201
        assert client.post(
            "/api/scores", json=individual, headers=university_headers
        ).status_code == 201
        rows = client.get("/api/scores", headers=university_headers).json()
        assert {row["exam_type"] for row in rows} == {"共通テスト", "個別試験"}


def test_analysis_separates_university_exam_types_by_subject(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        rows = [
            {
                "date": "2026-10-01", "exam_name": "共通テスト模試",
                "exam_type": "共通テスト", "subject": "英語リーディング",
                "score": 70, "max_score": 100,
            },
            {
                "date": "2026-11-01", "exam_name": "共通テスト模試",
                "exam_type": "共通テスト", "subject": "英語リーディング",
                "score": 80, "max_score": 100,
            },
            {
                "date": "2026-11-02", "exam_name": "大学別模試",
                "exam_type": "個別試験", "subject": "英語リーディング",
                "score": 55, "max_score": 100,
            },
        ]
        for row in rows:
            response = client.post("/api/scores", json=row, headers=headers)
            assert response.status_code == 201

        analysis = client.get("/api/analysis", headers=headers).json()
        breakdown = {
            (row["exam_type"], row["subject"]): row
            for row in analysis["exam_type_summary"]
        }
        common = breakdown[("共通テスト", "英語リーディング")]
        individual = breakdown[("個別試験", "英語リーディング")]

        assert common["count"] == 2
        assert common["average_rate"] == 75.0
        assert common["latest_rate"] == 80.0
        assert common["latest_date"] == "2026-11-01"
        assert individual["count"] == 1
        assert individual["average_rate"] == 55.0
        assert client.get("/api/analysis").json()["exam_type_summary"] == []


def test_university_ocr_candidates_use_university_subject_names():
    from api.ocr import parse_ocr_candidates

    candidates = parse_ocr_candidates([
        "英語リーディング 82/100\n"
        "数学IA 75/100\n"
        "数学IIBC 68/100\n"
        "物理 71/100\n"
        "情報I 88/100"
    ], mode="university")

    assert [item["subject"] for item in candidates] == [
        "英語リーディング", "数学IA", "数学IIBC", "物理", "情報I"
    ]
    assert [item["score_candidate"] for item in candidates] == [82, 75, 68, 71, 88]


def test_high_school_ocr_candidates_keep_high_school_subjects():
    from api.ocr import parse_ocr_candidates

    candidates = parse_ocr_candidates(["数学 75/100\n英語 80/100"])
    assert [item["subject"] for item in candidates] == ["数学", "英語"]


def test_pdf_text_preview_rejects_oversized_files(tmp_path, monkeypatch):
    from api.ocr import MAX_PDF_BYTES

    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/import/pdf",
            files={"file": ("large.pdf", b"x" * (MAX_PDF_BYTES + 1), "application/pdf")},
        )
        assert response.status_code == 413


def test_table_import_rejects_oversized_files(tmp_path, monkeypatch):
    from api.ocr import MAX_PDF_BYTES

    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/import/table",
            files={"file": ("large.csv", b"x" * (MAX_PDF_BYTES + 1), "text/csv")},
        )
        assert response.status_code == 413


def test_excel_report_escapes_formula_like_user_text(tmp_path, monkeypatch):
    from io import BytesIO
    from openpyxl import load_workbook

    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/questions", json={
            "subject": "数学",
            "unit": "=HYPERLINK(\"https://example.com\",\"click\")",
            "correct": True,
        })
        assert response.status_code == 201

        report = client.get("/api/reports/excel")
        assert report.status_code == 200
        workbook = load_workbook(BytesIO(report.content), data_only=False)
        cell = workbook["問題別データ"]["E2"]
        assert cell.data_type == "s"
        assert cell.value.startswith("'=")


def test_ocr_confirm_preserves_university_exam_type_and_subject(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        response = client.post("/api/import/ocr-confirm", headers=headers, json={
            "scores": [{
                "date": "2026-11-04",
                "exam_name": "共通テスト模試",
                "exam_type": "共通テスト",
                "subject": "数学IA",
                "score": 80,
                "max_score": 100,
            }]
        })
        assert response.status_code == 200
        assert response.json()["imported"] == 1
        saved = client.get("/api/scores", headers=headers).json()
        assert saved[0]["subject"] == "数学IA"
        assert saved[0]["exam_type"] == "共通テスト"


def test_ocr_preview_passes_exam_mode_to_candidate_parser(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(
            api,
            "preview_pdf_ocr",
            lambda content, mode: {"mode": mode, "candidates": []},
        )
        response = client.post(
            "/api/import/pdf/ocr-preview",
            headers={"X-Exam-Mode": "university"},
            files={"file": ("scores.pdf", b"fake-pdf", "application/pdf")},
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "university"



def test_university_excel_report_includes_exam_type_targets_and_weak_units(tmp_path, monkeypatch):
    from io import BytesIO
    from openpyxl import load_workbook

    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        score_response = client.post("/api/scores", headers=headers, json={
            "date": "2026-11-01",
            "exam_name": "共通テスト模試",
            "exam_type": "共通テスト",
            "subject": "数学IA",
            "score": 72,
            "max_score": 100,
        })
        assert score_response.status_code == 201
        question_response = client.post("/api/questions", headers=headers, json={
            "date": "2026-11-01",
            "exam_name": "共通テスト模試",
            "exam_type": "共通テスト",
            "subject": "数学IA",
            "unit": "場合の数と確率",
            "correct": False,
            "points": 10,
            "earned_points": 4,
        })
        assert question_response.status_code == 201
        past_paper_response = client.post("/api/questions", headers=headers, json={
            "date": "2026-11-02",
            "exam_name": "過去問演習",
            "exam_type": "過去問",
            "subject": "数学IA",
            "unit": "場合の数と確率",
            "correct": True,
            "points": 10,
            "earned_points": 9,
        })
        assert past_paper_response.status_code == 201
        settings_response = client.put("/api/settings", headers=headers, json={
            "profile": {},
            "target": {
                "university": {
                    "university_name": "東京大学",
                    "faculty": "理科一類",
                    "department": "",
                    "admission_method": "一般選抜",
                },
                "subjects": {
                    "数学IA": {"target_score": 85, "max_score": 100, "weight": 2}
                },
            },
        })
        assert settings_response.status_code == 200

        response = client.get("/api/reports/excel", headers=headers)
        assert response.status_code == 200
        workbook = load_workbook(BytesIO(response.content), data_only=True)

        assert {
            "成績データ", "問題別データ", "科目分析", "試験種別分析",
            "科目別目標", "志望情報", "単元分析", "単元推移",
        }.issubset(workbook.sheetnames)
        exam_sheet = workbook["試験種別分析"]
        assert exam_sheet["A2"].value == "共通テスト"
        assert exam_sheet["B2"].value == "数学IA"
        assert exam_sheet["G2"].value == 72
        target_sheet = workbook["科目別目標"]
        assert target_sheet["A2"].value == "数学IA"
        assert target_sheet["B2"].value == 85
        profile_values = {
            row[0].value: row[1].value for row in workbook["志望情報"].iter_rows(min_row=2)
        }
        assert profile_values["志望大学"] == "東京大学"
        unit_sheet = workbook["単元分析"]
        assert [cell.value for cell in unit_sheet[1]] == [
            "試験種別", "科目", "単元", "問題数", "正答率・得点率", "集計方法"
        ]
        unit_rows = {
            unit_sheet.cell(row=row, column=1).value: {
                "subject": unit_sheet.cell(row=row, column=2).value,
                "unit": unit_sheet.cell(row=row, column=3).value,
                "count": unit_sheet.cell(row=row, column=4).value,
                "accuracy": unit_sheet.cell(row=row, column=5).value,
            }
            for row in range(2, unit_sheet.max_row + 1)
        }
        assert unit_rows == {
            "共通テスト": {
                "subject": "数学IA", "unit": "場合の数と確率",
                "count": 1, "accuracy": 40,
            },
            "過去問": {
                "subject": "数学IA", "unit": "場合の数と確率",
                "count": 1, "accuracy": 90,
            },
        }

        trend_sheet = workbook["単元推移"]
        assert [cell.value for cell in trend_sheet[1]] == [
            "日付", "試験名", "試験種別", "科目", "単元", "問題数",
            "正答率・得点率", "集計方法",
        ]
        trend_rows = {
            trend_sheet.cell(row=row, column=2).value: {
                "date": trend_sheet.cell(row=row, column=1).value,
                "exam_type": trend_sheet.cell(row=row, column=3).value,
                "accuracy": trend_sheet.cell(row=row, column=7).value,
            }
            for row in range(2, trend_sheet.max_row + 1)
        }
        assert trend_rows == {
            "共通テスト模試": {
                "date": "2026-11-01", "exam_type": "共通テスト", "accuracy": 40,
            },
            "過去問演習": {
                "date": "2026-11-02", "exam_type": "過去問", "accuracy": 90,
            },
        }



def test_backup_restore_round_trip_preserves_mode_data_and_school_rules(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "high_school"}
        score = client.post("/api/scores", headers=headers, json={
            "date": "2026-11-03",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 76,
            "max_score": 100,
        })
        assert score.status_code == 201
        question = client.post("/api/questions", headers=headers, json={
            "date": "2026-11-03",
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 5,
            "earned_points": 2,
        })
        assert question.status_code == 201
        settings = client.put("/api/settings", headers=headers, json={
            "profile": {"nickname": "sample"},
            "target": {"subjects": {"数学": {"target_score": 80, "max_score": 100}}},
        })
        assert settings.status_code == 200
        school = client.post("/api/schools", headers=headers, json={
            "name": "テスト高校",
            "prefecture": "東京都",
            "school_type": "公立",
        })
        assert school.status_code == 201
        school_id = school.json()["id"]
        rule = client.post(f"/api/schools/{school_id}/rules", headers=headers, json={
            "admission_year": 2027,
            "course": "普通科",
            "selection_type": "一般選抜",
            "verification_status": "未確認",
            "rule_data": {"memo": "backup test"},
        })
        assert rule.status_code == 201

        exported = client.get("/api/backup", headers=headers)
        assert exported.status_code == 200
        backup = exported.json()
        assert backup["format_version"] == 1
        assert backup["exam_mode"] == "high_school"
        assert len(backup["scores"]) == 1
        assert len(backup["questions"]) == 1
        assert len(backup["schools"]) == 1
        assert len(backup["school_rules"]) == 1

        client.delete(f"/api/scores/{score.json()['id']}", headers=headers)
        client.delete(f"/api/questions/{question.json()['id']}", headers=headers)
        client.delete(f"/api/schools/{school_id}", headers=headers)
        client.put("/api/settings", headers=headers, json={"profile": {}, "target": {}})

        restored = client.post(
            "/api/backup/restore",
            headers=headers,
            json={**backup, "confirm_replace": True},
        )
        assert restored.status_code == 200
        assert restored.json()["restored"] == {
            "scores": 1, "questions": 1, "schools": 1, "school_rules": 1
        }
        assert len(client.get("/api/scores", headers=headers).json()) == 1
        assert len(client.get("/api/questions", headers=headers).json()) == 1
        assert len(client.get("/api/schools", headers=headers).json()) == 1
        assert client.get("/api/settings", headers=headers).json()["profile"]["nickname"] == "sample"


def test_backup_restore_requires_confirmation_and_matching_exam_mode(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        backup = client.get("/api/backup").json()
        missing_confirmation = client.post("/api/backup/restore", json=backup)
        assert missing_confirmation.status_code == 400

        wrong_mode = client.post(
            "/api/backup/restore",
            headers={"X-Exam-Mode": "university"},
            json={**backup, "confirm_replace": True},
        )
        assert wrong_mode.status_code == 409


def test_invalid_backup_does_not_replace_existing_data(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post("/api/scores", json={
            "date": "2026-11-03",
            "exam_name": "保持する模試",
            "subject": "数学",
            "score": 50,
            "max_score": 100,
        })
        assert created.status_code == 201
        backup = client.get("/api/backup").json()
        backup["scores"][0]["score"] = 999
        response = client.post(
            "/api/backup/restore",
            json={**backup, "confirm_replace": True},
        )
        assert response.status_code == 422
        scores = client.get("/api/scores").json()
        assert len(scores) == 1
        assert scores[0]["exam_name"] == "保持する模試"



def test_csv_import_normalizes_headers_and_preserves_exam_type(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = (
            " date , exam_name , exam_type , subject , score , max_score \n"
            "2026-10-02,共通テスト演習,共通テスト,数学IA,78,100\n"
        )
        response = client.post(
            "/api/import/table",
            headers={"X-Exam-Mode": "university"},
            files={"file": ("university.csv", csv_data.encode("utf-8-sig"), "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["total_rows"] == 1
        assert response.json()["imported"] == 1
        saved = client.get("/api/scores", headers={"X-Exam-Mode": "university"}).json()
        assert saved[0]["subject"] == "数学IA"
        assert saved[0]["exam_type"] == "共通テスト"


def test_csv_import_rejects_duplicate_normalized_headers(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        csv_data = "subject, subject ,score,max_score\n数学,英語,70,100\n"
        response = client.post(
            "/api/import/table",
            files={"file": ("duplicate.csv", csv_data.encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 422
        assert "重複" in response.json()["detail"]
        assert client.get("/api/scores").json() == []


def test_csv_import_rejects_more_than_row_limit(tmp_path, monkeypatch):
    from api.main import MAX_IMPORT_ROWS

    with make_client(tmp_path, monkeypatch) as client:
        lines = ["subject,score,max_score"]
        lines.extend(["数学,50,100"] * (MAX_IMPORT_ROWS + 1))
        response = client.post(
            "/api/import/table",
            files={"file": ("many.csv", ("\n".join(lines)).encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 413
        assert client.get("/api/scores").json() == []


def test_backup_restore_rejects_duplicate_school_identity_without_replacing_data(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "保持する高校",
            "prefecture": "東京都",
            "school_type": "公立",
        })
        assert school.status_code == 201

        backup = client.get("/api/backup").json()
        duplicate = dict(backup["schools"][0])
        duplicate["id"] = "duplicate-school-id"
        backup["schools"].append(duplicate)

        response = client.post(
            "/api/backup/restore",
            json={**backup, "confirm_replace": True},
        )

        assert response.status_code == 422
        schools = client.get("/api/schools").json()
        assert len(schools) == 1
        assert schools[0]["name"] == "保持する高校"


def test_backup_restore_rejects_duplicate_school_rule_identity_without_replacing_data(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "選抜ルール高校",
            "prefecture": "東京都",
            "school_type": "公立",
        })
        assert school.status_code == 201
        school_id = school.json()["id"]
        rule = client.post(f"/api/schools/{school_id}/rules", json={
            "admission_year": 2027,
            "course": "普通科",
            "selection_type": "一般選抜",
            "verification_status": "未確認",
            "rule_data": {"memo": "backup test"},
        })
        assert rule.status_code == 201

        backup = client.get("/api/backup").json()
        duplicate = dict(backup["school_rules"][0])
        duplicate["id"] = "duplicate-school-rule-id"
        backup["school_rules"].append(duplicate)

        response = client.post(
            "/api/backup/restore",
            json={**backup, "confirm_replace": True},
        )

        assert response.status_code == 422
        schools = client.get("/api/schools").json()
        assert len(schools) == 1
        assert len(schools[0]["rules"]) == 1
        assert schools[0]["rules"][0]["selection_type"] == "一般選抜"


def test_school_rule_update_conflict_preserves_original_rule(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        school = client.post("/api/schools", json={
            "name": "更新競合テスト高校",
            "prefecture": "東京都",
            "school_type": "公立",
        })
        assert school.status_code == 201
        school_id = school.json()["id"]

        first = client.post(f"/api/schools/{school_id}/rules", json={
            "admission_year": 2027,
            "course": "普通科",
            "selection_type": "一般選抜",
            "verification_status": "未確認",
            "notes": "既存ルール",
        })
        second = client.post(f"/api/schools/{school_id}/rules", json={
            "admission_year": 2027,
            "course": "普通科",
            "selection_type": "推薦選抜",
            "verification_status": "未確認",
            "notes": "更新対象ルール",
        })
        assert first.status_code == 201
        assert second.status_code == 201

        conflict = client.put(
            f"/api/school-rules/{second.json()['id']}",
            json={
                "admission_year": 2027,
                "course": "普通科",
                "selection_type": "一般選抜",
                "verification_status": "未確認",
                "notes": "競合する更新",
            },
        )
        assert conflict.status_code == 409

        listed = client.get("/api/schools").json()
        rules = listed[0]["rules"]
        assert len(rules) == 2
        saved = {rule["id"]: rule for rule in rules}
        assert saved[first.json()["id"]]["selection_type"] == "一般選抜"
        assert saved[second.json()["id"]]["selection_type"] == "推薦選抜"
        assert saved[second.json()["id"]]["notes"] == "更新対象ルール"

def test_weak_units_keep_exam_types_separate(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        headers = {"X-Exam-Mode": "university"}
        for exam_type, correct, earned in [
            ("共通テスト", False, 0),
            ("過去問", True, 10),
        ]:
            response = client.post("/api/questions", headers=headers, json={
                "date": "2026-11-01",
                "exam_name": "英語演習",
                "exam_type": exam_type,
                "subject": "英語リーディング",
                "unit": "長文読解",
                "correct": correct,
                "points": 10,
                "earned_points": earned,
            })
            assert response.status_code == 201

        weak_units = client.get("/api/analysis", headers=headers).json()["weak_units"]
        assert len(weak_units) == 2
        breakdown = {
            row["exam_type"]: row
            for row in weak_units
        }
        assert breakdown["共通テスト"]["accuracy"] == 0.0
        assert breakdown["過去問"]["accuracy"] == 100.0
        assert breakdown["共通テスト"]["questions"] == 1
        assert breakdown["過去問"]["questions"] == 1
        assert all(row["subject"] == "英語リーディング" for row in weak_units)
        assert all(row["unit"] == "長文読解" for row in weak_units)



def test_latest_exam_remains_available_when_only_one_exam_exists_on_latest_date(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        for subject, score in [("国語", 70), ("数学", 80)]:
            response = client.post("/api/scores", json={
                "date": "2026-10-01", "exam_name": "10月模試",
                "exam_type": "模試", "subject": subject,
                "score": score, "max_score": 100,
            })
            assert response.status_code == 201

        result = client.get("/api/analysis").json()
        assert result["latest_exam"]["name"] == "10月模試"
        assert result["latest_exam"]["total"] == 150
        assert result["latest_exam"]["max_total"] == 200
        assert result["latest_exam_ambiguous"] is False
