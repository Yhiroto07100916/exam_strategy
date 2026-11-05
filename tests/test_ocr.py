from types import SimpleNamespace

import fitz
import pytest

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


def test_parse_ocr_candidates_prefers_explicit_score_fraction():
    candidates = ocr.parse_ocr_candidates([
        "国語 80/100 偏差値 65",
        "数学 72／100 合計 450/500",
        "10/01 国語 75/100",
    ])
    assert len(candidates) == 3
    assert candidates[0]["score_candidate"] == 80
    assert candidates[0]["max_score_candidate"] == 100
    assert candidates[1]["score_candidate"] == 72
    assert candidates[1]["max_score_candidate"] == 100
    assert candidates[2]["score_candidate"] == 75
    assert candidates[2]["max_score_candidate"] == 100


def test_parse_ocr_candidates_skips_ambiguous_unlabelled_numbers():
    candidates = ocr.parse_ocr_candidates([
        "国語 80点 偏差値 65",
        "数学 72点 100点",
        "英語 90",
    ])
    assert len(candidates) == 1
    assert candidates[0]["subject"] == "英語"
    assert candidates[0]["score_candidate"] == 90
    assert candidates[0]["max_score_candidate"] == 100

def test_confirmed_ocr_import_deduplicates_within_one_batch(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        score = {
            "date": "2026-10-01", "exam_name": "OCR模試", "exam_type": "模試",
            "subject": "国語", "score": 80, "max_score": 100,
        }
        response = client.post(
            "/api/import/ocr-confirm", json={"scores": [score, score]}
        )
        assert response.status_code == 200
        assert response.json() == {"imported": 1, "duplicates": 1}
        assert len(client.get("/api/scores").json()) == 1


def test_ocr_confirm_rejects_score_above_maximum_without_saving(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        score = {
            "date": "2026-10-01", "exam_name": "OCR模試", "exam_type": "模試",
            "subject": "国語", "score": 101, "max_score": 100,
        }
        response = client.post("/api/import/ocr-confirm", json={"scores": [score]})
        assert response.status_code == 422
        assert client.get("/api/scores").json() == []


def test_ocr_confirm_rejects_invalid_date_without_saving(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        score = {
            "date": "2026-02-30", "exam_name": "OCR模試", "exam_type": "模試",
            "subject": "国語", "score": 80, "max_score": 100,
        }
        response = client.post("/api/import/ocr-confirm", json={"scores": [score]})
        assert response.status_code == 422
        assert client.get("/api/scores").json() == []


def test_preview_pdf_ocr_reports_timeout_clearly(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(
        ocr.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="jpn\\neng", stderr=""),
    )

    def timeout(*args, **kwargs):
        raise RuntimeError("process timeout")

    monkeypatch.setattr(ocr.pytesseract, "image_to_string", timeout)
    with pytest.raises(RuntimeError, match="OCR処理がタイムアウトしました"):
        ocr.preview_pdf_ocr(make_pdf())


def test_preview_pdf_ocr_rejects_too_many_pages(monkeypatch):
    document = fitz.open()
    for _ in range(ocr.MAX_PDF_PAGES + 1):
        document.new_page()
    content = document.tobytes()
    document.close()

    monkeypatch.setattr(ocr.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(
        ocr.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="jpn\\neng", stderr=""),
    )
    with pytest.raises(ValueError, match="20ページまで"):
        ocr.preview_pdf_ocr(content)
