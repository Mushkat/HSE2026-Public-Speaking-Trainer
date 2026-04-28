import re
from collections import Counter
from pathlib import Path

from app.services.speech_alignment import (
    SpeechWindow,
    build_speech_window,
    filter_timecodes_to_segments,
    overlap_seconds,
)


WINDOW_SEC = 10
WPM_NORMAL_MIN = 140
WPM_NORMAL_MAX = 160
MIN_ACTIVE_SPEECH_SEC = 5.0
MIN_WINDOW_SPEECH_SEC = 2.0
MIN_WINDOW_WORDS = 2
MIN_PAUSE_SEC = 0.3
MAX_PAUSE_EVENTS = 10
FILLER_PHRASES_RU = [
    "ээ",
    "эм",
    "ну",
    "как бы",
    "типа",
    "короче",
    "в общем",
    "значит",
    "это самое",
    "так сказать",
]

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_SENTENCE_TOKEN_RE = re.compile(r"[\w-]+|[.!?…]+", re.UNICODE)

RU_STOPWORDS = {
    "и", "в", "на", "что", "это", "как", "а", "но", "или", "к", "с", "по", "за", "о", "об", "от", "до", "у", "же", "ли", "бы", "не",
    "мы", "вы", "я", "они", "он", "она", "оно", "их", "нас", "нам", "вас", "мой", "твой", "свой", "так", "вот", "то", "эта", "этот", "эти",
}
WEAK_WORDS_RU = [
    "как бы", "типа", "ну", "в общем", "короче", "собственно", "скажем так",
    "по сути", "в принципе", "в целом", "вообще", "реально", "буквально",
    "просто", "на самом деле", "как сказать", "вот", "значит", "то есть",
    "как-то", "немножко", "чуть-чуть", "немного", "вроде", "в некотором смысле",
    "так сказать", "условно", "фактически", "в итоге", "в результате",
    "получается", "скажем", "примерно", "грубо говоря",
]
STARTER_SKIP_TOKENS = {"ээ", "эм", "ну", "так", "вот", "значит", "типа"}


def _normalize_token(value: str) -> str:
    return re.sub(r"[^\wа-яё-]+", "", value.lower(), flags=re.IGNORECASE).strip()


def _extract_timed_words(transcript_text: str | None, transcript_words: list[dict] | None, duration_seconds: float) -> list[dict]:
    words: list[dict] = []
    raw_words = transcript_words if isinstance(transcript_words, list) else []
    for item in raw_words:
        if not isinstance(item, dict):
            continue
        token = str(item.get("token") or "").strip()
        start = item.get("start")
        end = item.get("end")
        if not token or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            continue
        norm = _normalize_token(token)
        if not norm:
            continue
        words.append({"token": token, "normalized": norm, "start": float(start), "end": float(end)})

    if not words:
        return _build_synthetic_words(transcript_text, duration_seconds)

    return words


def _build_synthetic_words(transcript_text: str | None, duration_seconds: float) -> list[dict]:
    tokens = [_normalize_token(token) for token in _TOKEN_RE.findall(transcript_text or "")]
    tokens = [token for token in tokens if token]
    if not tokens:
        return []

    safe_duration = max(duration_seconds, 1.0)
    step = safe_duration / len(tokens)
    return [
        {
            "token": token,
            "normalized": token,
            "start": idx * step,
            "end": min(safe_duration, (idx + 1) * step),
        }
        for idx, token in enumerate(tokens)
    ]


