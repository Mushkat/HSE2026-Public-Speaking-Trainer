from __future__ import annotations

import logging
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.local_llm import get_local_llm_client, is_llm_enabled
from app.services.llm_blocks import generate_json_block, is_russian_text


_STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так",
    "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было",
    "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам", "ведь",
    "там", "потом", "себя", "ничего", "ей", "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы",
    "тебя", "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет",
    "ж", "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем", "ним", "здесь", "этом", "один",
    "почти", "мой", "тем", "чтобы", "нее", "кажется", "сейчас", "были", "куда", "зачем", "всех", "никогда", "можно",
    "при", "наконец", "два", "об", "другой", "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про",
    "всего", "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед",
    "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между",
    "это", "эта", "этих", "этим", "этими", "этот", "этого", "эту", "также", "очень", "просто", "тут", "там",
    "сегодня", "расскажу", "поговорим", "дальше", "следующий", "итог", "главный", "мысль", "выступления",
}
_FILLER_WORDS = {
    "ну", "как бы", "в общем", "в целом", "вот", "значит", "скажем так", "получается", "собственно",
}
_TIME_KEYS = ("t", "start", "start_sec")
_NOISE_PATTERNS = ("в 2025", "политик", "персональн", "паспорт", "личные данные")
_GENERIC_FALLBACK_QUESTIONS = [
    "В чём ваша главная мысль - что вы хотите, чтобы аудитория запомнила?",
    "Какая одна практическая рекомендация из вашего выступления самая важная?",
    "Какой пример лучше всего подтверждает ваш главный тезис?",
    "Что может пойти не так, и как вы предлагаете действовать в этом случае?",
    "Какой следующий шаг вы бы посоветовали человеку, который вас услышал?",
]
GOAL_RU_LABELS = {
    "inform": "информировать",
    "teach": "обучить",
    "persuade": "убедить",
    "sell": "продать",
    "inspire": "вдохновить",
    "entertain": "развлечь",
}
AUDIENCE_RU_LABELS = {
    "students": "студенты",
    "clients": "клиенты",
    "kids": "дети",
    "colleagues": "коллеги",
    "general": "широкая аудитория",
}
TONE_RU_LABELS = {
    "calm": "Спокойный",
    "energetic": "Энергичный",
    "friendly": "Дружелюбный",
    "formal": "Официальный",
}
PRESET_RU_LABELS = {
    "scientific_lecture": "Научная лекция",
    "conference_talk": "Доклад на конференции",
    "pitch_sales": "Питч / продажа",
    "interview_self_intro": "Интервью / самопрезентация",
    "storytelling": "Сторителлинг",
    "kids_lesson": "Урок для детей",
}

logger = logging.getLogger(__name__)
_COACHING_FALLBACK_REASONS = {
    "llm_disabled",
    "llm_unreachable",
    "timeout",
    "http_error",
    "empty_content",
    "json_extract_failed",
    "json_parse_failed",
    "schema_invalid",
    "filtered_all_items",
    "low_quality",
    "not_russian",
    "persistence_overwritten",
    "ui_mapping_wrong",
}
_LAST_BLOCK_OUTCOMES: dict[str, dict[str, Any]] = {}


def _debug_llm(event: str, **extra: Any) -> None:
    if settings.debug_llm:
        logger.warning(event, extra=extra)


def _debug_llm_quality(event: str, **extra: Any) -> None:
    if settings.debug_llm_quality:
        logger.warning(event, extra=extra)


def _llm_failure_reason(client: Any, default: str) -> str:
    meta = client.last_call_meta if client else {}
    if not isinstance(meta, dict):
        return default
    return str(meta.get("failure_reason") or meta.get("error_message") or default)


def _map_llm_failure_reason(reason: str) -> str:
    normalized = (reason or "").lower()
    if "timeout" in normalized:
        return "timeout"
    if normalized in {"request_exception", "connection_error"}:
        return "llm_unreachable"
    if normalized in {"json_fragment_not_found"}:
        return "json_extract_failed"
    if normalized in {"json_decode_error", "json_object_expected", "json_parse_failure"}:
        return "json_parse_failed"
    if normalized in {"empty_response", "empty_content"}:
        return "empty_content"
    if normalized in {"chat_choices_missing", "chat_message_content_missing", "invalid_payload", "llm_payload_not_object"}:
        return "schema_invalid"
    if "http" in normalized or "status" in normalized:
        return "http_error"
    return "http_error"


