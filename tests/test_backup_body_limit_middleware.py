import asyncio
import json

from api.main import BackupRestoreBodyLimitMiddleware


def invoke_middleware(headers, chunks, max_bytes=4):
    pending_messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    receive_calls = 0
    app_calls = []
    received_bodies = []
    received_message_counts = []
    sent_messages = []

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        if pending_messages:
            return pending_messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent_messages.append(message)

    async def downstream(scope, downstream_receive, downstream_send):
        app_calls.append(True)
        body = bytearray()
        message_count = 0
        while True:
            message = await downstream_receive()
            message_count += 1
            if message["type"] == "http.disconnect":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        received_bodies.append(bytes(body))
        received_message_counts.append(message_count)
        await downstream_send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await downstream_send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/backup/restore",
        "headers": headers,
    }
    middleware = BackupRestoreBodyLimitMiddleware(downstream, max_bytes=max_bytes)
    asyncio.run(middleware(scope, receive, send))

    status = next(
        message["status"]
        for message in sent_messages
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(response_body) if response_body else None, app_calls, received_bodies, receive_calls, received_message_counts


def test_backup_body_limit_rejects_chunked_body_without_content_length():
    status, body, app_calls, _, _, _ = invoke_middleware(
        [], [b"abc", b"de"]
    )

    assert status == 413
    assert body == {"detail": "バックアップファイルは20MB以下にしてください"}
    assert app_calls == []


def test_backup_body_limit_rejects_underreported_content_length():
    status, body, app_calls, _, _, _ = invoke_middleware(
        [(b"content-length", b"2")], [b"abcde"]
    )

    assert status == 413
    assert body == {"detail": "バックアップファイルは20MB以下にしてください"}
    assert app_calls == []


def test_backup_body_limit_rejects_declared_oversize_before_reading_body():
    status, body, app_calls, _, receive_calls, _ = invoke_middleware(
        [(b"content-length", b"5")], [b"abcde"]
    )

    assert status == 413
    assert body == {"detail": "バックアップファイルは20MB以下にしてください"}
    assert app_calls == []
    assert receive_calls == 0


def test_backup_body_limit_rejects_malformed_or_duplicate_content_length():
    for headers in (
        [(b"content-length", b"1.5")],
        [(b"content-length", b"4"), (b"content-length", b"4")],
        [(b"content-length", b"4"), (b"transfer-encoding", b"chunked")],
        [(b"content-length", b"9" * 5000)],
    ):
        status, body, app_calls, _, receive_calls = invoke_middleware(
            headers, [b"data"]
        )

        assert status == 400
        assert body == {"detail": "Content-Lengthヘッダーが不正です"}
        assert app_calls == []
        assert receive_calls == 0


def test_backup_body_limit_rejects_content_length_mismatch():
    status, body, app_calls, _, _, _ = invoke_middleware(
        [(b"content-length", b"3")], [b"ab"]
    )

    assert status == 400
    assert body == {"detail": "Content-Lengthヘッダーが不正です"}
    assert app_calls == []


def test_backup_body_limit_accepts_exact_limit_and_replays_all_chunks():
    status, body, app_calls, received_bodies, _, message_counts = invoke_middleware(
        [(b"content-length", b"4")], [b""] * 1000 + [b"ab", b"", b"cd", b""]
    )

    assert status == 204
    assert body is None
    assert app_calls == [True]
    assert received_bodies == [b"abcd"]
    assert message_counts == [1]


def test_backup_body_limit_does_not_intercept_other_routes():
    pending_messages = [{"type": "http.request", "body": b"large", "more_body": False}]
    app_calls = []

    async def receive():
        return pending_messages.pop(0)

    async def send(message):
        pass

    async def downstream(scope, downstream_receive, downstream_send):
        app_calls.append(True)
        message = await downstream_receive()
        assert message["body"] == b"large"
        await downstream_send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await downstream_send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/scores",
        "headers": [],
    }
    middleware = BackupRestoreBodyLimitMiddleware(downstream, max_bytes=4)
    asyncio.run(middleware(scope, receive, send))

    assert app_calls == [True]