def _build_sentences(transcript_text: str | None, words: list[dict]) -> list[list[dict]]:
    text = (transcript_text or "").strip()
    if not words:
        return []

    if text and re.search(r"[.!?…]", text):
        sentences: list[list[dict]] = []
        sentence_tokens: list[str] = []
        for token in _SENTENCE_TOKEN_RE.findall(text):
            if re.fullmatch(r"[.!?…]+", token):
                if sentence_tokens:
                    sentences.append(sentence_tokens)
                    sentence_tokens = []
                continue
            normalized = _normalize_token(token)
            if normalized:
                sentence_tokens.append(normalized)
        if sentence_tokens:
            sentences.append(sentence_tokens)

        mapped: list[list[dict]] = []
        cursor = 0
        for sentence in sentences:
            chunk: list[dict] = []
            for expected in sentence:
                while cursor < len(words):
                    candidate = words[cursor]
                    cursor += 1
                    if candidate["normalized"] == expected:
                        chunk.append(candidate)
                        break
            if chunk:
                mapped.append(chunk)
        if mapped:
            return mapped

    mapped: list[list[dict]] = []
    current: list[dict] = []
    for idx, word in enumerate(words):
        current.append(word)
        next_word = words[idx + 1] if idx + 1 < len(words) else None
        boundary_by_pause = bool(next_word and next_word["start"] - word["end"] >= 0.8)
        boundary_by_punct = bool(re.search(r"[.!?…]", str(word.get("token") or "")))
        if boundary_by_pause or boundary_by_punct:
            mapped.append(current)
            current = []
    if current:
        mapped.append(current)
    return mapped


def _word_timecodes(words: list[dict], token: str, *, label: str, kind: str = "info", limit: int = 10) -> list[dict]:
    timecodes = []
    for word in words:
        if word["normalized"] != token:
            continue
        timecodes.append({"t": round(word["start"], 2), "label": label, "kind": kind})
        if len(timecodes) >= limit:
            break
    return _dedupe_timecodes(timecodes, limit=limit)


def _phrase_timecodes(words: list[dict], phrase_tokens: list[str], *, label: str, kind: str = "info", limit: int = 10) -> list[dict]:
    if not phrase_tokens:
        return []
    normalized = [word["normalized"] for word in words]
    hits: list[dict] = []
    span = len(phrase_tokens)
    for idx in range(0, len(words) - span + 1):
        if normalized[idx : idx + span] != phrase_tokens:
            continue
        hits.append({"t": round(words[idx]["start"], 2), "label": label, "kind": kind})
        if len(hits) >= limit:
            break
    return _dedupe_timecodes(hits, limit=limit)


def _phrase_occurrences(words: list[dict], phrase_tokens: list[str], *, label: str, kind: str = "info") -> list[dict]:
    if not phrase_tokens:
        return []
    normalized = [word["normalized"] for word in words]
    hits: list[dict] = []
    span = len(phrase_tokens)
    for idx in range(0, len(words) - span + 1):
        if normalized[idx : idx + span] != phrase_tokens:
            continue
        hits.append({"t": round(words[idx]["start"], 2), "label": label, "kind": kind})
    return hits


def _dedupe_timecodes(timecodes: list[dict], *, min_gap_sec: float = 2.0, limit: int = 10) -> list[dict]:
    unique: list[dict] = []
    for item in sorted(timecodes, key=lambda row: float(row.get("t", 0) or 0)):
        t = float(item.get("t", 0) or 0)
        if unique and abs(float(unique[-1].get("t", 0) or 0) - t) < min_gap_sec and unique[-1].get("label") == item.get("label"):
            continue
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _rating_with_note(value: float, *, good_lt: float, ok_lt: float, notes: tuple[str, str, str]) -> tuple[str, str]:
    if value < good_lt:
        return "good", notes[0]
    if value <= ok_lt:
        return "ok", notes[1]
    return "bad", notes[2]


