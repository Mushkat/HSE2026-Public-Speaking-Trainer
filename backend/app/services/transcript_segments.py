import json
import logging
import re
from uuid import uuid4
from collections import Counter

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.local_llm import LocalLLMOptions, get_local_llm_client, is_llm_enabled

from app.models.segment_rewrite import SegmentRewrite
from app.models.transcript import Transcript as TranscriptModel
from app.models.transcript_segment import TranscriptSegment

PAUSE_BOUNDARY_SEC = 1.2
WEAK_PAUSE_BOUNDARY_SEC = 0.8
MAX_SEGMENT_DURATION_SEC = 32.0
MIN_SEGMENT_DURATION_SEC = 12.0
TARGET_SEGMENT_SEC = 18.0
MIN_SEGMENT_WORDS = 25
MAX_SEGMENT_WORDS = 85
TOPIC_SHIFT_MIN_DURATION_SEC = 14.0
TOPIC_SHIFT_TOKENS = {"итак", "во-первых", "во-вторых", "подытожим", "в итоге", "главное", "переходим", "далее"}
TOKEN_RE = re.compile(r"[\w\-']+", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|[\n\r]+")
CLAUSE_SPLIT_RE = re.compile(r"[.!?…;:]+|(?:\s+-\s+)|,\s+(?=(?:что|чтобы|когда|если|но|а|и)\b)", re.IGNORECASE)
FILLER_WORDS = {"ну", "как бы", "типа", "в общем", "короче", "это", "значит", "собственно", "вот"}
SENTENCE_END_RE = re.compile(r"[.!?…]+$")
JOINER_TOKENS = {"и", "а", "но"}

logger = logging.getLogger(__name__)


def has_segments_tables(db: Session) -> bool:
    bind = db.get_bind()
    inspector = inspect(bind)
    return inspector.has_table("transcript_segments") and inspector.has_table("segment_rewrites")


def _normalize_token(value: str) -> str:
    return value.lower().replace("ё", "е").strip(" ,.!?:;\"'()[]{}")


def _is_topic_shift(token: str) -> bool:
    normalized = _normalize_token(token)
    return normalized in TOPIC_SHIFT_TOKENS


def _is_sentence_end(token: str) -> bool:
    return bool(SENTENCE_END_RE.search(str(token or "").strip()))


def _build_segment_text(words: list[dict]) -> str:
    return " ".join((str(w.get("token", "")).strip() for w in words if str(w.get("token", "")).strip())).strip()


def _build_synthetic_words(text: str, duration_seconds: float) -> list[dict]:
    tokens = [t for t in TOKEN_RE.findall(text or "") if t.strip()]
    if not tokens:
        return []
    safe_duration = max(float(duration_seconds or 0), 1.0)
    avg = safe_duration / max(len(tokens), 1)
    words: list[dict] = []
    t = 0.0
    for token in tokens:
        start = t
        end = min(safe_duration, t + avg)
        words.append({"token": token, "start": start, "end": end, "confidence": None, "low_confidence": False})
        t = end
    if words:
        words[-1]["end"] = safe_duration
    return words


def _prepared_words(transcript_text: str | None, transcript_words: list[dict] | None, duration_seconds: float) -> list[dict]:
    words = [w for w in (transcript_words or []) if isinstance(w, dict)]
    words = sorted(words, key=lambda item: float(item.get("start", 0) or 0))
    if not words:
        return _build_synthetic_words(transcript_text or "", duration_seconds)

    return words


def _word_start(words: list[dict], idx: int) -> float:
    return float(words[idx].get("start", 0) or 0)


def _word_end(words: list[dict], idx: int) -> float:
    return float(words[idx].get("end", words[idx].get("start", 0)) or 0)


def _segment_duration(words: list[dict], start_idx: int, end_idx: int) -> float:
    return _word_end(words, end_idx) - _word_start(words, start_idx)


def _gap_after(words: list[dict], idx: int) -> float:
    if idx + 1 >= len(words):
        return 0.0
    return max(0.0, _word_start(words, idx + 1) - _word_end(words, idx))


def _is_good_boundary(words: list[dict], seg_start_idx: int, boundary_idx: int, target_reached: bool) -> tuple[int, int] | None:
    token = str(words[boundary_idx].get("token", ""))
    next_token = str(words[boundary_idx + 1].get("token", "")) if boundary_idx + 1 < len(words) else ""
    gap = _gap_after(words, boundary_idx)
    seg_duration = _segment_duration(words, seg_start_idx, boundary_idx)

    if _is_sentence_end(token):
        return (4, boundary_idx)
    if gap >= PAUSE_BOUNDARY_SEC:
        return (3, boundary_idx)
    if target_reached and gap >= WEAK_PAUSE_BOUNDARY_SEC:
        return (2, boundary_idx)
    if seg_duration >= TOPIC_SHIFT_MIN_DURATION_SEC and _is_topic_shift(next_token):
        return (1, boundary_idx)
    return None


def _choose_boundary_in_window(words: list[dict], seg_start_idx: int, window_start: int, window_end: int, target_reached: bool) -> int | None:
    candidates: list[tuple[int, int]] = []
    for idx in range(window_start, window_end + 1):
        candidate = _is_good_boundary(words, seg_start_idx, idx, target_reached)
        if candidate is None:
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -item[1]))
    return candidates[0][1]


