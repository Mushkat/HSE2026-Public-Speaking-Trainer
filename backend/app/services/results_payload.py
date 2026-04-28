from __future__ import annotations

from datetime import datetime
from typing import Any

WPM_MIN = 140
WPM_MAX = 160

VOICE_PLACEHOLDER_NOTE = "Недостаточно данных для оценки голоса"
VISUAL_PLACEHOLDER_NOTE = "Нет данных"


def _iso_now() -> str:
    return datetime.utcnow().isoformat()


def _metric(label: str, unit: str, value: float | int | None, rating: str = "na", note: str = "") -> dict[str, Any]:
    numeric_value = float(value) if isinstance(value, (int, float)) else None
    return {
        "value": numeric_value,
        "unit": unit,
        "label": label,
        "rating": rating,
        "note": note,
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _numeric_or_metric_value(value: Any) -> float | int | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict) and isinstance(value.get("value"), (int, float)):
        return value.get("value")
    return None


def _wpm_note(category: str) -> str:
    if category == "below":
        return "Ниже нормы 140–160"
    if category == "normal":
        return "В пределах нормы 140–160"
    if category == "above":
        return "Выше нормы 140–160"
    return "Нет данных"


def _rating_from_wpm(category: str) -> str:
    if category == "normal":
        return "good"
    if category in {"below", "above"}:
        return "ok"
    return "na"


def _rating_from_ratio(value: float | None, *, low: float, high: float) -> str:
    if value is None:
        return "na"
    if low <= value <= high:
        return "good"
    if value < low:
        return "ok"
    return "bad"


def _pitch_rating(value: float | None) -> str:
    if value is None:
        return "na"
    if value < 0.10:
        return "bad"
    if value <= 0.20:
        return "ok"
    return "good"


def _loudness_rating(value: float | None) -> str:
    if value is None:
        return "na"
    if value < 0.25:
        return "good"
    if value <= 0.45:
        return "ok"
    return "bad"


def _pitch_label_from_cv(value: float | None) -> str | None:
    if value is None:
        return None
    if value < 0.10:
        return "монотонно"
    if value <= 0.20:
        return "умеренно"
    return "выразительно"


def _loudness_label_from_cv(value: float | None) -> str | None:
    if value is None:
        return None
    if value < 0.25:
        return "стабильно"
    if value <= 0.45:
        return "перепады"
    return "сильные перепады"


def _map_old_results(stored: dict[str, Any]) -> dict[str, Any]:
    speech_metrics = _safe_dict(_safe_dict(stored.get("speech")).get("metrics"))
    voice_metrics = _safe_dict(_safe_dict(stored.get("voice")).get("metrics"))
    summary = _safe_dict(stored.get("summary"))
    visual = _safe_dict(stored.get("visual"))

    wpm_avg = speech_metrics.get("wpm_avg")
    wpm_category = speech_metrics.get("wpm_category") if speech_metrics.get("wpm_category") in {"below", "normal", "above"} else None
    wpm_note = speech_metrics.get("wpm_note") if isinstance(speech_metrics.get("wpm_note"), str) else None
    pause_ratio = speech_metrics.get("pause_ratio")
    filler_count = speech_metrics.get("filler_count")
    filler_density = speech_metrics.get("filler_density_per_min")

    pitch_cv = voice_metrics.get("pitch_cv")
    rms_cv = voice_metrics.get("rms_cv")

    return {
        "meta": {
            "language": summary.get("language") or stored.get("language") or "ru",
            "duration_sec": summary.get("duration_seconds"),
            "audio_format": summary.get("audio_format") or None,
            "model_versions": summary.get("model_versions") or {},
        },
        "delivery": {
            "tempo": {
                "wpm_avg": wpm_avg,
                "wpm_series": _safe_list(speech_metrics.get("wpm_windows")) or _safe_list(speech_metrics.get("wpm_series")),
                "wpm_windows": _safe_list(speech_metrics.get("wpm_windows")) or _safe_list(speech_metrics.get("wpm_series")),
                "wpm_normal_range": {"min": WPM_MIN, "max": WPM_MAX},
                "wpm_category": wpm_category,
                "wpm_note": wpm_note,
                "timecodes": [],
            },
            "pauses": {
                "pause_ratio": pause_ratio,
                "events": _safe_list(speech_metrics.get("pauses")),
                "pauses_stats": _safe_dict(speech_metrics.get("pauses_stats")),
                "pause_norm_percent": _safe_dict(speech_metrics.get("pause_norm_percent")) or {"min": 10, "max": 25},
                "pause_category": speech_metrics.get("pause_category"),
                "note": speech_metrics.get("pause_note"),
            },
        },
        "word_choice": {
            "fillers": {
                "count": filler_count,
                "density_per_min": filler_density,
                "events": _safe_list(speech_metrics.get("fillers")),
            },
            "templates": _safe_dict(_safe_dict(speech_metrics.get("word_choice")).get("templates")),
            "repetitions": _safe_dict(_safe_dict(speech_metrics.get("word_choice")).get("repetitions")),
            "weak_words": _safe_dict(_safe_dict(speech_metrics.get("word_choice")).get("weak_words")),
            "conciseness": _safe_dict(_safe_dict(speech_metrics.get("word_choice")).get("conciseness")),
        },
        "voice": {
            "pitch": {
                "cv": pitch_cv,
                "label": voice_metrics.get("pitch_variability_label"),
                "series": _safe_list(voice_metrics.get("pitch_series")),
            },
            "loudness": {
                "rms_cv": rms_cv,
                "label": voice_metrics.get("loudness_stability_label"),
                "series": _safe_list(voice_metrics.get("loudness_series")),
            },
        },
        "visual": {
            "centering": _safe_dict(visual.get("centering")),
            "stability": _safe_dict(visual.get("stability")),
            "eye_contact": _safe_dict(visual.get("eye_contact")),
        },
    }