def _build_word_choice(
    words: list[dict],
    transcript_text: str | None,
    *,
    speech_active_min: float,
    filler_count: int,
    speech_segments: list[dict],
) -> dict:
    sentences = _build_sentences(transcript_text, words)
    sentence_starters: Counter = Counter()
    sentence_starter_timecodes: dict[str, list[dict]] = {}

    for sentence in sentences:
        starter = next((w for w in sentence if w["normalized"] not in STARTER_SKIP_TOKENS), None)
        if not starter:
            continue
        key = starter["normalized"]
        sentence_starters[key] += 1
        sentence_starter_timecodes.setdefault(
            key,
            _word_timecodes(words, key, label=f"«{starter['token'].strip()}…»", kind="info", limit=10),
        )

    starter_items = []
    total_sentences = max(len(sentences), 1)
    for starter, count in sentence_starters.most_common(3):
        starter_items.append(
            {
                "starter": starter.capitalize(),
                "ratio": round(count / total_sentences, 2),
                "count": count,
                "timecodes": sentence_starter_timecodes.get(starter, []),
            }
        )
    top_ratio = starter_items[0]["ratio"] if starter_items else 0.0
    starters_rating, starters_note = _rating_with_note(
        top_ratio,
        good_lt=0.18,
        ok_lt=0.28,
        notes=(
            "Начала предложений разнообразные",
            "Часть предложений начинается одинаково",
            "Слишком много предложений начинается одинаково",
        ),
    )

    normalized_tokens = [word["normalized"] for word in words]
    meaningful_words = [token for token in normalized_tokens if token not in RU_STOPWORDS and len(token) > 2]
    word_counter = Counter(meaningful_words)
    top_words = [
        {"word": word, "count": count, "timecodes": _word_timecodes(words, word, label=f"«{word}»", kind="issue", limit=10)}
        for word, count in word_counter.most_common(5)
        if count >= 2
    ]

    phrase_counter: Counter = Counter()
    full_tokens = [word["normalized"] for word in words]
    for n in (2, 3):
        for idx in range(0, len(full_tokens) - n + 1):
            phrase = tuple(full_tokens[idx : idx + n])
            if any(token in RU_STOPWORDS or len(token) <= 2 for token in phrase):
                continue
            phrase_counter[phrase] += 1
    phrase_threshold = 2 if len(meaningful_words) < 80 else 3
    top_phrases = []
    for phrase_tuple, count in phrase_counter.most_common(5):
        if count < phrase_threshold:
            continue
        phrase = " ".join(phrase_tuple)
        top_phrases.append(
            {
                "phrase": phrase,
                "count": count,
                "timecodes": _phrase_timecodes(words, list(phrase_tuple), label=f"«{phrase}»", kind="issue", limit=10),
            }
        )

    total_meaningful = max(len(meaningful_words), 1)
    top_word_ratio = (top_words[0]["count"] / total_meaningful) if top_words else 0.0
    if top_word_ratio > 0.08 or (top_phrases and top_phrases[0]["count"] >= 5):
        repetitions_rating, repetitions_note = "bad", "Много повторов одного и того же выражения"
    elif top_word_ratio < 0.05 and not top_phrases:
        repetitions_rating, repetitions_note = "good", "Повторы минимальны"
    else:
        repetitions_rating, repetitions_note = "ok", "Повторы умеренные"

    weak_phrase_tokens = [
        (" ".join(_normalize_token(token) for token in phrase.split()), [_normalize_token(token) for token in phrase.split()])
        for phrase in WEAK_WORDS_RU
    ]
    weak_items = []
    weak_total = 0
    for phrase, tokens in weak_phrase_tokens:
        if len(tokens) == 1:
            count = sum(1 for token in normalized_tokens if token == phrase)
            if count > 0:
                weak_total += count
                weak_items.append({"word": phrase, "count": count, "timecodes": _word_timecodes(words, phrase, label=f"«{phrase}»", kind="issue", limit=10)})
        else:
            all_hits = _phrase_occurrences(words, tokens, label=f"«{phrase}»", kind="issue")
            if all_hits:
                weak_total += len(all_hits)
                weak_items.append({"word": phrase, "count": len(all_hits), "timecodes": all_hits[:10]})
    weak_items = sorted(weak_items, key=lambda item: item["count"], reverse=True)

    weak_per_min = weak_total / max(speech_active_min, 1e-6)
    weak_per_3_min = weak_total / max(speech_active_min / 3, 1e-6)
    if weak_per_3_min <= 1:
        weak_rating, weak_note = "good", "Речь звучит уверенно"
    elif weak_per_3_min < 6:
        weak_rating, weak_note = "ok", "Есть смягчающие слова - можно говорить прямее"
    else:
        weak_rating, weak_note = "bad", "Слишком много смягчающих слов - речь звучит неуверенно"

    unique_words = len(set(meaningful_words))
    repetition_ratio = 1 - (unique_words / total_meaningful)
    long_sentence_ratio = (
        sum(1 for sentence in sentences if len(sentence) > 20) / max(len(sentences), 1)
    )
    filler_per_min = filler_count / max(speech_active_min, 1e-6)
    filler_density_norm = max(0.0, min(1.0, filler_per_min / 3.0))

    redundancy_score = max(0.0, min(1.0, 0.4 * long_sentence_ratio + 0.4 * repetition_ratio + 0.2 * filler_density_norm))

    if redundancy_score < 0.25:
        conciseness_rating, conciseness_note = "good", "Речь достаточно лаконична"
    elif redundancy_score <= 0.45:
        conciseness_rating, conciseness_note = "ok", "Есть избыточность - можно сократить вводные фразы"
    else:
        conciseness_rating, conciseness_note = "bad", "Много избыточных фраз и повторов - сократите и структурируйте тезисы"

    for item in starter_items:
        item["timecodes"] = filter_timecodes_to_segments(item["timecodes"], segments=speech_segments) or item["timecodes"]
    for item in top_words:
        item["timecodes"] = filter_timecodes_to_segments(item["timecodes"], segments=speech_segments) or item["timecodes"]
    for item in top_phrases:
        item["timecodes"] = filter_timecodes_to_segments(item["timecodes"], segments=speech_segments) or item["timecodes"]
    for item in weak_items:
        item["timecodes"] = filter_timecodes_to_segments(item["timecodes"], segments=speech_segments) or item["timecodes"]

    return {
        "templates": {
            "sentence_starters": {
                "items": starter_items,
                "rating": starters_rating,
                "note": starters_note,
            }
        },
        "repetitions": {
            "top_words": top_words,
            "top_phrases": top_phrases,
            "density_per_min": round((sum(item["count"] for item in top_words) / max(speech_active_min, 1e-6)), 3) if top_words else 0.0,
            "rating": repetitions_rating,
            "note": repetitions_note,
        },
        "weak_words": {
            "items": weak_items,
            "count": weak_total,
            "density_per_min": round(weak_per_min, 3),
            "rating": weak_rating,
            "note": weak_note,
        },
        "conciseness": {
            "redundancy_score": {
                "value": round(redundancy_score, 2),
                "unit": "ratio",
                "label": "Избыточность",
                "rating": conciseness_rating,
                "note": conciseness_note,
            }
        },
    }


