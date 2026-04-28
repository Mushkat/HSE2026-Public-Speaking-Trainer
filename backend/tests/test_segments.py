import uuid

from sqlalchemy import text

from app.models.session import Session as SessionModel
from app.models.transcript_segment import TranscriptSegment
from app.services.transcript_segments import build_semantic_segments
from test_sessions import register_and_login


def test_build_semantic_segments_respects_pause_boundaries():
    words = [
        {"token": "Здравствуйте", "start": 0.0, "end": 0.6},
        {"token": "коллеги", "start": 0.7, "end": 1.2},
        {"token": "сегодня", "start": 1.3, "end": 1.8},
        {"token": "обсудим", "start": 1.9, "end": 2.4},
        {"token": "план", "start": 2.5, "end": 3.0},
        {"token": "проекта", "start": 3.1, "end": 3.7},
        {"token": "и", "start": 3.8, "end": 4.0},
        {"token": "риски", "start": 4.1, "end": 4.7},
        {"token": "подробно", "start": 4.8, "end": 5.5},
        {"token": "разберем", "start": 5.6, "end": 6.2},
        {"token": "детали", "start": 6.3, "end": 7.0},
        {"token": "сегодня.", "start": 7.1, "end": 7.8},
        {"token": "итак", "start": 9.2, "end": 9.6},
        {"token": "переходим", "start": 9.7, "end": 10.3},
        {"token": "к", "start": 10.4, "end": 10.6},
        {"token": "выводам", "start": 10.7, "end": 11.2},
        {"token": "и", "start": 11.3, "end": 11.5},
        {"token": "следующим", "start": 11.6, "end": 12.2},
        {"token": "шагам", "start": 12.3, "end": 12.9},
        {"token": "по", "start": 13.0, "end": 13.2},
        {"token": "запуску", "start": 13.3, "end": 13.9},
        {"token": "работ.", "start": 14.0, "end": 14.6},
        {"token": "Также", "start": 14.7, "end": 15.3},
        {"token": "уточним", "start": 15.4, "end": 16.0},
        {"token": "сроки", "start": 16.1, "end": 16.7},
        {"token": "и", "start": 16.8, "end": 17.0},
        {"token": "критерии", "start": 17.1, "end": 17.7},
        {"token": "успеха.", "start": 17.8, "end": 18.4},
    ]

    segments = build_semantic_segments("", words, 19.0)

    assert len(segments) == 1
    assert segments[0]["start_sec"] == 0.0
    assert 12 <= (segments[0]["end_sec"] - segments[0]["start_sec"]) <= 32
    assert segments[0]["text"].endswith(".")


def test_build_semantic_segments_prefers_sentence_end_near_target():
    words = []
    t = 0.0
    tokens = [
        "Сегодня", "разберем", "структуру", "выступления", "и", "подготовку", "к", "встрече.",
        "Во-первых", "нужно", "четко", "сформулировать", "цель", "и", "ожидаемый", "результат.",
        "Далее", "переходим", "к", "плану", "действий", "на", "неделю.",
        "Потом", "обсудим", "риски", "и", "варианты", "смягчения", "для", "команды.",
        "В", "итоге", "фиксируем", "дедлайны", "и", "ответственных", "на", "этапах.",
    ]
    for token in tokens:
        words.append({"token": token, "start": round(t, 2), "end": round(t + 0.85, 2)})
        t += 0.95

    segments = build_semantic_segments("", words, t)
    assert len(segments) >= 2
    assert all(12 <= (item["end_sec"] - item["start_sec"]) <= 32 for item in segments[:-1])
    assert segments[0]["text"].endswith(".")


def test_build_semantic_segments_quality_for_long_speech():
    words = []
    t = 0.0
    for block in range(120):
        token = "и" if block % 17 == 0 else f"слово{block}"
        punctuation = "." if block % 28 == 0 else ""
        words.append({"token": f"{token}{punctuation}", "start": round(t, 2), "end": round(t + 2.1, 2)})
        t += 2.3
        if block in {30, 61, 95}:
            t += 1.6

    segments = build_semantic_segments("", words, t)
    durations = [item["end_sec"] - item["start_sec"] for item in segments]
    avg_duration = sum(durations) / len(durations)

    assert avg_duration >= 12
    assert len(segments) < 20
    assert all(not item["text"].split()[-1].lower().strip(".,!?") in {"и", "а", "но"} for item in segments[:-1])


