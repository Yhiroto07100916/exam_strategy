from datetime import date, timedelta

from fastapi.testclient import TestClient

import api.main as api
import api.study_planning as planning


def make_client(tmp_path, monkeypatch):
    monkeypatch.delenv("STUDY_PLANNER_API_KEY", raising=False)
    monkeypatch.setattr(api, "DB", tmp_path / "study-plan.sqlite3")
    return TestClient(api.app)


def test_generate_study_plan_builds_month_week_day_hierarchy(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        target_date = (date.today() + timedelta(days=18)).isoformat()
        score = client.post("/api/scores", json={
            "date": date.today().isoformat(),
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 52,
            "max_score": 100,
        })
        assert score.status_code == 201
        question = client.post("/api/questions", json={
            "date": date.today().isoformat(),
            "exam_name": "11月模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
            "points": 10,
            "earned_points": 3,
        })
        assert question.status_code == 201

        response = client.post("/api/study-plans/generate", json={
            "target_date": target_date,
            "availability": {"1": 60, "3": 40, "6": 90},
            "session_minutes": 50,
        })

        assert response.status_code == 201
        plan = response.json()
        assert plan["generation_mode"] == "data_driven_v1"
        assert plan["months"]
        assert plan["subject_signals"]
        assert any(
            signal["subject"] == "数学"
            and signal["weak_units"][0]["unit"] == "二次関数"
            for signal in plan["subject_signals"]
        )
        scheduled_minutes = sum(
            task["duration_minutes"]
            for month in plan["months"]
            for week in month["weeks"]
            for day in week["days"]
            for task in day["tasks"]
        )
        assert scheduled_minutes == plan["total_minutes"]
        assert all(
            day["total_minutes"] <= 90
            for month in plan["months"]
            for week in month["weeks"]
            for day in week["days"]
        )


def test_study_plan_task_progress_can_be_updated_and_read(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        generated = client.post("/api/study-plans/generate", json={
            "target_date": (date.today() + timedelta(days=7)).isoformat(),
            "availability": {"6": 60},
            "session_minutes": 30,
        })
        assert generated.status_code == 201
        plan = generated.json()
        task = plan["months"][0]["weeks"][0]["days"][0]["tasks"][0]

        updated = client.patch(
            f"/api/study-plans/{plan['id']}/tasks/{task['id']}",
            json={"status": "completed", "actual_minutes": 25, "note": "解き直し完了"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "completed"

        fetched = client.get(f"/api/study-plans/{plan['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["progress"][task["id"]]["actual_minutes"] == 25
        assert fetched.json()["progress"][task["id"]]["note"] == "解き直し完了"


def test_study_plan_rejects_invalid_availability_and_unknown_task(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        invalid = client.post("/api/study-plans/generate", json={
            "target_date": (date.today() + timedelta(days=7)).isoformat(),
            "availability": {"8": 60},
        })
        assert invalid.status_code == 422

        generated = client.post("/api/study-plans/generate", json={
            "target_date": (date.today() + timedelta(days=7)).isoformat(),
            "availability": {"6": 60},
        })
        assert generated.status_code == 201
        plan_id = generated.json()["id"]
        missing = client.patch(
            f"/api/study-plans/{plan_id}/tasks/not-a-real-task",
            json={"status": "completed"},
        )
        assert missing.status_code == 404


def test_study_plans_are_isolated_by_exam_mode(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        payload = {
            "target_date": (date.today() + timedelta(days=7)).isoformat(),
            "availability": {"6": 60},
        }
        high_school = client.post(
            "/api/study-plans/generate", json=payload,
            headers={"X-Exam-Mode": "high_school"},
        )
        university = client.post(
            "/api/study-plans/generate", json=payload,
            headers={"X-Exam-Mode": "university"},
        )
        assert high_school.status_code == 201
        assert university.status_code == 201
        assert high_school.json()["id"] != university.json()["id"]
        assert len(client.get(
            "/api/study-plans", headers={"X-Exam-Mode": "high_school"}
        ).json()) == 1
        assert len(client.get(
            "/api/study-plans", headers={"X-Exam-Mode": "university"}
        ).json()) == 1


def test_ai_provider_only_changes_task_wording(tmp_path, monkeypatch):
    import json

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "items": [{
                                "subject": "数学",
                                "unit": "二次関数",
                                "title": "二次関数の最大・最小を整理",
                                "instructions": "定義域を確認し、グラフと式の両方で最大値・最小値を求める",
                            }]
                        }, ensure_ascii=False)
                    }
                }]
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, headers, json):
            assert url.endswith("/chat/completions")
            assert headers["Authorization"] == "Bearer test-secret"
            return FakeResponse()

    monkeypatch.setenv("STUDY_PLANNER_API_KEY", "test-secret")
    monkeypatch.setattr(planning.httpx, "AsyncClient", FakeAsyncClient)

    with make_client(tmp_path, monkeypatch) as client:
        client.post("/api/scores", json={
            "date": date.today().isoformat(),
            "exam_name": "確認模試",
            "exam_type": "模試",
            "subject": "数学",
            "score": 50,
            "max_score": 100,
        })
        client.post("/api/questions", json={
            "date": date.today().isoformat(),
            "exam_name": "確認模試",
            "exam_type": "模試",
            "subject": "数学",
            "unit": "二次関数",
            "correct": False,
        })
        # make_client clears the key by design; set it again after setup.
        monkeypatch.setenv("STUDY_PLANNER_API_KEY", "test-secret")
        response = client.post("/api/study-plans/generate", json={
            "target_date": (date.today() + timedelta(days=7)).isoformat(),
            "availability": {"6": 50},
        })

        assert response.status_code == 201
        plan = response.json()
        assert plan["generation_mode"] == "ai_assisted"
        assert plan["ai_status"] == "generated"
        task = plan["months"][0]["weeks"][0]["days"][0]["tasks"][0]
        assert task["title"] == "二次関数の最大・最小を整理"
        assert task["duration_minutes"] == 50