def _calculate_pauses_from_words(words: list[dict], speech_window: SpeechWindow, duration_seconds: float) -> tuple[float, list[dict], dict]:
    pauses: list[dict] = []
    total_silence = 0.0
    longest_pause = 0.0
    duration_total = max(float(duration_seconds), 0.0)
    window_start = float(speech_window.window_start)
    window_end = float(speech_window.window_end) if speech_window.window_end > speech_window.window_start else max(window_start, duration_total)
    analysis_window_sec = max(0.001, speech_window.speech_active_sec)
    if len(words) < 2:
        return 0.0, pauses, {"total_pause_sec": 0.0, "count": 0, "longest_pause_sec": 0.0, "analysis_window_sec": round(analysis_window_sec, 2)}

    for idx in range(len(words) - 1):
        raw_start = float(words[idx]["end"])
        raw_end = float(words[idx + 1]["start"])
        pause_start = max(raw_start, window_start)
        pause_end = min(raw_end, window_end)
        gap = max(0.0, pause_end - pause_start)
        if gap < MIN_PAUSE_SEC:
            continue
        pauses.append(
            {
                "start": round(pause_start, 2),
                "end": round(pause_end, 2),
                "dur": round(gap, 2),
                "t": round(pause_start, 2),
                "label": f"Пауза {gap:.1f}с",
                "kind": "issue" if gap >= 1.2 else "info",
            }
        )
        total_silence += gap
        longest_pause = max(longest_pause, gap)

    denominator_sec = max(0.001, speech_window.speech_active_sec + total_silence)
    pause_ratio = min(1.0, max(0.0, total_silence / denominator_sec))
    top_pauses = sorted(pauses, key=lambda item: (-float(item["dur"]), float(item["start"])))[:MAX_PAUSE_EVENTS]
    top_pauses = sorted(top_pauses, key=lambda item: float(item["start"]))
    return round(pause_ratio, 4), top_pauses, {
        "total_pause_sec": round(total_silence, 2),
        "count": len(pauses),
        "longest_pause_sec": round(longest_pause, 2),
        "analysis_window_sec": round(analysis_window_sec, 2),
        "speech_window_sec": round(speech_window.speech_active_sec, 2),
        "scope": "speech_span_without_edge_silence",
    }