def build_semantic_segments(transcript_text: str | None, transcript_words: list[dict] | None, duration_seconds: float) -> list[dict]:
    words = _prepared_words(transcript_text, transcript_words, duration_seconds)
    if not words:
        return []

    segments: list[dict] = []
    seg_start = 0

    while seg_start < len(words):
        min_end = min(len(words) - 1, seg_start + MIN_SEGMENT_WORDS - 1)
        probe = min_end

        while probe < len(words) - 1:
            duration = _segment_duration(words, seg_start, probe)
            if duration >= TARGET_SEGMENT_SEC:
                break
            probe += 1

        target_reached = _segment_duration(words, seg_start, probe) >= TARGET_SEGMENT_SEC
        window_start_t = _word_start(words, seg_start) + max(TARGET_SEGMENT_SEC - 4.0, MIN_SEGMENT_DURATION_SEC)
        window_end_t = _word_start(words, seg_start) + min(TARGET_SEGMENT_SEC + 6.0, MAX_SEGMENT_DURATION_SEC)

        window_start = max(seg_start, next((i for i in range(seg_start, len(words)) if _word_end(words, i) >= window_start_t), probe))
        window_end = min(len(words) - 1, next((i for i in range(window_start, len(words)) if _word_end(words, i) >= window_end_t), len(words) - 1))

        boundary = _choose_boundary_in_window(words, seg_start, window_start, window_end, target_reached)

        if boundary is None:
            hard_end = min(len(words) - 1, max(seg_start + MIN_SEGMENT_WORDS - 1, seg_start + MAX_SEGMENT_WORDS - 1))
            while hard_end < len(words) - 1 and _segment_duration(words, seg_start, hard_end) < MAX_SEGMENT_DURATION_SEC and (hard_end - seg_start + 1) < MAX_SEGMENT_WORDS:
                hard_end += 1

            back_window_start_t = max(_word_start(words, seg_start), _word_end(words, hard_end) - 6.0)
            back_window_start = next((i for i in range(seg_start, hard_end + 1) if _word_start(words, i) >= back_window_start_t), seg_start)
            boundary = _choose_boundary_in_window(words, seg_start, back_window_start, hard_end, target_reached=True)
            if boundary is None:
                boundary = hard_end

        if boundary < seg_start:
            boundary = min(len(words) - 1, seg_start + MIN_SEGMENT_WORDS - 1)

        if boundary + 1 < len(words):
            tail_tokens = [_normalize_token(str(words[j].get("token", ""))) for j in range(max(seg_start, boundary - 2), boundary + 1)]
            no_pause = _gap_after(words, boundary) < WEAK_PAUSE_BOUNDARY_SEC
            if tail_tokens and tail_tokens[-1] in JOINER_TOKENS and no_pause:
                extension = min(len(words) - 1, boundary + 4)
                better = _choose_boundary_in_window(words, seg_start, boundary + 1, extension, target_reached=True)
                if better is not None:
                    boundary = better

        seg_words = words[seg_start : boundary + 1]
        if not seg_words:
            seg_start = boundary + 1
            continue
        segments.append(
            {
                "idx": len(segments),
                "start_sec": _word_start(words, seg_start),
                "end_sec": _word_end(words, boundary),
                "text": _build_segment_text(seg_words),
                "word_start_idx": seg_start,
                "word_end_idx": boundary,
            }
        )
        seg_start = boundary + 1

    if len(segments) >= 2:
        last = segments[-1]
        prev = segments[-2]
        last_dur = float(last["end_sec"]) - float(last["start_sec"])
        if last_dur < MIN_SEGMENT_DURATION_SEC and int(last["word_end_idx"]) > int(last["word_start_idx"]):
            prev["end_sec"] = last["end_sec"]
            prev["word_end_idx"] = last["word_end_idx"]
            prev_words = words[int(prev["word_start_idx"]) : int(prev["word_end_idx"]) + 1]
            prev["text"] = _build_segment_text(prev_words)
            segments.pop()

    return [segment for segment in segments if segment["text"]]