def test_get_segments_returns_ordered_with_rewrites(client, db_session):
    token = register_and_login(client, "segments-owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Segments"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)
    session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()

    seg1 = TranscriptSegment(session_id=session.id, idx=0, start_sec=0, end_sec=8, text="Первый блок", word_start_idx=0, word_end_idx=10)
    seg2 = TranscriptSegment(session_id=session.id, idx=1, start_sec=8, end_sec=16, text="Второй блок", word_start_idx=11, word_end_idx=20)
    db_session.add_all([seg1, seg2])
    db_session.commit()

    rewrite_response = client.post(
        f"/sessions/{session_id}/segments/{seg1.id}/rewrite",
        headers=headers,
        json={"kind": "short"},
    )
    assert rewrite_response.status_code == 200
    assert rewrite_response.json()["kind"] == "short"
    assert "text" in rewrite_response.json()

    response = client.get(f"/sessions/{session_id}/segments", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [item["idx"] for item in payload] == [0, 1]
    assert payload[0]["rewrites"]["short"]["kind"] == "short"


def test_segment_rewrite_bullets_and_ownership(client, db_session):
    owner_token = register_and_login(client, "segments-owner2@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    session_id = client.post("/sessions", json={"title": "Segments ownership"}, headers=owner_headers).json()["id"]
    session = db_session.query(SessionModel).filter(SessionModel.id == uuid.UUID(session_id)).first()
    segment = TranscriptSegment(session_id=session.id, idx=0, start_sec=0, end_sec=10, text="Это длинный блок для пунктов.", word_start_idx=0, word_end_idx=10)
    db_session.add(segment)
    db_session.commit()

    bullets_response = client.post(
        f"/sessions/{session_id}/segments/{segment.id}/rewrite",
        headers=owner_headers,
        json={"kind": "bullets"},
    )
    assert bullets_response.status_code == 200
    bullets_payload = bullets_response.json()
    assert bullets_payload["kind"] == "bullets"
    assert isinstance(bullets_payload["bullets"], list)
    assert 3 <= len(bullets_payload["bullets"]) <= 6
    assert all(len(item) <= 90 for item in bullets_payload["bullets"])

    intruder_token = register_and_login(client, "segments-intruder@example.com")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}
    forbidden = client.get(f"/sessions/{session_id}/segments", headers=intruder_headers)
    assert forbidden.status_code == 404


def test_segments_endpoints_handle_missing_tables_gracefully(client, db_session):
    token = register_and_login(client, "segments-missing@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "No segment tables"}, headers=headers).json()["id"]

    db_session.execute(text("DROP TABLE segment_rewrites"))
    db_session.execute(text("DROP TABLE transcript_segments"))
    db_session.commit()

    list_response = client.get(f"/sessions/{session_id}/segments", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json() == []

    fake_segment_id = str(uuid.uuid4())
    rewrite_response = client.post(
        f"/sessions/{session_id}/segments/{fake_segment_id}/rewrite",
        headers=headers,
        json={"kind": "short"},
    )
    assert rewrite_response.status_code == 503


def test_segment_rewrite_short_shape(client, db_session):
    token = register_and_login(client, "segments-short-shape@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Rewrite short"}, headers=headers).json()["id"]
    session = db_session.query(SessionModel).filter(SessionModel.id == uuid.UUID(session_id)).first()
    segment = TranscriptSegment(
        session_id=session.id,
        idx=0,
        start_sec=0,
        end_sec=20,
        text="Сегодня мы подробно обсудим план проекта, затем рассмотрим риски и определим ответственных за каждый этап.",
        word_start_idx=0,
        word_end_idx=30,
    )
    db_session.add(segment)
    db_session.commit()

    short_response = client.post(
        f"/sessions/{session_id}/segments/{segment.id}/rewrite",
        headers=headers,
        json={"kind": "short"},
    )
    assert short_response.status_code == 200
    payload = short_response.json()
    assert payload["kind"] == "short"
    assert isinstance(payload["text"], str)
    assert payload["text"]
    assert len(payload["text"]) <= 220
