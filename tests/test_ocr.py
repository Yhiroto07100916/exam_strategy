import io
from types import SimpleNamespace

import fitz
from fastapi.testclient import TestClient

import api.main as api
import api.ocr as ocr


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB", tmp_path / "ocr-test.sqlite3")
    return TestClient(api.app)


def make_pdf():
    document = fitz.open()
    document.new_page()
    content = document.tobytes()
    document.close()
    return content


def test_parse_ocr_candidates():
    candidates = ocr.parse_ocr_candidates([
        "国語 80/100\n数学 72／100\n英語 120/100\n判定 A"
    ])
    assert len(candidates) == 2
    assert candidates[0]["subject"] == "国語"
    assert candidates[0]["score_candidate"] == 80
    assert candidates[1]["subject"] == "数学"
    assert candidates[1]["max_score_candidate"] == 100


def test_ocr_preview_requires_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: None)
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/import/pdf/ocr-preview",
            files={"file": ("mock.pdf", make_pdf(), "application/pdf")},
        )
        assert response.status_code == 503
        assert "Tesseract" in response.json()["detail"]


def test_ocr_preview_returns_candidates_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(
        ocr.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="jpn\neng", stderr=""),
    )
    monkeypatch.setattr(
        ocr.pytesseract, "image_to_string",
        lambda *args, **kwargs: "国語 80/100\n数学 72/100",
    )
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/import/pdf/ocr-preview",
            files={"file": ("mock.pdf", make_pdf(), "application/pdf")},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["requires_manual_confirmation"] is True
        assert len(result["candidates"]) == 2
        assert client.get("/api/scores").json() == []


def test_confirmed_ocr_import_saves_and_deduplicates(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        score = {
            "date": "2026-10-01", "exam_name": "OCR模試", "exam_type": "模試",
            "subject": "国語", "score": 80, "max_score": 100,
        }
        first = client.post("/api/import/ocr-confirm", json={"scores": [score]})
        assert first.status_code == 200
        assert first.json() == {"imported": 1, "duplicates": 0}

        second = client.post("/api/import/ocr-confirm", json={"scores": [score]})
        assert second.status_code == 200
        assert second.json() == {"imported": 0, "duplicates": 1}
        assert len(client.get("/api/scores").json()) == 1
