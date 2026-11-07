import sqlite3

from fastapi.testclient import TestClient

import api.main as api


def test_lifespan_initializes_database_and_core_tables_for_each_exam_mode(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "exam_strategy.sqlite3"
    university_database_path = tmp_path / "university_exam_strategy.sqlite3"
    monkeypatch.setattr(api, "DB", database_path)

    with TestClient(api.app):
        for path in (database_path, university_database_path):
            assert path.exists()
            with sqlite3.connect(path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            assert {
                "scores", "questions", "settings", "schools", "school_rules"
            } <= tables