def _dump_block_debug_files(*, session_id: str, block: str, request_id: str, request_data: dict[str, Any], response_data: dict[str, Any], content: str, parse_error: str = "") -> None:
    if not settings.debug_llm:
        return
    base_dir = Path(settings.storage_root) / "debug" / "llm" / str(session_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{block}_{request_id}"
    (base_dir / f"{prefix}_request.json").write_text(json.dumps(request_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (base_dir / f"{prefix}_response.json").write_text(json.dumps(response_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (base_dir / f"{prefix}_content.txt").write_text(content or "", encoding="utf-8")
    (base_dir / f"{prefix}_parse_error.txt").write_text(parse_error or "", encoding="utf-8")


def _log_coaching_fallback(*, block: str, reason: str, details: str, request_id: str | None, session_id: str, request_data: dict[str, Any] | None = None, response_data: dict[str, Any] | None = None, content: str = "", parse_error: str = "") -> None:
    safe_reason = reason if reason in _COACHING_FALLBACK_REASONS else "low_quality"
    logger.warning("COACHING_FALLBACK block=%s reason=%s request_id=%s", block, safe_reason, request_id or "na")
    logger.warning("coaching fallback details", extra={"block": block, "details": details, "request_id": request_id})
    if request_id and (request_data or response_data or content or parse_error):
        _dump_block_debug_files(
            session_id=session_id,
            block=block,
            request_id=request_id,
            request_data=request_data or {},
            response_data=response_data or {},
            content=content,
            parse_error=parse_error,
        )


def _log_block_outcome(
    *,
    block: str,
    used: str,
    reason: str,
    session_id: str,
    request_id: str | None,
    latency_ms: int | None = None,
) -> None:
    safe_reason = reason if reason in _COACHING_FALLBACK_REASONS else "low_quality"
    logger.warning(
        "LLM_BLOCK=%s source=%s reason=%s session=%s req=%s latency=%s",
        block,
        "llm" if used == "llm" else "fallback",
        "null" if used == "llm" else safe_reason,
        session_id,
        request_id or "na",
        latency_ms if isinstance(latency_ms, int) else "na",
    )
    _LAST_BLOCK_OUTCOMES[block] = {
        "used": used,
        "reason": safe_reason if used == "fallback" else "llm",
        "request_id": request_id or "na",
        "session_id": session_id,
        "llm_latency_ms": latency_ms,
    }


def get_last_coaching_outcomes() -> dict[str, dict[str, str]]:
    return dict(_LAST_BLOCK_OUTCOMES)


def _metric_value(data: Any, *keys: str) -> float | None:
    current = data if isinstance(data, dict) else {}
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    if isinstance(current, (int, float)):
        return float(current)
    return None


def _metric_text(data: Any, *keys: str) -> str | None:
    current = data if isinstance(data, dict) else {}
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    return current if isinstance(current, str) else None


def _to_percent(value: float | None) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) * 100, 1) if value <= 1 else round(float(value), 1)


def _in_range(value: float | None, min_value: float | None, max_value: float | None) -> bool:
    if not isinstance(value, (int, float)) or not isinstance(min_value, (int, float)) or not isinstance(max_value, (int, float)):
        return False
    return float(min_value) <= float(value) <= float(max_value)


def _dist_to_range(value: float | None, min_value: float | None, max_value: float | None) -> float:
    if not isinstance(value, (int, float)) or not isinstance(min_value, (int, float)) or not isinstance(max_value, (int, float)):
        return -1.0
    if value < min_value:
        return float(min_value - value)
    if value > max_value:
        return float(value - max_value)
    return 0.0


def _fmt_sec(sec: float | int | None) -> str:
    if not isinstance(sec, (int, float)) or sec < 0:
        return ""
    safe = int(round(sec))
    hours, remainder = divmod(safe, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f" ({hours}:{minutes:02d}:{seconds:02d})"
    return f" ({minutes}:{seconds:02d})"


def _first_timecode(*collections: Any) -> float | None:
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            for key in _TIME_KEYS:
                value = item.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
    return None


def _rating_from_issues(count: int) -> str:
    if count == 0:
        return "good"
    if count <= 2:
        return "ok"
    return "bad"


@lru_cache(maxsize=1)
def _ascii_re() -> re.Pattern[str]:
    return re.compile(r"[A-Za-z]")


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip())


def _extract_keywords(transcript_text: str | None, segments: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    source_text = transcript_text or " ".join(seg.get("text", "") for seg in segments if isinstance(seg, dict))
    words = re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", source_text.lower())
    filtered = [w for w in words if w not in _STOPWORDS]
    if not filtered:
        return []
    return [word for word, _ in Counter(filtered).most_common(limit)]


def _segment_summary_bullets(segments: list[dict[str, Any]]) -> list[str]:
    if not segments:
        return [
            "Тема выступления обозначена, но без детализированного развертывания.",
            "Ключевые аргументы стоит подкрепить примерами и цифрами.",
            "В завершении добавьте конкретный следующий шаг для аудитории.",
        ]

    chosen = segments[:3] + ([segments[-1]] if len(segments) > 3 else [])
    bullets: list[str] = []
    for idx, seg in enumerate(chosen[:4]):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        bullets_rewrite = seg.get("bullets_rewrite")
        if idx == 0 and isinstance(bullets_rewrite, list) and bullets_rewrite:
            bullets.append(f"В начале вы обозначили: {bullets_rewrite[0][:120]}.")
        else:
            short = re.sub(r"\s+", " ", text)[:120]
            bullets.append(f"Ключевой фрагмент: {short}{'…' if len(text) > 120 else ''}")

    if len(bullets) < 3:
        bullets.append("Финал стоит завершать чётким призывом к действию или следующим шагом.")
    return bullets[:5]


def _fallback_summary_bullets_from_transcript(source_text: str, segments: list[dict[str, Any]]) -> list[str]:
    sentences = [_clean_sentence(item) for item in _sentence_split(source_text) if _clean_sentence(item)]
    bullets: list[str] = []
    for sentence in sentences:
        candidate = sentence
        if len(candidate) < 50:
            continue
        if len(candidate) > 160:
            candidate = candidate[:157].rstrip(" ,;:-") + "..."
        if not _is_near_duplicate(candidate, bullets):
            bullets.append(_normalize_bullet(candidate))
        if len(bullets) >= 7:
            break
    if len(bullets) >= 4:
        return bullets[:7]
    return _segment_summary_bullets(segments)[:5]


def _normalize_bullet(text: str) -> str:
    bullet = _normalize_spaces(text)
    if bullet and bullet[-1] not in ".!?":
        bullet += "."
    return bullet


def _russian_quality_ok(text: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return False
    ascii_letters = _ascii_re().findall(text)
    return len(ascii_letters) / max(1, len(letters)) <= 0.10


def _looks_russian(text: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return False
    cyr = re.findall(r"[А-Яа-яЁё]", text)
    return len(cyr) / max(1, len(letters)) >= 0.80


def _repair_block_russian_once(
    *,
    block_name: str,
    user_prompt: str,
    schema_validator: Any,
    max_tokens: int,
    temperature: float,
    request_id: str,
    session_id: str,
    client: Any,
) -> dict[str, Any]:
    return generate_json_block(
        block_name=block_name,
        system_prompt="Только русский. Верни только JSON. Никакого английского.",
        user_prompt=f"{user_prompt}\n\nПерепиши результат полностью по-русски, сохрани структуру JSON. Без англицизмов.",
        schema_validator=schema_validator,
        max_tokens=max_tokens,
        temperature=temperature,
        request_id=f"{request_id}-repair-ru",
        session_id=session_id,
        client=client,
        llm_enabled=True,
    )


def _sentence_split(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+|[\n\r]+", text) if s.strip()]


def _clean_sentence(text: str) -> str:
    cleaned = f" {_normalize_spaces(text)} "
    for filler in sorted(_FILLER_WORDS, key=len, reverse=True):
        cleaned = re.sub(rf"(?i)(^|[\s,;:-]){re.escape(filler)}(?=$|[\s,;:.!?-])", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:-")
    return cleaned.strip()


def _tokenize_ru(text: str) -> list[str]:
    return [token for token in re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", text.lower()) if token not in _STOPWORDS]


def _best_sentence_from_text(text: str) -> str:
    sentences = [_clean_sentence(item) for item in _sentence_split(text)]
    meaningful = [item for item in sentences if 10 <= len(item.split()) <= 25]
    if meaningful:
        meaningful.sort(key=lambda item: (len(_tokenize_ru(item)), -abs(17 - len(item.split()))), reverse=True)
        return meaningful[0][:180]
    if sentences:
        sentences.sort(key=lambda item: len(_tokenize_ru(item)), reverse=True)
        return sentences[0][:180]
    return ""


def _segment_density_score(text: str, first_segments_tokens: list[list[str]], keyword_stems: set[str]) -> tuple[int, int]:
    tokens = _tokenize_ru(text)
    local_counts = Counter(token for token in tokens if token not in _STOPWORDS)
    repeated_bonus = sum(1 for token, count in local_counts.items() if count > 1)
    keyword_matches = sum(1 for token in tokens if token[:5] in keyword_stems)
    cross_matches = 0
    token_stems = {token[:5] for token in tokens}
    for other in first_segments_tokens:
        cross_matches += len(token_stems & {token[:5] for token in other})
    return keyword_matches + repeated_bonus, cross_matches


def extract_main_idea(segments: list[dict[str, Any]], transcript_text: str | None = None) -> str:
    normalized_segments = [
        _normalize_spaces(str(seg.get("text", "")))
        for seg in segments
        if isinstance(seg, dict) and isinstance(seg.get("text"), str) and seg.get("text", "").strip()
    ]
    candidates = normalized_segments[:3]
    if not candidates and transcript_text:
        candidates = [_normalize_spaces(transcript_text)]
    if not candidates:
        return "Главная мысль выступления не распознана."

    all_tokens = [_tokenize_ru(text) for text in candidates]
    keyword_stems = {token[:5] for token in _extract_keywords(transcript_text, segments, limit=8)}
    if not keyword_stems:
        keyword_stems = {token[:5] for tokens in all_tokens for token in tokens[:8]}

    ranked = sorted(
        candidates,
        key=lambda text: (*_segment_density_score(text, all_tokens, keyword_stems), len(_best_sentence_from_text(text).split())),
        reverse=True,
    )
    main_sentence = _best_sentence_from_text(ranked[0])
    if not main_sentence:
        return "Главная мысль выступления не распознана."
    return main_sentence[:180]


def _build_compact_excerpt(transcript_text: str | None, segments: list[dict[str, Any]], *, max_chars: int) -> str:
    normalized_segments = [
        _normalize_spaces(str(seg.get("text", "")))
        for seg in segments
        if isinstance(seg, dict) and isinstance(seg.get("text"), str) and seg.get("text", "").strip()
    ]
    if normalized_segments:
        excerpt_parts: list[str] = []
        for idx, item in enumerate(normalized_segments[:6]):
            excerpt_parts.append(item)
            if sum(len(part) + 1 for part in excerpt_parts) >= max_chars:
                break
            if idx >= 2 and sum(len(part) for part in excerpt_parts) >= int(max_chars * 0.8):
                break
        excerpt = "\n".join(excerpt_parts)
        return excerpt[:max_chars]
    base_text = _normalize_spaces(transcript_text or "")
    return base_text[:max_chars]


def _build_coaching_brief(transcript_text: str | None, segments: list[dict[str, Any]]) -> dict[str, Any]:
    excerpt_limit = min(800, max(420, int(settings.local_llm_max_input_chars)))
    excerpt = _build_first_middle_last_excerpt(transcript_text or _build_compact_excerpt(transcript_text, segments, max_chars=excerpt_limit), max_chars=excerpt_limit)
    main_idea = extract_main_idea(segments, transcript_text)
    key_terms = _extract_keywords(transcript_text or excerpt, segments, limit=8)
    if not key_terms:
        key_terms = _extract_keywords(excerpt, [{"text": excerpt}], limit=8)
    key_terms = key_terms[:8]
    _debug_llm_quality(
        "coaching llm quality brief",
        main_idea=main_idea,
        key_terms=key_terms,
        excerpt_chars=len(excerpt),
    )
    return {
        "excerpt": excerpt,
        "main_idea": main_idea,
        "key_terms": key_terms,
    }


def _content_overlap(text: str, reference: str) -> bool:
    text_tokens = {token[:5] for token in _tokenize_ru(text) if len(token) >= 4}
    ref_tokens = {token[:5] for token in _tokenize_ru(reference) if len(token) >= 4}
    if not text_tokens or not ref_tokens:
        return False
    return bool(text_tokens & ref_tokens)


def _build_context_data(source_text: str) -> dict[str, Any]:
    tokens = _tokenize_ru(source_text)
    keyword_counts = Counter(tokens)
    top_keywords = [word for word, _ in keyword_counts.most_common(10)]
    sentences = _sentence_split(source_text)
    claim = ""
    for sent in sentences[:5]:
        cleaned = _clean_sentence(sent)
        if 8 <= len(cleaned.split()) <= 22:
            claim = cleaned
            break
    if not claim and sentences:
        claim = _clean_sentence(sentences[0])
    return {
        "top_keywords": top_keywords,
        "claim": claim,
        "main_idea": claim or "Главная мысль выступления не распознана.",
    }


def _is_near_duplicate(candidate: str, existing: list[str]) -> bool:
    c_words = set(_normalize_question(candidate).split())
    for item in existing:
        i_words = set(_normalize_question(item).split())
        if not c_words or not i_words:
            continue
        jaccard = len(c_words & i_words) / max(1, len(c_words | i_words))
        if jaccard >= 0.74:
            return True
        if SequenceMatcher(None, _normalize_question(candidate), _normalize_question(item)).ratio() >= 0.86:
            return True
    return False


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower(), flags=re.UNICODE)).strip()


def _question_relevant(question: str, *, main_idea: str, key_terms: list[str]) -> bool:
    question_tokens = {token[:5] for token in _tokenize_ru(question) if len(token) >= 4}
    keyword_stems = {item[:5] for item in key_terms if item}
    if question_tokens & keyword_stems:
        return True
    return _content_overlap(question, main_idea)


def _build_questions_user_prompt(*, main_idea: str, summary_bullets: list[str], key_terms: list[str], source_text: str) -> str:
    summary_block = "\n".join(f"- {item}" for item in summary_bullets[:5]) or "- Ключевые мысли не выделены."
    return (
        "Сформулируй 4 вопроса аудитории по ГЛАВНОЙ мысли выступления.\n"
        "Используй опорные данные:\n"
        f"Главная мысль: {main_idea}\n"
        "Ключевые моменты:\n"
        f"{summary_block}\n"
        f"Ключевые слова: {', '.join(key_terms) or 'нет'}\n"
        "Фрагмент выступления:\n<<<"
        f"{source_text}"
        ">>>\n\n"
        "Требования:\n"
        "- Только по-русски\n"
        "- Вопросы должны быть естественными, как от живого слушателя\n"
        "- Каждый вопрос ≤ 25 слов\n"
        "- Без канцелярита и без английских слов\n"
        "- Опирайся на смысл текста, а не только на ключевые слова\n"
        "- Вопросы должны проверять: смысл, конкретику, применимость, ограничения\n\n"
        "Верни строго JSON:\n"
        '{ "items": ["...?", "...?", "...?", "...?"] }'
    )


def _build_questions_retry_prompt(*, main_idea: str, summary_bullets: list[str], key_terms: list[str], source_text: str) -> str:
    summary_block = "\n".join(f"- {item}" for item in summary_bullets[:5]) or "- Ключевые мысли не выделены."
    return (
        "Переформулируй 4 вопроса аудитории.\n"
        "Условия:\n"
        f"- Главная мысль: {main_idea}\n"
        f"- Ключевые слова: {', '.join(key_terms) or 'нет'}\n"
        "- Только по-русски\n"
        "- Каждый вопрос должен быть связан с текстом выступления\n"
        "- Каждый вопрос ≤ 25 слов\n"
        "- Не повторяй один и тот же шаблон\n\n"
        "Ключевые моменты:\n"
        f"{summary_block}\n"
        "Фрагмент выступления:\n<<<"
        f"{source_text}"
        ">>>\n\n"
        "Верни строго JSON:\n"
        '{ "items": ["...?", "...?", "...?", "...?"] }'
    )


def _filter_questions(
    raw_items: list[str],
    source_text: str,
    keywords: list[str],
    *,
    require_keyword_match: bool = False,
    main_idea: str = "",
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    kept: list[str] = []
    reasons: list[str] = []
    rejected: list[dict[str, str]] = []
    numbers = set(re.findall(r"\b\d{1,4}\b", source_text))
    keyword_stems = {item[:5] for item in keywords if item}

    for raw in raw_items:
        question = _normalize_spaces(str(raw))
        if not question:
            reasons.append("empty")
            rejected.append({"item": str(raw), "reason": "empty"})
            continue
        if not question.endswith("?"):
            question = question.rstrip(".!") + "?"

        if len(question) < 10:
            reasons.append("too_short")
            rejected.append({"item": question, "reason": "too_short"})
            continue
        if len(question) > 180:
            reasons.append("too_long")
            rejected.append({"item": question, "reason": "too_long"})
            continue
        if not _russian_quality_ok(question) or not _looks_russian(question):
            reasons.append("non_russian")
            rejected.append({"item": question, "reason": "non_russian"})
            continue

        low = question.lower()
        if any(p in low for p in _NOISE_PATTERNS):
            reasons.append("noise_pattern")
            rejected.append({"item": question, "reason": "noise_pattern"})
            continue

        if any(number not in numbers for number in re.findall(r"\b\d{1,4}\b", question)):
            reasons.append("hallucinated_number")
            rejected.append({"item": question, "reason": "hallucinated_number"})
            continue

        q_tokens = [token for token in _tokenize_ru(low) if len(token) >= 4]
        if require_keyword_match and q_tokens:
            relevant = _question_relevant(question, main_idea=main_idea, key_terms=keywords)
            if not relevant and _content_overlap(question, source_text):
                relevant = True
            if keyword_stems and not relevant:
                reasons.append("off_topic")
                rejected.append({"item": question, "reason": "off_topic"})
                continue

        if _is_near_duplicate(question, kept):
            reasons.append("duplicate")
            rejected.append({"item": question, "reason": "duplicate"})
            continue

        kept.append(question)
        if len(kept) >= 5:
            break

    return kept, reasons, rejected


def _contextual_fallback_questions(*, desired_count: int = 4, audience: str = "general") -> list[str]:
    desired = min(5, max(3, desired_count))
    templates = {
        "students": [
            "Можете сформулировать ключевое определение своими словами и привести короткий пример, чтобы проверить понимание?",
            "В чём отличие вашего подхода от альтернативы, и по каким признакам студент может это увидеть на практике?",
            "Какие ограничения у метода вы бы выделили, и как их учитывать при решении задач?",
            "Какой следующий шаг вы рекомендуете после этой идеи: что попробовать сделать в учебном проекте?",
            "Какая одна ошибка в понимании темы встречается чаще всего, и как её избежать?",
        ],
        "clients": [
            "Какая конкретная выгода для нас в ближайшие 1–3 месяца, и по каким метрикам вы предлагаете измерять успех?",
            "Какие основные риски или ограничения вы видите, и что нужно сделать, чтобы снизить их заранее?",
            "Какие сроки и ресурсы потребуются, чтобы получить первый ощутимый результат, и что будет считаться 'готово'?",
            "Как это решение сравнить с альтернативами по цене/эффекту, и почему вы выбрали именно такой подход?",
            "Какой следующий шаг вы предлагаете после выступления: что нужно согласовать и кто ответственный?",
        ],
        "kids": [
            "Почему это важно — что изменится, если мы будем делать так, как вы предлагаете?",
            "Представь, что я ничего не знаю: можешь объяснить это на простом примере из жизни?",
            "А если сделать наоборот — что получится? Почему ваш вариант лучше?",
            "Какой самый простой шаг можно попробовать уже сегодня, чтобы это проверить?",
            "Какая часть кажется самой сложной, и как сделать её проще?",
        ],
        "colleagues": [
            "Как бы вы внедряли это по шагам, и какие метрики вы бы поставили, чтобы понять, что мы движемся правильно?",
            "Какие ограничения у подхода самые критичные, и какие компромиссы вы считаете допустимыми?",
            "С чем вы сравнивали решение и почему выбран именно этот вариант (по качеству/стоимости/рискам)?",
            "Какие зависимости и требования к данным/инфраструктуре нужны для первого пилота?",
            "Какой следующий шаг после выступления: что нужно решить на уровне команды и владельцев процессов?",
        ],
        "general": [
            "Можете привести один простой пример, который лучше всего показывает вашу главную мысль?",
            "Какие ограничения у этой идеи и в каких случаях она может не сработать?",
            "Что вы советуете сделать первым шагом после выступления, чтобы применить это на практике?",
            "Почему это важно именно сейчас, и что изменится, если следовать вашему совету?",
            "Какую одну мысль вы хотите, чтобы люди точно запомнили, и почему?",
        ],
    }
    return templates.get(audience, templates["general"])[:desired]


def _normalize_audience_question(question: str, *, audience: str) -> str:
    q = _normalize_spaces(question)
    if not q:
        return ""
    if not q.endswith("?"):
        q = q.rstrip(".!") + "?"
    if len(q) < 80:
        tails = {
            "students": " Приведите определение, пример и способ проверки результата?",
            "clients": " Уточните выгоду, риски и срок получения результата для клиента?",
            "kids": " Объясните простыми словами и сравните с понятной жизненной ситуацией?",
            "colleagues": " Уточните шаги внедрения и метрики, по которым команда проверит эффект?",
            "general": " Поясните на примере, почему это важно и как применить на практике?",
        }
        tail = tails.get(audience, tails["general"])
        q = q[:-1] + ";" + tail.lower() if q.endswith("?") else f"{q} {tail}"
    return _normalize_spaces(q)


def _question_has_audience_marker(question: str, audience: str) -> bool:
    low = question.lower()
    markers = {
        "students": ("пример", "определ", "провер"),
        "clients": ("выг", "риск", "срок", "результ"),
        "kids": ("представ", "почему", "как думаешь"),
        "colleagues": ("внедр", "метрик", "сравн"),
    }
    if audience not in markers:
        return True
    return any(marker in low for marker in markers[audience])


def _build_first_middle_last_excerpt(text: str, *, max_chars: int = 800) -> str:
    normalized = _normalize_spaces(text)
    if len(normalized) <= max_chars:
        return normalized
    chunk = max(120, max_chars // 3 - 6)
    first = normalized[:chunk].strip()
    middle_start = max(0, len(normalized) // 2 - chunk // 2)
    middle = normalized[middle_start : middle_start + chunk].strip()
    last = normalized[-chunk:].strip()
    return " … ".join([first, middle, last])[:max_chars]


_KEYWORD_STOPWORDS = _STOPWORDS | {"видео", "речь", "выступление", "сегодня", "вообще", "просто", "итак"}
_WEAK_KEYWORDS = {"который", "которая", "которые", "почему", "такой", "наверное", "может"}


def _fallback_keywords(source_text: str, *, limit: int = 6) -> list[str]:
    tokens = [
        token
        for token in _tokenize_ru(source_text)
        if len(token) >= 5
        and token not in _KEYWORD_STOPWORDS
        and token not in _WEAK_KEYWORDS
    ]
    if not tokens:
        return []
    counts = Counter(tokens)
    preferred_endings = ("ия", "ие", "ость", "изм", "ция", "ние", "ка", "ство", "тор", "ция")
    ranked = sorted(
        counts.items(),
        key=lambda item: ((1 if item[0].endswith(preferred_endings) else 0), item[1], len(item[0])),
        reverse=True,
    )
    return [word for word, _ in ranked[:limit]]


def _clean_keywords(raw_items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in raw_items:
        text = _normalize_spaces(str(item).lower().replace("#", ""))
        text = re.sub(r"[^\w\sа-яё-]", "", text, flags=re.IGNORECASE).strip()
        if not text or len(text) < 2 or len(text) > 28:
            continue
        if len(text.split()) > 2:
            continue
        if not re.search(r"[А-Яа-яЁё]", text):
            continue
        if text in _KEYWORD_STOPWORDS:
            continue
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= 8:
            break
    return cleaned


def _generate_summary_keywords(
    *,
    transcript_text: str | None,
    segments: list[dict[str, Any]],
    session_id: str,
    brief: dict[str, Any],
    scenario_ctx: dict[str, str] | None = None,
) -> list[str]:
    source_text = brief.get("excerpt") or _build_compact_excerpt(transcript_text, segments, max_chars=700)
    source_text = source_text[:800]
    client = get_local_llm_client()
    scenario_ctx = scenario_ctx or {}
    if not client or not is_llm_enabled():
        fallback = _fallback_keywords(source_text)
        _log_block_outcome(block="keywords", used="fallback", reason="llm_disabled", session_id=session_id, request_id=None)
        _log_coaching_fallback(block="keywords", reason="llm_disabled", details="llm disabled or unavailable", request_id=None, session_id=session_id)
        return fallback

    request_id = str(uuid4())
    system_prompt = "Ты — редактор тегов к видео. Только русский. Верни строго JSON."
    user_prompt = (
        f"Сценарий: preset={scenario_ctx.get('preset_label_ru', 'Конференция')}, цель={scenario_ctx.get('goal', 'inform')}, аудитория={scenario_ctx.get('audience', 'general')}.\n"
        "Фрагмент речи:\n"
        f"<<<{source_text}>>>\n\n"
        "Сгенерируй 5–10 ключевых слов как теги под видео:\n"
        "- только существительные или словосочетания (1–3 слова)\n"
        "- без '#'\n"
        "- без местоимений и стоп-слов (например: 'нужно', 'кстати', 'это', 'мы', 'и')\n"
        "- слова должны отражать тему и главные идеи\n\n"
        "Верни строго JSON:\n"
        '{ "keywords": ["...", "..."] }'
    )
    llm_result = generate_json_block(
        block_name="keywords",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_validator=lambda payload: isinstance(payload.get("keywords"), list),
        max_tokens=180,
        temperature=0.2,
        request_id=request_id,
        session_id=session_id,
        client=client,
        llm_enabled=True,
    )
    if llm_result.get("ok"):
        raw_keywords = (llm_result.get("payload") or {}).get("keywords") if isinstance(llm_result.get("payload"), dict) else []
        cleaned = _clean_keywords(raw_keywords if isinstance(raw_keywords, list) else [])
        cleaned = [item for item in cleaned if 1 <= len(item.split()) <= 3 and item not in _KEYWORD_STOPWORDS and "#" not in item][:10]
        if cleaned and not is_russian_text(" ".join(cleaned), min_cyrillic_chars=12):
            repair_result = _repair_block_russian_once(
                block_name="keywords",
                user_prompt=user_prompt,
                schema_validator=lambda payload: isinstance(payload.get("keywords"), list),
                max_tokens=180,
                temperature=0.2,
                request_id=str(llm_result.get("request_id") or request_id),
                session_id=session_id,
                client=client,
            )
            if repair_result.get("ok"):
                raw_keywords = (repair_result.get("payload") or {}).get("keywords") if isinstance(repair_result.get("payload"), dict) else []
                cleaned = _clean_keywords(raw_keywords if isinstance(raw_keywords, list) else [])
                cleaned = [item for item in cleaned if 1 <= len(item.split()) <= 3 and item not in _KEYWORD_STOPWORDS and "#" not in item][:10]
                llm_result = repair_result
            else:
                reason = "not_russian"
                _log_block_outcome(block="keywords", used="fallback", reason=reason, session_id=session_id, request_id=repair_result.get("request_id"), latency_ms=repair_result.get("llm_latency_ms"))
                _log_coaching_fallback(block="keywords", reason=reason, details=f"snippet={repair_result.get('content_snippet', '')}", request_id=repair_result.get("request_id"), session_id=session_id)
                return _fallback_keywords(source_text, limit=7)
        if 5 <= len(cleaned) <= 10:
            _log_block_outcome(block="keywords", used="llm", reason="llm", session_id=session_id, request_id=llm_result.get("request_id"), latency_ms=llm_result.get("llm_latency_ms"))
            return cleaned
        reason = "schema_invalid"
    else:
        reason = str(llm_result.get("reason") or "schema_invalid")
    _log_block_outcome(block="keywords", used="fallback", reason=reason, session_id=session_id, request_id=llm_result.get("request_id"), latency_ms=llm_result.get("llm_latency_ms"))
    _log_coaching_fallback(
        block="keywords",
        reason=reason,
        details=f"snippet={llm_result.get('content_snippet', '')}",
        request_id=llm_result.get("request_id"),
        session_id=session_id,
    )
    fallback = _fallback_keywords(source_text, limit=7)
    if len(fallback) < 4:
        _log_block_outcome(block="keywords", used="fallback", reason="low_quality", session_id=session_id, request_id=llm_result.get("request_id"))
    return fallback


def _generate_key_moments(
    *,
    transcript_text: str | None,
    segments: list[dict[str, Any]],
    session_id: str,
    brief: dict[str, Any],
    scenario_ctx: dict[str, str] | None = None,
) -> list[str]:
    source_text = brief.get("excerpt") or _build_compact_excerpt(transcript_text, segments, max_chars=700)
    source_text = source_text[:800]
    fallback = _fallback_summary_bullets_from_transcript(source_text, segments)
    scenario_ctx = scenario_ctx or {}
    client = get_local_llm_client()
    if not is_llm_enabled():
        logger.warning("coaching key moments llm disabled; fallback active", extra={"source_chars": len(source_text)})
    if not client or not is_llm_enabled():
        _debug_llm("coaching key moments final", mode="fallback", bullets=fallback[:5])
        _log_block_outcome(block="summary", used="fallback", reason="llm_disabled", session_id=session_id, request_id=None)
        _log_coaching_fallback(block="summary", reason="llm_disabled", details="llm disabled or client missing", request_id=None, session_id=session_id)
        return fallback[:5]

    system_prompt = "Ты — редактор резюме выступления. Только русский. Верни строго JSON."
    user_prompt = (
        f"Сценарий: preset={scenario_ctx.get('preset_label_ru', 'Конференция')}, цель={scenario_ctx.get('goal', 'inform')}, аудитория={scenario_ctx.get('audience', 'general')}.\n"
        "Фрагмент речи:\n"
        f"<<<{source_text}>>>\n\n"
        "Сделай 'Ключевые моменты' (4–7 пунктов):\n"
        "- каждый пункт = законченная мысль\n"
        "- 10–18 слов\n"
        "- без общих слов и без повторов\n"
        "- отражай несколько главных идей (не заголовки)\n\n"
        "Верни строго JSON:\n"
        '{ "bullets": ["...", "..."] }'
    )
    _debug_llm("coaching key moments llm start", mode="llm", source_chars=len(source_text))
    request_id = str(uuid4())
    llm_result = generate_json_block(
        block_name="summary",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_validator=lambda payload: isinstance(payload.get("bullets"), list),
        max_tokens=min(settings.local_llm_max_tokens_keymoments, 260),
        temperature=0.2,
        request_id=request_id,
        session_id=session_id,
        client=client,
        llm_enabled=True,
    )
    if llm_result.get("ok"):
        raw_bullets = (llm_result.get("payload") or {}).get("bullets") if isinstance(llm_result.get("payload"), dict) else []
        cleaned: list[str] = []
        for item in raw_bullets if isinstance(raw_bullets, list) else []:
            bullet = _normalize_bullet(str(item))[:180]
            if not 40 <= len(bullet) <= 180:
                continue
            if not is_russian_text(bullet, min_cyrillic_chars=16):
                continue
            if _is_near_duplicate(bullet, cleaned):
                continue
            cleaned.append(bullet)
        if 4 <= len(cleaned) <= 7:
            _log_block_outcome(block="summary", used="llm", reason="llm", session_id=session_id, request_id=llm_result.get("request_id"), latency_ms=llm_result.get("llm_latency_ms"))
            return cleaned[:7]
        repair_result = _repair_block_russian_once(
            block_name="summary",
            user_prompt=f"{user_prompt}\n\nСделай 4–7 пунктов, каждый 40–180 символов, без дублей.",
            schema_validator=lambda payload: isinstance(payload.get("bullets"), list),
            max_tokens=min(settings.local_llm_max_tokens_keymoments, 260),
            temperature=0.2,
            request_id=str(llm_result.get("request_id") or request_id),
            session_id=session_id,
            client=client,
        )
        if repair_result.get("ok"):
            raw_bullets = (repair_result.get("payload") or {}).get("bullets") if isinstance(repair_result.get("payload"), dict) else []
            cleaned = []
            for item in raw_bullets if isinstance(raw_bullets, list) else []:
                bullet = _normalize_bullet(str(item))[:180]
                if not 40 <= len(bullet) <= 180:
                    continue
                if not is_russian_text(bullet, min_cyrillic_chars=16):
                    continue
                if _is_near_duplicate(bullet, cleaned):
                    continue
                cleaned.append(bullet)
            if 4 <= len(cleaned) <= 7:
                _log_block_outcome(block="summary", used="llm", reason="llm", session_id=session_id, request_id=repair_result.get("request_id"), latency_ms=repair_result.get("llm_latency_ms"))
                return cleaned[:7]
            reason = "not_russian" if cleaned and not is_russian_text(" ".join(cleaned), min_cyrillic_chars=30) else "schema_invalid"
            llm_result = repair_result
        else:
            llm_result = repair_result
            reason = "not_russian" if str(repair_result.get("reason")) == "schema_invalid" else str(repair_result.get("reason") or "schema_invalid")
    else:
        reason = str(llm_result.get("reason") or "schema_invalid")
    _log_block_outcome(block="summary", used="fallback", reason=reason, session_id=session_id, request_id=llm_result.get("request_id"), latency_ms=llm_result.get("llm_latency_ms"))
    _log_coaching_fallback(block="summary", reason=reason, details=f"snippet={llm_result.get('content_snippet','')}", request_id=llm_result.get("request_id"), session_id=session_id)
    return fallback[:5]


def _generate_audience_questions(
    *,
    transcript_text: str | None,
    segments: list[dict[str, Any]],
    summary_bullets: list[str],
    session_id: str,
    brief: dict[str, Any] | None = None,
    scenario_ctx: dict[str, str] | None = None,
) -> list[str]:
    brief = brief or _build_coaching_brief(transcript_text, segments)
    source_text = brief.get("excerpt") or _build_compact_excerpt(transcript_text, segments, max_chars=700)
    source_text = source_text[:700]
    main_idea = brief.get("main_idea") or extract_main_idea(segments, transcript_text)
    key_terms = list(dict.fromkeys((brief.get("key_terms") or []) + _extract_keywords(transcript_text, segments, limit=8)))[:8]
    desired_count = 4 if len(source_text.split()) >= 45 else 3

    llm_items: list[str] = []
    llm_error = ""
    request_id: str | None = None
    user_prompt = ""
    client = get_local_llm_client()
    scenario_ctx = scenario_ctx or {}
    if not is_llm_enabled():
        logger.warning("coaching questions llm disabled; fallback active", extra={"source_chars": len(source_text)})
    if client and is_llm_enabled():
        request_id = str(uuid4())
        goal_ru = GOAL_RU_LABELS.get(str(scenario_ctx.get("goal") or "inform"), "информировать")
        audience_ru = AUDIENCE_RU_LABELS.get(str(scenario_ctx.get("audience") or "general"), "широкая аудитория")
        tone_ru = TONE_RU_LABELS.get(str(scenario_ctx.get("tone") or "friendly"), "Дружелюбный")
        system_prompt = "Ты — представитель аудитории, который задаёт вопросы после выступления. Только русский. Верни строго JSON. Вопросы должны звучать естественно, как реальные вопросы людей этой аудитории."
        user_prompt = (
            "Сценарий:\n"
            f"аудитория={audience_ru}\n"
            f"цель={goal_ru}\n"
            f"формат={scenario_ctx.get('preset_label_ru', 'Доклад на конференции')}\n"
            f"тон={tone_ru}\n\n"
            "Фрагмент речи:\n"
            f"<<<{source_text}>>>\n\n"
            "Сгенерируй 3–5 вопросов ИМЕННО ОТ ЭТОЙ АУДИТОРИИ.\n"
            "Требования:\n"
            "- каждый вопрос 15–30 слов\n"
            "- минимум 1 вопрос: про пример/доказательство\n"
            "- минимум 1 вопрос: про риск/ограничение\n"
            "- минимум 1 вопрос: про применение/следующий шаг\n"
            "- каждый вопрос заканчивается '?'\n"
            "- стиль должен явно соответствовать аудитории:\n"
            "  студенты: определения, пример, как проверить, в чём отличие\n"
            "  клиенты: выгода, сроки, риски, критерии успеха, что получим\n"
            "  дети: простые слова, сравнение, 'почему', 'а если', 'как ты думаешь'\n"
            "  коллеги: внедрение, метрики, сравнение подходов, ограничения\n"
            "  широкая аудитория: понятные вопросы, без терминов, зачем важно\n\n"
            "Верни строго JSON:\n"
            '{ "items": [ {"q":"..."} ] }'
        )
        audience = str(scenario_ctx.get("audience") or "general")
        llm_result = generate_json_block(
            block_name="questions",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_validator=lambda payload: isinstance(payload.get("items"), list),
            max_tokens=min(settings.local_llm_max_tokens_questions, 240),
            temperature=0.3,
            request_id=request_id,
            session_id=session_id,
            client=client,
            llm_enabled=True,
        )
        if llm_result.get("ok"):
            raw_items = (llm_result.get("payload") or {}).get("items") if isinstance(llm_result.get("payload"), dict) else []
            for item in raw_items if isinstance(raw_items, list) else []:
                question = item.get("q") if isinstance(item, dict) else item
                q = _normalize_audience_question(str(question), audience=audience)
                if not q:
                    continue
                if 70 <= len(q) <= 240 and not _is_near_duplicate(q, llm_items):
                    llm_items.append(q)
            if not llm_items:
                llm_error = "schema_invalid"
            request_id = str(llm_result.get("request_id") or request_id)
        else:
            llm_error = str(llm_result.get("reason") or "schema_invalid")
            request_id = str(llm_result.get("request_id") or request_id)
        if len(llm_items) < 3:
            repair_prompt = (
                f"{user_prompt}\n\n"
                "Верни только JSON. Условия: 3-5 вопросов, каждый 70-240 символов, с учетом аудитории и с '?'. "
                "Обязательно: минимум один вопрос про пример/доказательство, один про риск/ограничение, один про следующий шаг."
            )
            repair_result = generate_json_block(
                block_name="questions",
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                schema_validator=lambda payload: isinstance(payload.get("items"), list),
                max_tokens=min(settings.local_llm_max_tokens_questions, 240),
                temperature=0.3,
                request_id=f"{request_id}-repair-schema",
                session_id=session_id,
                client=client,
                llm_enabled=True,
            )
            if repair_result.get("ok"):
                llm_items = []
                raw_items = (repair_result.get("payload") or {}).get("items") if isinstance(repair_result.get("payload"), dict) else []
                for item in raw_items if isinstance(raw_items, list) else []:
                    question = item.get("q") if isinstance(item, dict) else item
                    q = _normalize_audience_question(str(question), audience=audience)
                    if 70 <= len(q) <= 240 and not _is_near_duplicate(q, llm_items):
                        llm_items.append(q)
                if len(llm_items) >= 3:
                    llm_error = ""
                    request_id = str(repair_result.get("request_id") or request_id)
    else:
        llm_error = "llm_disabled"

    filtered_llm, reasons, rejected_llm = _filter_questions(llm_items, source_text, key_terms, require_keyword_match=False, main_idea=main_idea)
    if (
        len(filtered_llm) < 3
        and client
        and is_llm_enabled()
        and user_prompt
        and any(item.get("reason") == "non_russian" for item in rejected_llm)
    ):
        ru_repair = _repair_block_russian_once(
            block_name="questions",
            user_prompt=user_prompt,
            schema_validator=lambda payload: isinstance(payload.get("items"), list),
            max_tokens=min(settings.local_llm_max_tokens_questions, 240),
            temperature=0.3,
            request_id=str(request_id or "questions"),
            session_id=session_id,
            client=client,
        )
        if ru_repair.get("ok"):
            ru_items: list[str] = []
            raw_items = (ru_repair.get("payload") or {}).get("items") if isinstance(ru_repair.get("payload"), dict) else []
            for item in raw_items if isinstance(raw_items, list) else []:
                question = item.get("q") if isinstance(item, dict) else item
                q = _normalize_audience_question(str(question), audience=str(scenario_ctx.get("audience") or "general"))
                if not q:
                    continue
                if 70 <= len(q) <= 240 and not _is_near_duplicate(q, ru_items):
                    ru_items.append(q)
            filtered_llm, reasons, rejected_llm = _filter_questions(ru_items, source_text, key_terms, require_keyword_match=False, main_idea=main_idea)
            request_id = str(ru_repair.get("request_id") or request_id)
            if len(filtered_llm) >= 3:
                llm_items = ru_items
                llm_error = ""
        else:
            llm_error = "not_russian"
    logger.warning(
        "coaching questions llm pipeline summary",
        extra={
            "llm_enabled": bool(client and is_llm_enabled()),
            "llm_raw_items": len(llm_items),
            "llm_filtered_items": len(filtered_llm),
            "llm_error": llm_error or None,
            "source_chars": len(source_text),
            "filter_reasons": dict(Counter(reasons)),
            "request_id": request_id if client and is_llm_enabled() else None,
        },
    )
    _debug_llm("coaching questions filtered", request_id=request_id, filtered_count=len(filtered_llm), rejected=rejected_llm[:8])
    if settings.debug_llm_quality:
        removed_for_relevance = sum(1 for item in rejected_llm if item.get("reason") == "off_topic")
        _debug_llm_quality(
            "coaching questions quality gate",
            main_idea=main_idea,
            key_terms=key_terms,
            relevance_removed=removed_for_relevance,
            rejected_total=len(rejected_llm),
        )

    if 3 <= len(filtered_llm) <= 5:
        logger.warning("coaching questions using llm output", extra={"items": len(filtered_llm), "desired_count": desired_count})
        final_llm = filtered_llm[:desired_count]
        _debug_llm("coaching questions final", request_id=request_id, mode="llm", items=final_llm)
        _log_block_outcome(
            block="questions",
            used="llm",
            reason="llm",
            session_id=session_id,
            request_id=request_id,
            latency_ms=(client.last_call_meta or {}).get("elapsed_ms"),
        )
        return final_llm

    lenient_llm: list[str] = []
    for raw in llm_items:
        question = _normalize_spaces(str(raw))
        if not question:
            continue
        if not question.endswith("?"):
            question = question.rstrip(".!") + "?"
        if len(question) < 10 or len(question) > 180:
            continue
        if not _russian_quality_ok(question) or not _looks_russian(question):
            continue
        if _is_near_duplicate(question, lenient_llm):
            continue
        lenient_llm.append(question)
        if len(lenient_llm) >= 5:
            break
    if len(lenient_llm) >= 3:
        logger.warning(
            "coaching questions using lenient llm output",
            extra={"request_id": request_id, "raw_items": len(llm_items), "lenient_items": len(lenient_llm)},
        )
        _log_block_outcome(
            block="questions",
            used="llm",
            reason="llm",
            session_id=session_id,
            request_id=request_id,
            latency_ms=(client.last_call_meta or {}).get("elapsed_ms"),
        )
        return lenient_llm[:desired_count]

    fallback_reason = llm_error or "filtered_all_items"
    if not llm_error and rejected_llm and all(item.get("reason") == "non_russian" for item in rejected_llm):
        fallback_reason = "not_russian"
    if fallback_reason not in _COACHING_FALLBACK_REASONS:
        if llm_items and not filtered_llm:
            rejected_reasons = {item.get("reason") for item in rejected_llm}
            if rejected_reasons and rejected_reasons <= {"non_russian"}:
                fallback_reason = "filtered_all_items"
            elif rejected_reasons:
                fallback_reason = "filtered_all_items"
            else:
                fallback_reason = "low_quality"
        elif llm_items and len(filtered_llm) < 3:
            fallback_reason = "low_quality"
        else:
            fallback_reason = "schema_invalid"

    fallback_audience = str(scenario_ctx.get("audience") or "general")
    fallback = [_normalize_audience_question(item, audience=fallback_audience) for item in _contextual_fallback_questions(desired_count=desired_count, audience=fallback_audience)]
    logger.warning(
        "coaching questions fallback output",
        extra={"items": len(fallback), "desired_count": desired_count, "FALLBACK_REASON": fallback_reason},
    )
    _log_coaching_fallback(
        block="questions",
        reason=fallback_reason,
        details=f"raw={len(llm_items)} filtered={len(filtered_llm)} reasons={dict(Counter(reasons))}",
        request_id=request_id,
        session_id=session_id,
        response_data={"filtered_rejections": rejected_llm[:10]},
        content=json.dumps({"items": llm_items}, ensure_ascii=False),
    )
    _debug_llm("coaching questions final", request_id=request_id, mode="fallback", items=fallback)
    _log_block_outcome(
        block="questions",
        used="fallback",
        reason=fallback_reason,
        session_id=session_id,
        request_id=request_id,
        latency_ms=(client.last_call_meta or {}).get("elapsed_ms") if client else None,
    )
    return fallback


def _generate_coaching_bundle(*, transcript_text: str | None, segments: list[dict[str, Any]], session_id: str, brief: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    source_text = (brief.get("excerpt") or _build_compact_excerpt(transcript_text, segments, max_chars=700))[:700]
    main_idea = brief.get("main_idea") or extract_main_idea(segments, transcript_text)
    key_terms = list(dict.fromkeys((brief.get("key_terms") or []) + _extract_keywords(transcript_text, segments, limit=8)))[:8]

    fallback_summary = _segment_summary_bullets(segments)[:5]
    fallback_questions = _contextual_fallback_questions(desired_count=4 if len(source_text.split()) >= 45 else 3)
    fallback_keywords = _fallback_keywords(source_text, limit=8)

    client = get_local_llm_client()
    if not client or not is_llm_enabled():
        for block in ("summary", "questions", "keywords"):
            _log_block_outcome(block=block, used="fallback", reason="llm_disabled", session_id=session_id, request_id=None)
        return fallback_summary, fallback_questions, fallback_keywords

    return _generate_key_moments(transcript_text=transcript_text, segments=segments, session_id=session_id, brief=brief), _generate_audience_questions(
        transcript_text=transcript_text, segments=segments, summary_bullets=fallback_summary, session_id=session_id, brief=brief
    ), _generate_summary_keywords(transcript_text=transcript_text, segments=segments, session_id=session_id, brief=brief)


def _build_metrics_snapshot(*, results: dict[str, Any], norms: dict[str, Any]) -> dict[str, float | None]:
    delivery = results.get("delivery") if isinstance(results.get("delivery"), dict) else {}
    word_choice = results.get("word_choice") if isinstance(results.get("word_choice"), dict) else {}
    voice = results.get("voice") if isinstance(results.get("voice"), dict) else {}
    visual = results.get("visual") if isinstance(results.get("visual"), dict) else {}
    return {
        "wpm": _metric_value(delivery, "tempo", "wpm_avg", "value"),
        "pause_percent": _to_percent(_metric_value(delivery, "pauses", "pause_ratio", "value")),
        "fillers_per_min": _metric_value(word_choice, "fillers", "density", "value"),
        "redundancy_percent": _to_percent(_metric_value(word_choice, "conciseness", "redundancy_score", "value")),
        "pitch_cv": _metric_value(voice, "pitch", "cv", "value"),
        "eye_contact": _metric_value(visual, "eye_contact", "value"),
        "wpm_min": _metric_value(norms, "wpm", "min"),
        "wpm_max": _metric_value(norms, "wpm", "max"),
        "pause_min": _metric_value(norms, "pause_percent", "min"),
        "pause_max": _metric_value(norms, "pause_percent", "max"),
        "fillers_min": _metric_value(norms, "fillers_per_min", "min"),
        "fillers_max": _metric_value(norms, "fillers_per_min", "max"),
        "red_min": _metric_value(norms, "redundancy_percent", "min"),
        "red_max": _metric_value(norms, "redundancy_percent", "max"),
        "pitch_min": _metric_value(norms, "pitch_cv", "min"),
        "pitch_max": _metric_value(norms, "pitch_cv", "max"),
        "eye_min": _metric_value(norms, "eye_contact", "min"),
        "eye_max": _metric_value(norms, "eye_contact", "max"),
    }


def _generate_strength_v2_fallback(*, metrics: dict[str, float | None], scenario_ctx: dict[str, str]) -> list[dict[str, Any]]:
    checks = [
        ("wpm", _in_range(metrics["wpm"], metrics["wpm_min"], metrics["wpm_max"]), _dist_to_range(metrics["wpm"], metrics["wpm_min"], metrics["wpm_max"])),
        ("pause_percent", _in_range(metrics["pause_percent"], metrics["pause_min"], metrics["pause_max"]), _dist_to_range(metrics["pause_percent"], metrics["pause_min"], metrics["pause_max"])),
        ("fillers_per_min", _in_range(metrics["fillers_per_min"], metrics["fillers_min"], metrics["fillers_max"]), _dist_to_range(metrics["fillers_per_min"], metrics["fillers_min"], metrics["fillers_max"])),
        ("redundancy_percent", _in_range(metrics["redundancy_percent"], metrics["red_min"], metrics["red_max"]), _dist_to_range(metrics["redundancy_percent"], metrics["red_min"], metrics["red_max"])),
        ("pitch_cv", _in_range(metrics["pitch_cv"], metrics["pitch_min"], metrics["pitch_max"]), _dist_to_range(metrics["pitch_cv"], metrics["pitch_min"], metrics["pitch_max"])),
        ("eye_contact", _in_range(metrics["eye_contact"], metrics["eye_min"], metrics["eye_max"]), _dist_to_range(metrics["eye_contact"], metrics["eye_min"], metrics["eye_max"])),
    ]
    sorted_metrics = [item[0] for item in sorted(checks, key=lambda item: (0 if item[1] else 1, item[2]))]
    items: list[dict[str, Any]] = []
    goal_ru = scenario_ctx["goal_ru"]
    audience_ru = scenario_ctx["audience_ru"]
    tone_ru = scenario_ctx["tone_ru"]
    preset_label_ru = scenario_ctx["preset_label_ru"]
    for key in sorted_metrics:
        if key == "wpm":
            items.append({"title": "Уместный темп", "text": f"Темп речи подходит для цели «{goal_ru}» и помогает аудитории ({audience_ru}) удерживать основную мысль.", "evidence": [f"WPM {metrics['wpm'] or '-'} при норме {metrics['wpm_min'] or '-'}–{metrics['wpm_max'] or '-'}"], "metrics": ["wpm"], "timecode": None})
        elif key == "pause_percent":
            items.append({"title": "Хороший ритм пауз", "text": f"Паузы выглядят естественно для формата «{preset_label_ru}» и делают подачу более структурной.", "evidence": [f"Паузы {metrics['pause_percent'] or '-'}% при норме {metrics['pause_min'] or '-'}–{metrics['pause_max'] or '-'}%"], "metrics": ["pause_percent"], "timecode": None})
        elif key == "fillers_per_min":
            items.append({"title": "Чистая речь", "text": f"Мало слов-паразитов — для сценария «{preset_label_ru}» это повышает доверие и ясность для {audience_ru}.", "evidence": [f"Паразиты {metrics['fillers_per_min'] or '-'}/мин при норме {metrics['fillers_min'] or '-'}–{metrics['fillers_max'] or '-'}/мин"], "metrics": ["fillers_per_min"], "timecode": None})
        elif key == "redundancy_percent":
            items.append({"title": "Лаконичная формулировка", "text": f"Низкая избыточность помогает быстрее донести цель «{goal_ru}» без лишних повторов и воды.", "evidence": [f"Избыточность {metrics['redundancy_percent'] or '-'}% при норме {metrics['red_min'] or '-'}–{metrics['red_max'] or '-'}%"], "metrics": ["redundancy_percent"], "timecode": None})
        elif key == "pitch_cv":
            items.append({"title": "Живая интонация", "text": f"Интонационная вариативность соответствует тону «{tone_ru}» и помогает удерживать внимание аудитории.", "evidence": [f"pitch_cv {metrics['pitch_cv'] or '-'} при норме {metrics['pitch_min'] or '-'}–{metrics['pitch_max'] or '-'}"], "metrics": ["pitch_cv"], "timecode": None})
        elif key == "eye_contact":
            items.append({"title": "Контакт с аудиторией", "text": f"Зрительный контакт поддерживает вовлечённость: это особенно важно для цели «{goal_ru}» и аудитории ({audience_ru}).", "evidence": [f"Контакт {metrics['eye_contact'] or '-'}/5 при норме {metrics['eye_min'] or '-'}–{metrics['eye_max'] or '-'}/5"], "metrics": ["eye_contact"], "timecode": None})
        if len(items) >= 5:
            break
    return items[:5] if items else [{"title": "Рабочая основа", "text": f"Для сценария «{preset_label_ru}» уже есть базовая структура, на которую можно опереться для цели «{goal_ru}».", "evidence": ["WPM 0 при норме 0–0"], "metrics": ["wpm"], "timecode": None}]


def _generate_strength_v2(*, session_id: str, scenario_ctx: dict[str, str], metrics: dict[str, float | None]) -> dict[str, Any]:
    fallback_items = _generate_strength_v2_fallback(metrics=metrics, scenario_ctx=scenario_ctx)[:5]
    client = get_local_llm_client()
    request_id = str(uuid4())
    if not client or not is_llm_enabled():
        return {"items": fallback_items[:4], "source": "fallback", "fallback_reason": "llm_disabled", "request_id": None, "llm_latency_ms": None}
    system_prompt = "Ты — коуч по публичным выступлениям. Только русский. Верни строго JSON. Не выдумывай числа: используй только переданные метрики и нормы. Пиши 'Сила' так, чтобы было явно, почему это хорошо именно для данного сценария (цель+аудитория+тон)."
    user_prompt = (
        f"Сценарий:\nформат={scenario_ctx['preset_label_ru']}\nцель={scenario_ctx['goal_ru']}\nаудитория={scenario_ctx['audience_ru']}\nтон={scenario_ctx['tone_ru']}\n\n"
        f"Нормы сценария:\nWPM {metrics['wpm_min']}-{metrics['wpm_max']}\nПаузы {metrics['pause_min']}-{metrics['pause_max']}%\nПаразиты {metrics['fillers_min']}-{metrics['fillers_max']}/мин\nИзбыточность {metrics['red_min']}-{metrics['red_max']}%\nИнтонация pitch_cv {metrics['pitch_min']}-{metrics['pitch_max']}\nЗрительный контакт {metrics['eye_min']}-{metrics['eye_max']}/5\n\n"
        f"Фактические метрики:\nWPM={metrics['wpm']}\nПаузы={metrics['pause_percent']}%\nПаразиты={metrics['fillers_per_min']}/мин\nИзбыточность={metrics['redundancy_percent']}%\npitch_cv={metrics['pitch_cv']}\nЗрительный контакт={metrics['eye_contact']}/5\n\n"
        "Сделай 3–5 пунктов 'Сила' (плюсы выступления) — почему это хорошо ИМЕННО для данного сценария.\n"
        'Верни строго JSON:\n{ "items": [ {"title":"...","text":"...","evidence":["..."],"metrics":["wpm"],"timecode":null} ] }'
    )
    result = generate_json_block(block_name="strength_v2", system_prompt=system_prompt, user_prompt=user_prompt, schema_validator=lambda payload: isinstance(payload.get("items"), list), max_tokens=260, temperature=0.25, request_id=request_id, session_id=session_id, client=client, llm_enabled=True)
    if result.get("ok"):
        items = (result.get("payload") or {}).get("items") if isinstance(result.get("payload"), dict) else []
        cleaned = [
            item
            for item in items
            if isinstance(item, dict)
            and 5 <= len(str(item.get("title") or "")) <= 50
            and 90 <= len(str(item.get("text") or "")) <= 200
            and isinstance(item.get("evidence"), list)
            and 1 <= len(item.get("evidence")) <= 2
            and any(ch.isdigit() for ch in str(item.get("evidence")[0]))
            and is_russian_text(f"{item.get('title', '')} {item.get('text', '')} {' '.join(item.get('evidence', []))}", min_cyrillic_chars=30)
        ]
        if len(cleaned) < 3:
            repair = _repair_block_russian_once(
                block_name="strength_v2",
                user_prompt=user_prompt,
                schema_validator=lambda payload: isinstance(payload.get("items"), list),
                max_tokens=260,
                temperature=0.25,
                request_id=str(result.get("request_id") or request_id),
                session_id=session_id,
                client=client,
            )
            if repair.get("ok"):
                items = (repair.get("payload") or {}).get("items") if isinstance(repair.get("payload"), dict) else []
                cleaned = [item for item in items if isinstance(item, dict) and is_russian_text(f"{item.get('title', '')} {item.get('text', '')}", min_cyrillic_chars=30)]
                result = repair
        if 3 <= len(cleaned) <= 5:
            return {"items": cleaned[:5], "source": "llm", "fallback_reason": None, "request_id": result.get("request_id"), "llm_latency_ms": result.get("llm_latency_ms")}
    return {"items": fallback_items[:4], "source": "fallback", "fallback_reason": "not_russian" if result.get("ok") else str(result.get("reason") or "schema_invalid"), "request_id": result.get("request_id"), "llm_latency_ms": result.get("llm_latency_ms")}


def _generate_growth_v2(*, session_id: str, scenario_ctx: dict[str, str], metrics: dict[str, float | None]) -> dict[str, Any]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    deviations = [
        (_dist_to_range(metrics["wpm"], metrics["wpm_min"], metrics["wpm_max"]), "wpm"),
        (_dist_to_range(metrics["pause_percent"], metrics["pause_min"], metrics["pause_max"]), "pause_percent"),
        (_dist_to_range(metrics["fillers_per_min"], metrics["fillers_min"], metrics["fillers_max"]), "fillers_per_min"),
        (_dist_to_range(metrics["redundancy_percent"], metrics["red_min"], metrics["red_max"]), "redundancy_percent"),
        (_dist_to_range(metrics["pitch_cv"], metrics["pitch_min"], metrics["pitch_max"]), "pitch_cv"),
        (_dist_to_range(metrics["eye_contact"], metrics["eye_min"], metrics["eye_max"]), "eye_contact"),
    ]
    for dist, key in sorted(deviations, key=lambda item: item[0], reverse=True):
        if dist <= 0:
            continue
        if key == "wpm":
            high = (metrics["wpm"] or 0) > (metrics["wpm_max"] or 0)
            candidates.append((dist, {"title": "Слишком быстрый темп" if high else "Темп ниже нормы", "text": "Темп выше нормы — часть смысловых блоков может восприниматься на слух хуже." if high else f"Темп ниже нормы для формата «{scenario_ctx['preset_label_ru']}», из-за этого ключевые тезисы звучат растянуто.", "why_for_scenario": f"Для {scenario_ctx['audience_ru']} важна разборчивость, особенно при цели «{scenario_ctx['goal_ru']}»." if high else f"Для цели «{scenario_ctx['goal_ru']}» важно удерживать внимание {scenario_ctx['audience_ru']}, а медленный темп снижает динамику.", "action": "Сделайте паузу после каждого тезиса и замедлите окончания фраз, сохраняя уверенную дикцию." if high else "Ускорьте ключевые фразы: уберите вводные слова и сократите предложения в середине выступления.", "evidence": [f"WPM {metrics['wpm']} при норме {metrics['wpm_min']}–{metrics['wpm_max']}"], "metrics": ["wpm"], "timecode": None}))
        if key == "pause_percent":
            high = (metrics["pause_percent"] or 0) > (metrics["pause_max"] or 0)
            candidates.append((dist, {"title": "Слишком много пауз" if high else "Не хватает пауз", "text": "Паузы встречаются чаще нормы, из-за этого теряется связность повествования." if high else "Паузы реже нормы, из-за этого речь звучит плотной и сложнее воспринимается.", "why_for_scenario": f"В формате «{scenario_ctx['preset_label_ru']}» это мешает довести цель «{scenario_ctx['goal_ru']}» до {scenario_ctx['audience_ru']}." if high else f"Для {scenario_ctx['audience_ru']} паузы помогают структурировать материал и поддерживают цель «{scenario_ctx['goal_ru']}».", "action": "Сократите паузы внутри предложения и перенесите их на границы смысловых блоков." if high else "Добавьте 2–3 короткие смысловые паузы перед выводом и после ключевых определений.", "evidence": [f"Паузы {metrics['pause_percent']}% при норме {metrics['pause_min']}–{metrics['pause_max']}%"], "metrics": ["pause_percent"], "timecode": None}))
        if key == "fillers_per_min":
            candidates.append((dist, {"title": "Много слов-паразитов", "text": "Слова-паразиты встречаются чаще нормы и снижают ощущение уверенности.", "why_for_scenario": f"Для цели «{scenario_ctx['goal_ru']}» и аудитории ({scenario_ctx['audience_ru']}) важно звучать точно и надёжно.", "action": "Замените паразиты на короткие паузы 0.3–0.5с и заранее заготовьте формулировки ключевых тезисов.", "evidence": [f"Паразиты {metrics['fillers_per_min']}/мин при норме {metrics['fillers_min']}–{metrics['fillers_max']}/мин"], "metrics": ["fillers_per_min"], "timecode": None}))
        if key == "redundancy_percent":
            candidates.append((dist, {"title": "Избыточность формулировок", "text": "Много повторов и лишних слов — смысл теряется на фоне объёма.", "why_for_scenario": f"В сценарии «{scenario_ctx['preset_label_ru']}» это мешает быстрее донести цель «{scenario_ctx['goal_ru']}» до {scenario_ctx['audience_ru']}.", "action": "Сократите каждую мысль до 1–2 предложений и уберите повторы в соседних абзацах.", "evidence": [f"Избыточность {metrics['redundancy_percent']}% при норме {metrics['red_min']}–{metrics['red_max']}%"], "metrics": ["redundancy_percent"], "timecode": None}))
        if key == "pitch_cv":
            candidates.append((dist, {"title": "Монотонная интонация", "text": "Интонация менее вариативна, чем ожидается — внимание удерживать сложнее.", "why_for_scenario": f"Для тона «{scenario_ctx['tone_ru']}» и цели «{scenario_ctx['goal_ru']}» полезны контрасты на ключевых тезисах.", "action": "Подчеркните выводы: повышайте тон на тезисе и снижайте на завершении фразы.", "evidence": [f"pitch_cv {metrics['pitch_cv']} при норме {metrics['pitch_min']}–{metrics['pitch_max']}"], "metrics": ["pitch_cv"], "timecode": None}))
        if key == "eye_contact":
            candidates.append((dist, {"title": "Слабый зрительный контакт", "text": "Зрительный контакт ниже ожидаемого — доверие и вовлечённость уменьшаются.", "why_for_scenario": f"Для {scenario_ctx['audience_ru']} это важно: контакт усиливает эффект цели «{scenario_ctx['goal_ru']}».", "action": "Держите взгляд в камеру на началах и окончаниях ключевых тезисов (2–3 секунды).", "evidence": [f"Контакт {metrics['eye_contact']}/5 при норме {metrics['eye_min']}–{metrics['eye_max']}/5"], "metrics": ["eye_contact"], "timecode": None}))
    fallback_items = [item for _, item in candidates][:5] or [{"title": "Зона роста", "text": "Сфокусируйтесь на доработке структуры выступления, чтобы усилить подачу.", "why_for_scenario": f"Это поможет лучше достичь цели «{scenario_ctx['goal_ru']}» для аудитории {scenario_ctx['audience_ru']}.", "action": "Запишите ещё один дубль и сравните метрики по темпу, паузам и ясности формулировок.", "evidence": ["WPM 0 при норме 0–0"], "metrics": ["wpm"], "timecode": None}]
    client = get_local_llm_client()
    request_id = str(uuid4())
    if not client or not is_llm_enabled():
        return {"items": fallback_items[:5], "source": "fallback", "fallback_reason": "llm_disabled", "request_id": None, "llm_latency_ms": None}
    system_prompt = "Ты — коуч. Только русский. Верни строго JSON. Не выдумывай факты и числа. 'Область роста' должна помогать лучше достигать цель в данном сценарии (формат+аудитория+тон)."
    user_prompt = (
        f"Сценарий:\nформат={scenario_ctx['preset_label_ru']}\nцель={scenario_ctx['goal_ru']}\nаудитория={scenario_ctx['audience_ru']}\nтон={scenario_ctx['tone_ru']}\n\n"
        f"Нормы сценария:\nWPM {metrics['wpm_min']}-{metrics['wpm_max']}\nПаузы {metrics['pause_min']}-{metrics['pause_max']}%\nПаразиты {metrics['fillers_min']}-{metrics['fillers_max']}/мин\nИзбыточность {metrics['red_min']}-{metrics['red_max']}%\npitch_cv {metrics['pitch_min']}-{metrics['pitch_max']}\nЗрительный контакт {metrics['eye_min']}-{metrics['eye_max']}/5\n\n"
        f"Фактические метрики:\nWPM={metrics['wpm']}\nПаузы={metrics['pause_percent']}%\nПаразиты={metrics['fillers_per_min']}/мин\nИзбыточность={metrics['redundancy_percent']}%\npitch_cv={metrics['pitch_cv']}\nЗрительный контакт={metrics['eye_contact']}/5\n\n"
        'JSON:\n{ "items": [ {"title":"...","text":"...","why_for_scenario":"...","action":"...","evidence":["..."],"metrics":["wpm"],"timecode":null} ] }'
    )
    result = generate_json_block(block_name="growth_v2", system_prompt=system_prompt, user_prompt=user_prompt, schema_validator=lambda payload: isinstance(payload.get("items"), list), max_tokens=340, temperature=0.25, request_id=request_id, session_id=session_id, client=client, llm_enabled=True)
    if result.get("ok"):
        items = (result.get("payload") or {}).get("items") if isinstance(result.get("payload"), dict) else []
        cleaned = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            why = str(item.get("why_for_scenario") or "")
            if not any(marker in why for marker in (scenario_ctx["goal_ru"], scenario_ctx["audience_ru"], scenario_ctx["tone_ru"])):
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                continue
            if not any(ch.isdigit() for ch in str(evidence[0])):
                continue
            text_probe = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("text") or ""),
                    str(item.get("why_for_scenario") or ""),
                    str(item.get("action") or ""),
                ]
            )
            if not is_russian_text(text_probe, min_cyrillic_chars=35):
                continue
            cleaned.append(item)
        if len(cleaned) < 4:
            repair = _repair_block_russian_once(
                block_name="growth_v2",
                user_prompt=user_prompt,
                schema_validator=lambda payload: isinstance(payload.get("items"), list),
                max_tokens=340,
                temperature=0.25,
                request_id=str(result.get("request_id") or request_id),
                session_id=session_id,
                client=client,
            )
            if repair.get("ok"):
                items = (repair.get("payload") or {}).get("items") if isinstance(repair.get("payload"), dict) else []
                cleaned = [item for item in items if isinstance(item, dict) and is_russian_text(" ".join([str(item.get("title") or ""), str(item.get("text") or ""), str(item.get("action") or "")]), min_cyrillic_chars=35)]
                result = repair
        if 4 <= len(cleaned) <= 6:
            return {"items": cleaned[:6], "source": "llm", "fallback_reason": None, "request_id": result.get("request_id"), "llm_latency_ms": result.get("llm_latency_ms")}
    return {"items": fallback_items[:5], "source": "fallback", "fallback_reason": "not_russian" if result.get("ok") else str(result.get("reason") or "schema_invalid"), "request_id": result.get("request_id"), "llm_latency_ms": result.get("llm_latency_ms")}


def build_coaching_payload(
    *,
    results: dict[str, Any],
    transcript_text: str | None,
    segments: list[dict[str, Any]],
    scenario_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delivery = results.get("delivery") if isinstance(results.get("delivery"), dict) else {}
    word_choice = results.get("word_choice") if isinstance(results.get("word_choice"), dict) else {}
    voice = results.get("voice") if isinstance(results.get("voice"), dict) else {}
    visual = results.get("visual") if isinstance(results.get("visual"), dict) else {}
    session_id = str(results.get("session_id") or "unknown_session")

    logger.warning(
        "build coaching payload start",
        extra={
            "llm_enabled": bool(settings.local_llm_enabled),
            "llm_base_url": settings.local_llm_base_url,
            "segments_count": len(segments),
            "transcript_chars": len((transcript_text or "").strip()),
        },
    )

    wpm_category = _metric_text(delivery, "tempo", "wpm_category")
    pause_ratio = _metric_value(delivery, "pauses", "pause_ratio", "value")
    filler_count = _metric_value(word_choice, "fillers", "count", "value")
    filler_density = _metric_value(word_choice, "fillers", "density", "value")
    starter_items = (word_choice.get("templates") or {}).get("sentence_starters", {}).get("items", [])
    top_starter_ratio = None
    if isinstance(starter_items, list) and starter_items and isinstance(starter_items[0], dict):
        ratio = starter_items[0].get("ratio")
        if isinstance(ratio, (int, float)):
            top_starter_ratio = float(ratio)

    repetitions_words = (word_choice.get("repetitions") or {}).get("top_words", [])
    repetitions_phrases = (word_choice.get("repetitions") or {}).get("top_phrases", [])
    weak_words_count = _metric_value(word_choice, "weak_words", "count", "value")
    redundancy_score = _metric_value(word_choice, "conciseness", "redundancy_score", "value")

    pitch_label = _metric_text(voice, "pitch", "label")
    loudness_label = _metric_text(voice, "loudness", "label")
    centering = _metric_value(visual, "centering", "value")
    stability = _metric_value(visual, "stability", "value")

    issues: list[tuple[int, str]] = []

    if wpm_category == "below":
        issues.append((4, "Темп ниже нормы 140–160: ускоряйте ключевые блоки на 1–2 фразы в минуту."))
    elif wpm_category == "above":
        issues.append((4, "Темп выше нормы 140–160: замедлитесь и добавляйте короткую паузу после тезиса."))

    if isinstance(pause_ratio, (int, float)):
        if pause_ratio > 0.30:
            t = _first_timecode((delivery.get("pauses") or {}).get("events"))
            issues.append((4, f"Пауз слишком много: объединяйте короткие фразы в цельные мысли{_fmt_sec(t)}."))
        elif pause_ratio < 0.08:
            issues.append((3, "Пауз мало: делайте смысловую паузу 0.5–1 сек после каждого важного тезиса."))

    if isinstance(filler_count, (int, float)) and filler_count >= 6:
        t = _first_timecode((word_choice.get("fillers") or {}).get("events"))
        issues.append((5, f"Слова-паразиты заметны: заменяйте их микропаузой и дыханием{_fmt_sec(t)}."))
    elif isinstance(filler_density, (int, float)) and filler_density >= 3:
        issues.append((4, "Высокая плотность паразитов: тренируйте короткие ответы с паузами вместо вводных слов."))

    if isinstance(top_starter_ratio, (int, float)) and top_starter_ratio >= 0.35:
        t = _first_timecode((starter_items[0] or {}).get("timecodes") if starter_items else None)
        issues.append((3, f"Повторяются одинаковые начала предложений: чередуйте формулировки вступления{_fmt_sec(t)}."))

    top_word_count = repetitions_words[0].get("count") if isinstance(repetitions_words, list) and repetitions_words and isinstance(repetitions_words[0], dict) else 0
    top_phrase_count = repetitions_phrases[0].get("count") if isinstance(repetitions_phrases, list) and repetitions_phrases and isinstance(repetitions_phrases[0], dict) else 0
    if isinstance(top_word_count, (int, float)) and top_word_count >= 5 or isinstance(top_phrase_count, (int, float)) and top_phrase_count >= 4:
        t = _first_timecode(
            (repetitions_words[0] or {}).get("timecodes") if repetitions_words else None,
            (repetitions_phrases[0] or {}).get("timecodes") if repetitions_phrases else None,
        )
        issues.append((3, f"Есть повторяющиеся слова/фразы: замените повторы синонимами и примерами{_fmt_sec(t)}."))

    if isinstance(weak_words_count, (int, float)) and weak_words_count >= 5:
        issues.append((4, "Много смягчающих формулировок: уберите «может», «наверное» в ключевых тезисах."))

    if isinstance(redundancy_score, (int, float)) and redundancy_score >= 0.45:
        issues.append((4, "Речь избыточна: сократите вводные конструкции и оставьте только смысловые фразы."))

    if pitch_label == "монотонно":
        issues.append((4, "Интонация монотонна: меняйте высоту голоса на переходах между идеями."))

    if loudness_label == "сильные перепады":
        issues.append((3, "Громкость неравномерна: держите стабильный уровень и избегайте резких скачков."))

    if isinstance(centering, (int, float)) and centering < 60:
        issues.append((3, "Кадрирование слабое: держите лицо ближе к центру кадра на уровне глаз."))

    if isinstance(stability, (int, float)) and stability < 60:
        issues.append((3, "Поза нестабильна: зафиксируйте корпус и уменьшите лишние движения руками."))

    issues.sort(key=lambda x: x[0], reverse=True)
    growth_bullets = [item[1] for item in issues[:5]] or ["Продолжайте практику: запишите ещё один дубль и сравните динамику метрик."]

    scenario_profile = scenario_profile if isinstance(scenario_profile, dict) else {}
    preset_id = str(scenario_profile.get("preset_id") or "conference_talk")
    scenario_ctx = {
        "preset_id": preset_id,
        "preset_label_ru": str(scenario_profile.get("preset_label_ru") or PRESET_RU_LABELS.get(preset_id) or preset_id),
        "goal": str(scenario_profile.get("goal") or "inform"),
        "audience": str(scenario_profile.get("audience") or "general"),
        "tone": str(scenario_profile.get("tone") or "friendly"),
        "goal_ru": GOAL_RU_LABELS.get(str(scenario_profile.get("goal") or "inform"), "информировать"),
        "audience_ru": AUDIENCE_RU_LABELS.get(str(scenario_profile.get("audience") or "general"), "широкая аудитория"),
        "tone_ru": TONE_RU_LABELS.get(str(scenario_profile.get("tone") or "friendly"), "Дружелюбный"),
    }
    metrics_snapshot = _build_metrics_snapshot(results=results, norms=scenario_profile.get("norms") if isinstance(scenario_profile.get("norms"), dict) else {})
    strength_v2 = _generate_strength_v2(session_id=session_id, scenario_ctx=scenario_ctx, metrics=metrics_snapshot)
    growth_v2 = _generate_growth_v2(session_id=session_id, scenario_ctx=scenario_ctx, metrics=metrics_snapshot)
    brief = _build_coaching_brief(transcript_text, segments)
    summary_bullets = _generate_key_moments(transcript_text=transcript_text, segments=segments, session_id=session_id, brief=brief, scenario_ctx=scenario_ctx)
    questions = _generate_audience_questions(
        transcript_text=transcript_text,
        segments=segments,
        summary_bullets=summary_bullets,
        session_id=session_id,
        brief=brief,
        scenario_ctx=scenario_ctx,
    )
    summary_keywords = _generate_summary_keywords(
        transcript_text=transcript_text,
        segments=segments,
        session_id=session_id,
        brief=brief,
        scenario_ctx=scenario_ctx,
    )

    logger.warning(
        "build coaching payload completed",
        extra={
            "questions_items": len(questions),
            "summary_items": len(summary_bullets),
            "summary_keywords": len(summary_keywords),
        },
    )

    _debug_llm("build coaching payload final", questions=questions[:5], summary=summary_bullets[:5], keywords=summary_keywords[:8])
    outcomes = get_last_coaching_outcomes()
    questions_outcome = outcomes.get("questions") or {"used": "fallback", "reason": "low_quality", "request_id": "na", "llm_latency_ms": None}
    summary_outcome = outcomes.get("summary") or {"used": "fallback", "reason": "low_quality", "request_id": "na", "llm_latency_ms": None}
    keywords_outcome = outcomes.get("keywords") or {"used": "fallback", "reason": "low_quality", "request_id": "na", "llm_latency_ms": None}

    return {
        "strength": {
            "title": "Сила",
            "text": str((strength_v2.get("items") or [{}])[0].get("text") if isinstance((strength_v2.get("items") or [{}])[0], dict) else "Есть базовая структура выступления - это хорошая основа для усиления подачи."),
            "rating": _rating_from_issues(1),
        },
        "strength_v2": strength_v2,
        "growth": {
            "title": "Область роста",
            "bullets": growth_bullets,
            "rating": _rating_from_issues(len(growth_bullets)),
        },
        "growth_v2": growth_v2,
        "questions": {
            "title": "Вопросы аудитории",
            "items": questions[:5],
            "source": "llm" if questions_outcome.get("used") == "llm" else "fallback",
            "fallback_reason": None if questions_outcome.get("used") == "llm" else questions_outcome.get("reason"),
            "request_id": questions_outcome.get("request_id"),
            "llm_latency_ms": questions_outcome.get("llm_latency_ms"),
        },
        "summary": {
            "title": "Резюме",
            "bullets": summary_bullets[:5],
            "keywords": summary_keywords[:8],
            "source": "llm" if summary_outcome.get("used") == "llm" else "fallback",
            "fallback_reason": None if summary_outcome.get("used") == "llm" else summary_outcome.get("reason"),
            "request_id": summary_outcome.get("request_id"),
            "llm_latency_ms": summary_outcome.get("llm_latency_ms"),
        },
        "keywords": {
            "title": "Ключевые слова",
            "items": summary_keywords[:8],
            "source": "llm" if keywords_outcome.get("used") == "llm" else "fallback",
            "fallback_reason": None if keywords_outcome.get("used") == "llm" else keywords_outcome.get("reason"),
            "request_id": keywords_outcome.get("request_id"),
            "llm_latency_ms": keywords_outcome.get("llm_latency_ms"),
        },
    }