def replace_session_segments(
    db: Session,
    *,
    session_id,
    transcript_text: str | None,
    transcript_words: list[dict] | None,
    duration_seconds: float,
) -> list[TranscriptSegment]:
    if not has_segments_tables(db):
        logger.warning("segment tables are missing; skipping segment replacement", extra={"session_id": str(session_id)})
        return []

    built = build_semantic_segments(transcript_text, transcript_words, duration_seconds)
    db.query(TranscriptSegment).filter(TranscriptSegment.session_id == session_id).delete(synchronize_session=False)
    created: list[TranscriptSegment] = []
    for item in built:
        row = TranscriptSegment(session_id=session_id, **item)
        db.add(row)
        created.append(row)
    db.flush()
    return created


def ensure_segments_word_indices(db: Session, *, session_id) -> list[TranscriptSegment]:
    rows = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.idx.asc())
        .all()
    )
    if not rows:
        return rows

    transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session_id).first()
    words = transcript.words if transcript and isinstance(transcript.words, list) else []
    if not words:
        return rows

    max_idx = len(words) - 1
    invalid = any(
        row.word_start_idx is None
        or row.word_end_idx is None
        or row.word_start_idx < 0
        or row.word_end_idx < row.word_start_idx
        or row.word_end_idx > max_idx
        for row in rows
    )
    if not invalid:
        return rows

    logger.info("rebuilding invalid transcript segments to restore word index alignment", extra={"session_id": str(session_id)})
    last_end = max((float(item.get("end", item.get("start", 0)) or 0) for item in words if isinstance(item, dict)), default=0.0)
    replace_session_segments(
        db,
        session_id=session_id,
        transcript_text=transcript.text if transcript else None,
        transcript_words=words,
        duration_seconds=last_end,
    )
    db.flush()
    return (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.idx.asc())
        .all()
    )


