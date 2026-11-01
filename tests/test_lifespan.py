import sqlite3

from fastapi.testclient import TestClient

import api.main as api


def test_lifespan_initializes_database_and_core_tables(tmp_path, monkeypatch):
    database_path = tmp_path / "exam_strategy.sqlite3"
    monkeypatch.setattr(api, "DB", database_path)

    with TestClient(api.app):
        assert database_path.exists()
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

    assert {"scores", "questions", "settings", "schools", "school_rules"} <= tables