def normalize_results_payload(
    *,
    session_id: str,
    session_status: str,
    stored_results: dict[str, Any] | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    src = _safe_dict(stored_results)
    if src.get("schema_version") == 1:
        base = src
    else:
        base = _map_old_results(src)

    meta = _safe_dict(base.get("meta"))
    delivery = _safe_dict(base.get("delivery"))
    word_choice = _safe_dict(base.get("word_choice"))
    voice = _safe_dict(base.get("voice"))
    visual = _safe_dict(base.get("visual"))
    coaching = _safe_dict(base.get("coaching"))

    tempo = _safe_dict(delivery.get("tempo"))
    pauses = _safe_dict(delivery.get("pauses"))
    fillers = _safe_dict(word_choice.get("fillers"))

    wpm_avg = _numeric_or_metric_value(tempo.get("wpm_avg"))
    wpm_category = tempo.get("wpm_category") if tempo.get("wpm_category") in {"below", "normal", "above"} else None
    wpm_note = tempo.get("wpm_note") if isinstance(tempo.get("wpm_note"), str) else _wpm_note(wpm_category or "")
    pause_ratio = _numeric_or_metric_value(pauses.get("pause_ratio"))
    if isinstance(pause_ratio, (int, float)):
        pause_ratio = float(pause_ratio) / 100 if float(pause_ratio) > 1 else float(pause_ratio)
        pause_ratio = max(0.0, min(1.0, pause_ratio))
    filler_count = _numeric_or_metric_value(fillers.get("count"))
    filler_density = None
    if isinstance(fillers.get("density_per_min"), (int, float)):
        filler_density = fillers.get("density_per_min")
    elif isinstance(fillers.get("density"), (int, float)):
        filler_density = fillers.get("density")
    else:
        filler_density = _numeric_or_metric_value(fillers.get("density"))

    pitch = _safe_dict(voice.get("pitch"))
    loudness = _safe_dict(voice.get("loudness"))
    pitch_cv = _numeric_or_metric_value(pitch.get("cv"))
    rms_cv = _numeric_or_metric_value(loudness.get("rms_cv"))
    pitch_label = pitch.get("label") if isinstance(pitch.get("label"), str) else _pitch_label_from_cv(pitch_cv)
    loudness_label = loudness.get("label") if isinstance(loudness.get("label"), str) else _loudness_label_from_cv(rms_cv)

    normalized_status = session_status if session_status in {"ready", "error", "processing"} else "processing"

    return {
        "schema_version": 1,
        "session_id": session_id,
        "generated_at": generated_at or base.get("generated_at") or _iso_now(),
        "status": normalized_status,
        "meta": {
            "language": meta.get("language") or "ru",
            "duration_sec": meta.get("duration_sec") if isinstance(meta.get("duration_sec"), (int, float)) else None,
            "audio_format": meta.get("audio_format"),
            "model_versions": _safe_dict(meta.get("model_versions")),
        },
        "delivery": {
            "tempo": {
                "wpm_avg": _metric("Темп", "wpm", wpm_avg, _rating_from_wpm(wpm_category or ""), wpm_note),
                "wpm_variability": _metric("Вариативность темпа", "%", None, "na", "Метрика будет добавлена позже"),
                "wpm_normal_range": {"min": WPM_MIN, "max": WPM_MAX},
                "wpm_category": wpm_category,
                "wpm_note": wpm_note,
                "wpm_series": _safe_list(tempo.get("wpm_windows")) or _safe_list(tempo.get("wpm_series")),
                "wpm_windows": _safe_list(tempo.get("wpm_windows")) or _safe_list(tempo.get("wpm_series")),
                "timecodes": _safe_list(tempo.get("timecodes")),
            },
            "pauses": {
                "pause_ratio": _metric("Доля пауз", "ratio", round(pause_ratio, 4) if pause_ratio is not None else None, _rating_from_ratio(pause_ratio, low=0.1, high=0.25), pauses.get("note") if isinstance(pauses.get("note"), str) else ""),
                "pause_norm_percent": _safe_dict(pauses.get("pause_norm_percent")) or {"min": 10, "max": 25},
                "pause_category": pauses.get("pause_category") if pauses.get("pause_category") in {"low", "normal", "high"} else None,
                "pauses_stats": _safe_dict(pauses.get("pauses_stats")),
                "events": _safe_list(pauses.get("events")),
            },
        },
        "word_choice": {
            "fillers": {
                "count": _metric("Слова-паразиты", "шт", filler_count, "ok" if isinstance(filler_count, (int, float)) and filler_count <= 5 else "bad" if isinstance(filler_count, (int, float)) else "na", ""),
                "density": _metric("Плотность паразитов", "в минуту", filler_density, "na" if filler_density is None else "ok", ""),
                "events": _safe_list(fillers.get("events")),
            },
            "templates": {
                "sentence_starters": {
                    "items": _safe_list(_safe_dict(_safe_dict(word_choice.get("templates")).get("sentence_starters")).get("items")),
                    "rating": _safe_dict(_safe_dict(word_choice.get("templates")).get("sentence_starters")).get("rating") or "na",
                    "note": _safe_dict(_safe_dict(word_choice.get("templates")).get("sentence_starters")).get("note") or "Нет данных",
                }
            },
            "repetitions": {
                "top_words": _safe_list(_safe_dict(word_choice.get("repetitions")).get("top_words")),
                "top_phrases": _safe_list(_safe_dict(word_choice.get("repetitions")).get("top_phrases")),
                "rating": _safe_dict(word_choice.get("repetitions")).get("rating") or "na",
                "note": _safe_dict(word_choice.get("repetitions")).get("note") or "Нет данных",
            },
            "weak_words": {
                "count": _metric(
                    "Слабые слова",
                    "шт",
                    _numeric_or_metric_value(_safe_dict(word_choice.get("weak_words")).get("count"))
                    if _numeric_or_metric_value(_safe_dict(word_choice.get("weak_words")).get("count")) is not None
                    else len(_safe_list(_safe_dict(word_choice.get("weak_words")).get("items"))),
                    _safe_dict(word_choice.get("weak_words")).get("rating") or "na",
                    _safe_dict(word_choice.get("weak_words")).get("note") or "Нет данных",
                ),
                "density_per_min": _metric(
                    "Плотность слабых слов",
                    "в минуту",
                    _numeric_or_metric_value(_safe_dict(word_choice.get("weak_words")).get("density_per_min")),
                    _safe_dict(word_choice.get("weak_words")).get("rating") or "na",
                    _safe_dict(word_choice.get("weak_words")).get("note") or "Нет данных",
                ),
                "items": _safe_list(_safe_dict(word_choice.get("weak_words")).get("items")),
            },
            "conciseness": {
                "redundancy_score": {
                    **_metric(
                        "Избыточность",
                        "ratio",
                        _numeric_or_metric_value(_safe_dict(word_choice.get("conciseness")).get("redundancy_score")),
                        _safe_dict(_safe_dict(word_choice.get("conciseness")).get("redundancy_score")).get("rating") or "na",
                        _safe_dict(_safe_dict(word_choice.get("conciseness")).get("redundancy_score")).get("note") or "Нет данных",
                    )
                },
            },
        },
        "voice": {
            "pitch": {
                "cv": _metric("Вариативность интонации", "ratio", pitch_cv, _pitch_rating(pitch_cv), VOICE_PLACEHOLDER_NOTE if pitch_cv is None else ""),
                "label": pitch_label,
                "series": _safe_list(pitch.get("series")),
            },
            "loudness": {
                "rms_cv": _metric("Стабильность громкости", "ratio", rms_cv, _loudness_rating(rms_cv), VOICE_PLACEHOLDER_NOTE if rms_cv is None else ""),
                "label": loudness_label,
                "series": _safe_list(loudness.get("series")),
            },
        },
        "visual": {
            "centering": _metric(
                "Центрирование",
                "score_0_100",
                _safe_dict(visual.get("centering")).get("value"),
                _safe_dict(visual.get("centering")).get("rating") if _safe_dict(visual.get("centering")).get("rating") in {"good", "ok", "bad", "na"} else "na",
                _safe_dict(visual.get("centering")).get("note") or VISUAL_PLACEHOLDER_NOTE,
            ),
            "stability": _metric(
                "Стабильность позы",
                "score_0_100",
                _safe_dict(visual.get("stability")).get("value"),
                _safe_dict(visual.get("stability")).get("rating") if _safe_dict(visual.get("stability")).get("rating") in {"good", "ok", "bad", "na"} else "na",
                _safe_dict(visual.get("stability")).get("note") or VISUAL_PLACEHOLDER_NOTE,
            ),
            "eye_contact": {
                **_metric(
                    "Зрительный контакт",
                    "score_1_5",
                    _safe_dict(visual.get("eye_contact")).get("value"),
                    _safe_dict(visual.get("eye_contact")).get("rating") if _safe_dict(visual.get("eye_contact")).get("rating") in {"good", "ok", "bad", "na"} else "na",
                    _safe_dict(visual.get("eye_contact")).get("note") or VISUAL_PLACEHOLDER_NOTE,
                ),
                "ratio": _safe_dict(visual.get("eye_contact")).get("ratio") if isinstance(_safe_dict(visual.get("eye_contact")).get("ratio"), (int, float)) else None,
            },
        },
        "coaching": {
            "strength": {
                "title": _safe_dict(coaching.get("strength")).get("title") or "Сила",
                "text": _safe_dict(coaching.get("strength")).get("text") or "Вы уверенно начали и обозначили тему выступления.",
                "rating": _safe_dict(coaching.get("strength")).get("rating") or "ok",
            },
            "growth": {
                "title": _safe_dict(coaching.get("growth")).get("title") or "Область роста",
                "bullets": _safe_dict(coaching.get("growth")).get("bullets")
                or [
                    "Добавьте больше конкретики и примеров в ключевых тезисах.",
                    "Сократите повторяющиеся вводные фразы.",
                ],
                "rating": _safe_dict(coaching.get("growth")).get("rating") or "ok",
            },
            "questions": {
                "title": _safe_dict(coaching.get("questions")).get("title") or "Вопросы аудитории",
                "items": _safe_dict(coaching.get("questions")).get("items") or [],
                "source": _safe_dict(coaching.get("questions")).get("source") or "fallback",
                "fallback_reason": _safe_dict(coaching.get("questions")).get("fallback_reason"),
                "request_id": _safe_dict(coaching.get("questions")).get("request_id"),
                "llm_latency_ms": _safe_dict(coaching.get("questions")).get("llm_latency_ms"),
            },
            "summary": {
                "title": _safe_dict(coaching.get("summary")).get("title") or "Резюме",
                "bullets": _safe_dict(coaching.get("summary")).get("bullets") or [],
                "keywords": _safe_dict(coaching.get("summary")).get("keywords")
                or [],
                "source": _safe_dict(coaching.get("summary")).get("source") or "fallback",
                "fallback_reason": _safe_dict(coaching.get("summary")).get("fallback_reason"),
                "request_id": _safe_dict(coaching.get("summary")).get("request_id"),
                "llm_latency_ms": _safe_dict(coaching.get("summary")).get("llm_latency_ms"),
            },
            "keywords": {
                "title": _safe_dict(coaching.get("keywords")).get("title") or "Ключевые слова",
                "items": _safe_dict(coaching.get("keywords")).get("items")
                or _safe_dict(coaching.get("summary")).get("keywords")
                or [],
                "source": (
                    _safe_dict(coaching.get("keywords")).get("source")
                    or (
                        "llm"
                        if (
                            (_safe_dict(coaching.get("keywords")).get("request_id"))
                            and (_safe_dict(coaching.get("keywords")).get("items"))
                        )
                        else None
                    )
                    or _safe_dict(coaching.get("summary")).get("source")
                    or "fallback"
                ),
                "fallback_reason": _safe_dict(coaching.get("keywords")).get("fallback_reason") or _safe_dict(coaching.get("summary")).get("fallback_reason"),
                "request_id": _safe_dict(coaching.get("keywords")).get("request_id"),
                "llm_latency_ms": _safe_dict(coaching.get("keywords")).get("llm_latency_ms"),
            },
            "goal": {
                "status": _safe_dict(coaching.get("goal")).get("status")
                if _safe_dict(coaching.get("goal")).get("status") in {"achieved", "partial", "not_achieved"}
                else "partial",
                "achieved": _safe_dict(coaching.get("goal")).get("achieved")
                if _safe_dict(coaching.get("goal")).get("achieved") in {"yes", "partial", "no"}
                else ("yes" if _safe_dict(coaching.get("goal")).get("status") == "achieved" else "no" if _safe_dict(coaching.get("goal")).get("status") == "not_achieved" else "partial"),
                "summary": _safe_dict(coaching.get("goal")).get("summary") or "",
                "criteria": _safe_dict(coaching.get("goal")).get("criteria") or [],
                "reasons": _safe_dict(coaching.get("goal")).get("reasons") or [],
                "actions": _safe_dict(coaching.get("goal")).get("actions") or [],
                "source": _safe_dict(coaching.get("goal")).get("source") or "fallback",
                "fallback_reason": _safe_dict(coaching.get("goal")).get("fallback_reason"),
                "request_id": _safe_dict(coaching.get("goal")).get("request_id"),
                "llm_latency_ms": _safe_dict(coaching.get("goal")).get("llm_latency_ms"),
            },
        },
    }


def build_session_summary(session: Any, status_value: str) -> dict[str, Any]:
    results = normalize_results_payload(
        session_id=str(session.id),
        session_status=status_value,
        stored_results=session.analysis_results if isinstance(session.analysis_results, dict) else None,
    )
    return {
        "id": str(session.id),
        "created_at": session.created_at,
        "title": session.title,
        "status": status_value if status_value in {"ready", "processing", "error"} else "processing",
        "scenario_preset_id": getattr(session, "scenario_preset_id", None),
        "scenario_goal": (_safe_dict(getattr(session, "scenario_profile_json", None)).get("goal") if isinstance(getattr(session, "scenario_profile_json", None), dict) else None),
        "scenario_label_ru": {
            "scientific_lecture": "Научная лекция",
            "conference_talk": "Доклад на конференции",
            "pitch_sales": "Питч / продажа",
            "interview_self_intro": "Интервью / самопрезентация",
            "storytelling": "Сторителлинг",
            "kids_lesson": "Урок для детей",
        }.get(getattr(session, "scenario_preset_id", None)),
        "summary": {
            "wpm_avg": results["delivery"]["tempo"]["wpm_avg"]["value"],
            "wpm_category": results["delivery"]["tempo"].get("wpm_category"),
            "pause_ratio": results["delivery"]["pauses"]["pause_ratio"]["value"],
            "filler_count": results["word_choice"]["fillers"]["count"]["value"],
            "filler_per_min": results["word_choice"]["fillers"]["density"]["value"],
            "redundancy_score": results["word_choice"]["conciseness"]["redundancy_score"]["value"],
            "top_starter": (_safe_list(_safe_dict(_safe_dict(results["word_choice"].get("templates")).get("sentence_starters")).get("items"))[0].get("starter") if _safe_list(_safe_dict(_safe_dict(results["word_choice"].get("templates")).get("sentence_starters")).get("items")) else None),
            "weak_words_count": results["word_choice"]["weak_words"]["count"]["value"],
            "pitch_cv": results["voice"]["pitch"]["cv"]["value"],
            "rms_cv": results["voice"]["loudness"]["rms_cv"]["value"],
            "pitch_label": results["voice"]["pitch"].get("label"),
            "loudness_label": results["voice"]["loudness"].get("label"),
            "centering": results["visual"]["centering"]["value"],
            "stability": results["visual"]["stability"]["value"],
            "eye_contact": results["visual"].get("eye_contact", {}).get("value"),
        },
    }