def rewrite_short_fallback(text: str) -> dict:
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not parts:
        cleaned = " ".join(text.split())
        return {"text": cleaned[:240]}

    scored: list[tuple[int, str]] = []
    lowered = [p.lower() for p in parts]
    word_counts = Counter(TOKEN_RE.findall(" ".join(lowered)))
    for sentence in parts:
        tokens = [t.lower() for t in TOKEN_RE.findall(sentence)]
        score = sum(word_counts[t] for t in tokens if t not in FILLER_WORDS)
        scored.append((score, sentence))

    selected = [parts[0]]
    if len(parts) > 1:
        best = max(scored[1:], key=lambda item: item[0])[1]
        if best != selected[0]:
            selected.append(best)
    compact = " ".join(selected[:2])
    compact = re.sub(r"\b(ну|как бы|типа|в общем|короче|значит|собственно)\b", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\s+", " ", compact).strip(" ,.;")
    return {"text": compact[:220]}


def rewrite_bullets_fallback(text: str) -> dict:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    clauses = [item.strip(" ,.;:!?-") for item in CLAUSE_SPLIT_RE.split(normalized) if item.strip(" ,.;:!?-")]
    if not clauses:
        clauses = [item.strip() for item in SENTENCE_SPLIT_RE.split(normalized) if item.strip()]
    if not clauses and normalized:
        clauses = [normalized]

    bullets: list[str] = []
    for clause in clauses:
        cleaned = re.sub(r"\b(ну|как бы|типа|в общем|короче|значит|собственно|вот)\b", "", clause, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:!?-")
        tokens = [token for token in cleaned.split() if token]
        if len(tokens) < 2:
            continue
        phrase = " ".join(tokens[:12]).strip(" ,.;:!?-")[:90]
        normalized_phrase = phrase.lower()
        if phrase and normalized_phrase not in {" ".join(existing.split()).lower() for existing in bullets}:
            bullets.append(phrase)
        if len(bullets) >= 4:
            break

    if len(bullets) < 2 and normalized:
        words = normalized.split()
        chunk_size = max(4, min(10, max(1, len(words) // 3)))
        for start in range(0, len(words), chunk_size):
            phrase = " ".join(words[start : start + chunk_size]).strip(" ,.;:!?-")[:90]
            normalized_phrase = phrase.lower()
            if len(phrase.split()) >= 2 and normalized_phrase not in {" ".join(existing.split()).lower() for existing in bullets}:
                bullets.append(phrase)
            if len(bullets) >= 4:
                break

    if len(bullets) < 3 and normalized:
        words = normalized.split()
        if words:
            target_chunks = min(4, max(3, len(bullets) + 1))
            approx_chunk = max(2, (len(words) + target_chunks - 1) // target_chunks)
            for index in range(target_chunks):
                start = min(index * approx_chunk, max(len(words) - 2, 0))
                end = min(len(words), start + approx_chunk)
                phrase = " ".join(words[start:end]).strip(" ,.;:!?-")[:90]
                normalized_phrase = " ".join(phrase.split()).lower()
                if len(phrase.split()) >= 2 and normalized_phrase not in {" ".join(existing.split()).lower() for existing in bullets}:
                    bullets.append(phrase)
                if len(bullets) >= 4:
                    break

    return {"bullets": bullets[:4]}


def _parse_json_payload(raw: str) -> dict | None:
    try:
        parsed = json.loads(raw.strip())
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _try_local_llm_json(kind: str, text: str) -> tuple[dict | None, str | None]:
    if not is_llm_enabled():
        return None, None
    client = get_local_llm_client()
    if not client:
        return None, None

    compact = re.sub(r"\s+", " ", text or "").strip()[:900]
    if not compact:
        return None, None

    if kind == "short":
        system_prompt = "Ты помощник по улучшению речи. Возвращай только валидный JSON по схеме запроса."
        user_prompt = (
            "Сделай короткую и ясную версию фрагмента на русском, сохрани смысл.\n"
            "Верни строго JSON: { \"text\": \"...\" }\n\n"
            f"Фрагмент:\n<<<\n{compact}\n>>>"
        )
        max_tokens = min(160, settings.local_llm_max_tokens)
        payload = client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            options=LocalLLMOptions(max_tokens=max_tokens, temperature=settings.local_llm_temperature),
            trace_id=f"segment:{kind}",
            purpose="segment_rewrite",
            request_id=str(uuid4()),
            session_id="segment_rewrite",
        )
    else:
        system_prompt = "Ты - русскоязычный редактор. Пиши только по-русски. Без воды. Без выдуманных фактов."
        user_prompt = (
            "Перепиши фрагмент в виде 2–4 коротких пунктов.\n"
            "Требования: один пункт = одна короткая фраза, без вводных слов, без повторов.\n"
            "Верни строго JSON:\n"
            '{ "bullets": ["...", "..."] }\n\n'
            f"Фрагмент:\n<<<{compact}>>>"
        )
        max_tokens = min(160, settings.local_llm_max_tokens)
        payload = client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            options=LocalLLMOptions(max_tokens=max_tokens, temperature=0.2),
            trace_id=f"segment:{kind}",
            purpose="segment_rewrite",
            request_id=str(uuid4()),
            session_id="segment_rewrite",
        )
        if not payload:
            payload = client.generate_json(
                system_prompt=system_prompt,
                user_prompt=f"{user_prompt}\n\nВерни валидный JSON без текста вне JSON.",
                options=LocalLLMOptions(max_tokens=max_tokens, temperature=0.2),
                trace_id=f"segment:{kind}:retry_json",
                purpose="segment_rewrite",
                request_id=str(uuid4()),
                session_id="segment_rewrite",
            )

    if not payload:
        return None, None
    return payload, "local_llm"


def generate_segment_rewrite(kind: str, text: str) -> tuple[dict, str]:
    llm_payload, model_name = _try_local_llm_json(kind, text)
    if llm_payload:
        if kind == "short" and isinstance(llm_payload.get("text"), str):
            return {"text": str(llm_payload.get("text", "")).strip()[:220]}, "local_llm"
        if kind == "bullets" and isinstance(llm_payload.get("bullets"), list):
            bullets = [str(item).strip()[:90] for item in llm_payload.get("bullets", []) if str(item).strip()]
            if bullets:
                return {"bullets": bullets[:4]}, "local_llm"

    if kind == "short":
        return rewrite_short_fallback(text), "fallback"
    return rewrite_bullets_fallback(text), "fallback"


def upsert_segment_rewrite(db: Session, *, segment_id, kind: str, content: dict, model: str) -> SegmentRewrite:
    rewrite = (
        db.query(SegmentRewrite)
        .filter(SegmentRewrite.segment_id == segment_id, SegmentRewrite.kind == kind)
        .first()
    )
    if rewrite:
        rewrite.content = content
        rewrite.model = model
    else:
        rewrite = SegmentRewrite(segment_id=segment_id, kind=kind, content=content, model=model)
        db.add(rewrite)
    db.flush()
    return rewrite