def _wpm_category(wpm_avg: float) -> tuple[str, float]:
    if wpm_avg < WPM_NORMAL_MIN:
        return "below", round(WPM_NORMAL_MIN - wpm_avg, 2)
    if wpm_avg > WPM_NORMAL_MAX:
        return "above", round(wpm_avg - WPM_NORMAL_MAX, 2)
    return "normal", 0.0


def _format_time_label(seconds: float) -> str:
    safe = max(0, int(round(seconds)))
    hours, remainder = divmod(safe, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _window_count_for_speech(speech_active_sec: float) -> int:
    return 5 if speech_active_sec < 60 else 7


def map_speech_time_to_timeline_intervals(
    speech_segments: list[dict],
    a_speech: float,
    b_speech: float,
) -> list[list[float]]:
    if not speech_segments or b_speech <= a_speech:
        return []

    mapped: list[list[float]] = []
    consumed_speech = 0.0
    for segment in speech_segments:
        seg_start = float(segment.get("start", 0.0) or 0.0)
        seg_end = float(segment.get("end", 0.0) or 0.0)
        seg_duration = max(0.0, seg_end - seg_start)
        if seg_duration <= 0:
            continue

        seg_speech_from = consumed_speech
        seg_speech_to = consumed_speech + seg_duration
        overlap_from = max(a_speech, seg_speech_from)
        overlap_to = min(b_speech, seg_speech_to)
        if overlap_to > overlap_from:
            mapped.append(
                [
                    round(seg_start + (overlap_from - seg_speech_from), 4),
                    round(seg_start + (overlap_to - seg_speech_from), 4),
                ]
            )
        consumed_speech = seg_speech_to
        if consumed_speech >= b_speech:
            break
    return mapped


def _build_speech_time_windows(words: list[dict], speech_segments: list[dict], speech_active_sec: float) -> list[dict]:
    if speech_active_sec <= 0 or not speech_segments:
        return []

    total_windows = _window_count_for_speech(speech_active_sec)
    window_speech_sec = speech_active_sec / max(total_windows, 1)
    if window_speech_sec <= 0:
        return []

    windows: list[dict] = []

    for index in range(total_windows):
        speech_start = round(index * window_speech_sec, 4)
        speech_end = round(speech_active_sec if index == total_windows - 1 else (index + 1) * window_speech_sec, 4)
        real_intervals = map_speech_time_to_timeline_intervals(speech_segments, speech_start, speech_end)

        words_in_window = 0
        for word in words:
            midpoint = (float(word["start"]) + float(word["end"])) / 2
            if any(start <= midpoint < end for start, end in real_intervals):
                words_in_window += 1

        speech_span = max(0.0, speech_end - speech_start)
        if speech_span >= MIN_WINDOW_SPEECH_SEC and words_in_window >= MIN_WINDOW_WORDS:
            window_wpm = round(words_in_window / (speech_span / 60), 2)
        else:
            window_wpm = None

        windows.append(
            {
                "idx": index + 1,
                "label": f"Речь {_format_time_label(speech_start)}–{_format_time_label(speech_end)}",
                "speech_from_sec": speech_start,
                "speech_to_sec": speech_end,
                "wpm": window_wpm,
                "words": words_in_window,
                "speech_sec": round(speech_span, 4),
                "timeline_spans": real_intervals,
                "seek_to_sec": real_intervals[0][0] if real_intervals else None,
                "speech_t_start": speech_start,
                "speech_t_end": speech_end,
                "t_start": real_intervals[0][0] if real_intervals else None,
                "t_end": real_intervals[-1][1] if real_intervals else None,
                "speech_active_sec": round(speech_span, 4),
            }
        )

    return windows


def build_speech_metrics(*, transcript_text: str | None, transcript_words: list[dict] | None, audio_path: Path, duration_seconds: float, speech_window: SpeechWindow | None = None) -> dict:
    safe_duration = max(duration_seconds, 1.0)
    words = _extract_timed_words(transcript_text, transcript_words, safe_duration)

    word_count = len(words)
    duration_min = safe_duration / 60
    speech_window = speech_window or build_speech_window(audio_path=audio_path, transcript_words=words, duration_seconds=safe_duration)
    speech_segments = speech_window.segments
    speech_active_sec = speech_window.speech_active_sec
    speech_active_min = speech_active_sec / 60 if speech_active_sec > 0 else 0.0

    if speech_active_sec >= MIN_ACTIVE_SPEECH_SEC and speech_active_min > 0:
        wpm_avg = round(word_count / speech_active_min, 2)
        category, delta_to_normal = _wpm_category(wpm_avg)
        wpm_note = None
    else:
        wpm_avg = None
        category = None
        delta_to_normal = None
        wpm_note = "Недостаточно речевой активности для расчета темпа"

    wpm_windows = _build_speech_time_windows(words, speech_segments, speech_active_sec)

    pause_ratio, pauses, pauses_stats = _calculate_pauses_from_words(words, speech_window, safe_duration)

    if pause_ratio < 0.08:
        pause_category = "low"
        pause_note = "Паузы почти отсутствуют - может быть тяжело воспринимать"
    elif pause_ratio > 0.30:
        pause_category = "high"
        pause_note = "Паузы встречаются часто - возможно есть заминки"
    else:
        pause_category = "normal"
        pause_note = "Паузы в разумном диапазоне"

    normalized_tokens = [word["normalized"] for word in words]
    filler_matches = []
    phrase_token_variants = [(phrase, phrase.split()) for phrase in FILLER_PHRASES_RU]
    i = 0
    while i < len(words):
        matched = False
        for phrase, tokens in phrase_token_variants:
            seq_len = len(tokens)
            if normalized_tokens[i : i + seq_len] == tokens:
                filler_matches.append(
                    {
                        "phrase": phrase,
                        "start": round(words[i]["start"], 2),
                        "end": round(words[i + seq_len - 1]["end"], 2),
                        "t": round(words[i]["start"], 2),
                        "label": phrase,
                        "kind": "issue",
                    }
                )
                i += seq_len
                matched = True
                break
        if not matched:
            i += 1

    filler_matches = _dedupe_timecodes(filler_matches, min_gap_sec=2.0, limit=10)
    filler_matches = filter_timecodes_to_segments(filler_matches, segments=speech_segments) or filler_matches
    filler_count = len(filler_matches)
    filler_density = round(filler_count / speech_active_min, 3) if speech_active_min > 0 else 0.0
    filler_top = [{"phrase": phrase, "count": count} for phrase, count in Counter(item["phrase"] for item in filler_matches).most_common(5)]

    word_choice_metrics = _build_word_choice(words, transcript_text, speech_active_min=speech_active_min or duration_min, filler_count=filler_count, speech_segments=speech_segments)

    return {
        "wpm_avg": wpm_avg,
        "wpm_series": wpm_windows,
        "wpm_windows": wpm_windows,
        "wpm_normal_range": {"min": WPM_NORMAL_MIN, "max": WPM_NORMAL_MAX},
        "wpm_category": category,
        "wpm_note": wpm_note,
        "delta_to_normal": delta_to_normal,
        "speech_active_sec": round(speech_active_sec, 2),
        "speech_segments": [{"start": round(item["start"], 2), "end": round(item["end"], 2)} for item in speech_segments],
        "speech_segments_source": speech_window.source,
        "pause_ratio": pause_ratio,
        "pauses": pauses,
        "pauses_stats": pauses_stats,
        "pause_norm_percent": {"min": 10, "max": 25},
        "pause_category": pause_category,
        "pause_note": pause_note,
        "filler_count": filler_count,
        "filler_density_per_min": filler_density,
        "fillers": filler_matches,
        "filler_top": filler_top,
        "word_choice": word_choice_metrics,
    }
