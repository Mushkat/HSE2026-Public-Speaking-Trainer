from __future__ import annotations

import uuid
from typing import Any
import logging
import re

from app.core.config import settings
from app.core.local_llm import LocalLLMOptions, get_local_llm_client, is_llm_enabled, parse_json_strict
from app.services.llm_blocks import generate_json_block, is_russian_text
from app.services.scenario_baselines import (
    DEFAULT_PRESET_ID,
    DEFAULT_STRUCTURED,
    SCENARIO_BASELINES,
    get_baseline_for_preset,
)

GOALS = {"inform", "teach", "persuade", "sell", "inspire", "entertain"}
AUDIENCES = {"colleagues", "clients", "students", "kids", "general"}
TONES = {"calm", "energetic", "friendly", "formal"}
PRESET_IDS = set(SCENARIO_BASELINES.keys())

DEFAULT_CLASSIFICATION = {
    "preset_id": DEFAULT_PRESET_ID,
    "goal": DEFAULT_STRUCTURED["goal"],
    "audience": DEFAULT_STRUCTURED["audience"],
    "tone": DEFAULT_STRUCTURED["tone"],
}

GOAL_FALLBACK_ACTIONS: dict[str, list[str]] = {
    "scientific_lecture": [
        "Снизьте темп на сложных терминах и делайте паузу перед определениями.",
        "Уберите слова-паразиты в ключевых тезисах.",
        "Добавьте голосовые акценты на выводах разделов.",
    ],
    "conference_talk": [
        "Синхронизируйте темп с паузами в переходах между блоками.",
        "Сократите повторы в каждом абзаце до одной ключевой мысли.",
        "Удерживайте зрительный контакт в начале и конце тезиса.",
    ],
    "pitch_sales": [
        "Держите высокий, но контролируемый темп в value-proposition.",
        "Сократите паразиты в блоке с цифрами и выгодами.",
        "Усильте интонацию на оффере и призыве к действию.",
    ],
    "interview_self_intro": [
        "Выравнивайте темп, чтобы не ускоряться на сложных вопросах.",
        "Сократите лишние повторения биографических деталей.",
        "Смотрите в камеру при ключевых достижениях.",
    ],
    "storytelling": [
        "Добавьте выразительные паузы перед кульминационными моментами.",
        "Уберите паразиты в эмоциональных переходах.",
        "Сделайте интонационный контраст между сценами.",
    ],
    "kids_lesson": [
        "Снизьте темп на новых терминах и проверьте понимание паузой.",
        "Упростите формулировки и уберите избыточные повторы.",
        "Используйте более яркую интонацию в объяснениях.",
    ],
}
GOAL_RU = {
    "teach": "обучить",
    "inform": "информировать",
    "persuade": "убедить",
    "sell": "продать",
    "inspire": "вдохновить",
    "entertain": "развлечь",
}
AUDIENCE_RU = {
    "students": "для студентов",
    "clients": "для клиентов",
    "kids": "для детей",
    "colleagues": "для коллег",
    "general": "для широкой аудитории",
}
GOAL_CRITERIA_MAP: dict[str, list[tuple[str, str, list[str]]]] = {
    "teach": [
        ("clarity", "Ясность", ["redundancy_percent", "fillers_per_min"]),
        ("tempo", "Темп", ["wpm"]),
        ("pause_structure", "Структура пауз", ["pause_percent"]),
        ("intonation", "Интонация для удержания внимания", ["pitch_cv"]),
        ("contact", "Контакт с аудиторией", ["eye_contact"]),
    ],
    "inform": [
        ("clarity", "Понятность", ["redundancy_percent", "fillers_per_min"]),
        ("tempo", "Темп", ["wpm"]),
        ("pauses", "Паузы", ["pause_percent"]),
        ("intonation", "Интонационная вариативность", ["pitch_cv"]),
    ],
    "persuade": [
        ("confidence", "Уверенность речи", ["fillers_per_min", "redundancy_percent"]),
        ("dynamics", "Динамика подачи", ["pitch_cv", "wpm"]),
        ("contact", "Контакт", ["eye_contact"]),
        ("rhythm", "Ритм/паузы", ["pause_percent"]),
    ],
    "sell": [
        ("energy", "Энергия и темп", ["wpm", "pitch_cv"]),
        ("confidence", "Уверенность", ["fillers_per_min"]),
        ("trust", "Контакт и доверие", ["eye_contact"]),
        ("conciseness", "Лаконичность аргументов", ["redundancy_percent"]),
    ],
    "inspire": [
        ("emotion", "Эмоциональная динамика", ["pitch_cv"]),
        ("rhythm", "Ритм пауз", ["pause_percent"]),
        ("contact", "Контакт", ["eye_contact"]),
        ("clarity", "Чёткость формулировок", ["redundancy_percent"]),
    ],
    "entertain": [
        ("dynamics", "Динамика", ["pitch_cv", "wpm"]),
        ("rhythm", "Ритм", ["pause_percent"]),
        ("contact", "Контакт", ["eye_contact"]),
        ("clarity", "Понятность", ["fillers_per_min", "redundancy_percent"]),
    ],
}
AUDIENCE_HINTS_RU = {
    "students": "для студентов это облегчает понимание",
    "clients": "для клиентов это повышает доверие и ясность выгоды",
    "kids": "для детей это помогает не терять нить",
    "colleagues": "для коллег это улучшает воспринимаемость аргументов",
    "general": "для широкой аудитории это делает речь понятнее",
}
logger = logging.getLogger(__name__)

PRESET_CLASSIFICATION_DEFAULTS: dict[str, dict[str, str]] = {
    "scientific_lecture": {"goal": "teach", "audience": "students", "tone": "formal"},
    "conference_talk": {"goal": "inform", "audience": "colleagues", "tone": "friendly"},
    "pitch_sales": {"goal": "sell", "audience": "clients", "tone": "energetic"},
    "interview_self_intro": {"goal": "persuade", "audience": "colleagues", "tone": "formal"},
    "storytelling": {"goal": "inspire", "audience": "general", "tone": "friendly"},
    "kids_lesson": {"goal": "teach", "audience": "kids", "tone": "energetic"},
}

PRESET_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("kids_lesson", ("дет", "школ", "урок", "класс", "ученик", "ребят", "kids", "children", "school")),
    ("pitch_sales", ("прод", "клиент", "сделк", "питч", "инвест", "startup", "sales", "pitch", "customer")),
    ("interview_self_intro", ("собесед", "hr", "рекрутер", "самопрез", "о себе", "interview", "resume")),
    ("scientific_lecture", ("науч", "лекц", "исслед", "статья", "универс", "science", "research", "thesis")),
    ("storytelling", ("истор", "сюжет", "геро", "эмоци", "story", "narrative")),
    ("conference_talk", ("доклад", "конферен", "митап", "выступ", "conference", "talk")),
]


def _is_valid_classification(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("preset_id"), str)
        and payload["preset_id"] in PRESET_IDS
        and payload.get("goal") in GOALS
        and payload.get("audience") in AUDIENCES
        and payload.get("tone") in TONES
    )


def _validated_structured(structured: dict[str, Any] | None) -> dict[str, str]:
    src = structured or {}
    return {
        "goal": str(src.get("goal") if src.get("goal") in GOALS else DEFAULT_STRUCTURED["goal"]),
        "audience": str(src.get("audience") if src.get("audience") in AUDIENCES else DEFAULT_STRUCTURED["audience"]),
        "tone": str(src.get("tone") if src.get("tone") in TONES else DEFAULT_STRUCTURED["tone"]),
    }


def _safe_preset_id(preset_id: str | None) -> str:
    if isinstance(preset_id, str) and preset_id in PRESET_IDS:
        return preset_id
    return DEFAULT_PRESET_ID


def build_scenario_profile(*, preset_id: str | None, structured: dict[str, Any] | None, user_hint: str = "") -> dict[str, Any]:
    resolved_preset_id = _safe_preset_id(preset_id)
    baseline = get_baseline_for_preset(resolved_preset_id)
    resolved = _validated_structured(structured)
    return {
        "version": 1,
        "preset_id": resolved_preset_id,
        "goal": resolved["goal"],
        "audience": resolved["audience"],
        "tone": resolved["tone"],
        "norms": baseline["norms"],
        "weights": baseline["weights"],
        "user_hint": " ".join((user_hint or "").strip().split())[:240],
    }


def classify_scenario_free_text(free_text: str) -> tuple[dict[str, str], str | None]:
    fallback = _heuristic_classification(free_text)
    client = get_local_llm_client()
    if not free_text.strip() or not is_llm_enabled() or not client:
        return fallback, "llm_unavailable"

    system_prompt = "Ты — помощник по выбору сценария выступления. Только русский. Верни строго JSON."
    user_prompt = (
        "Выбери preset_id из:\n"
        "scientific_lecture, conference_talk, pitch_sales, interview_self_intro, storytelling, kids_lesson.\n"
        "И выбери:\n"
        "goal: inform|teach|persuade|sell|inspire|entertain\n"
        "audience: colleagues|clients|students|kids|general\n"
        "tone: calm|energetic|friendly|formal\n"
        "Верни строго JSON:\n"
        "{ \"preset_id\":\"...\",\"goal\":\"...\",\"audience\":\"...\",\"tone\":\"...\" }\n"
        f"Описание:\n<<<{free_text}>>>"
    )

    request_id = f"scenario-autopick-{uuid.uuid4().hex[:10]}"
    options = LocalLLMOptions(max_tokens=140, temperature=0.2)

    try:
        raw_text, _, _ = client.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            request_id=request_id,
            session_id="scenario_autopick",
        )
        parsed = parse_json_strict(raw_text)
        if isinstance(parsed, dict) and _is_valid_classification(parsed):
            return {
                "preset_id": parsed["preset_id"],
                "goal": parsed["goal"],
                "audience": parsed["audience"],
                "tone": parsed["tone"],
            }, None

        repair_text, _, _ = client.call_llm(
            system_prompt=system_prompt,
            user_prompt=f"{user_prompt}\n\nВерни только JSON без текста",
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            request_id=f"{request_id}-repair",
            session_id="scenario_autopick",
        )
        repaired = parse_json_strict(repair_text)
        if isinstance(repaired, dict) and _is_valid_classification(repaired):
            return {
                "preset_id": repaired["preset_id"],
                "goal": repaired["goal"],
                "audience": repaired["audience"],
                "tone": repaired["tone"],
            }, None
    except Exception:
        return fallback, "llm_error"

    return fallback, "invalid_json"


def _heuristic_classification(free_text: str) -> dict[str, str]:
    text = (free_text or "").lower()
    for preset_id, keywords in PRESET_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return {"preset_id": preset_id, **PRESET_CLASSIFICATION_DEFAULTS[preset_id]}
    return dict(DEFAULT_CLASSIFICATION)


def evaluate_goal_achievement(
    *,
    scenario_profile: dict[str, Any] | None,
    normalized_results: dict[str, Any],
    transcript_text: str | None,
) -> dict[str, Any]:
    profile = scenario_profile if isinstance(scenario_profile, dict) else {}
    preset_id = _safe_preset_id(profile.get("preset_id") if isinstance(profile.get("preset_id"), str) else None)
    goal = profile.get("goal") if isinstance(profile.get("goal"), str) else DEFAULT_STRUCTURED["goal"]
    audience = profile.get("audience") if isinstance(profile.get("audience"), str) else DEFAULT_STRUCTURED["audience"]
    tone = profile.get("tone") if isinstance(profile.get("tone"), str) else DEFAULT_STRUCTURED["tone"]
    norms = profile.get("norms") if isinstance(profile.get("norms"), dict) else get_baseline_for_preset(preset_id)["norms"]

    delivery = normalized_results.get("delivery") if isinstance(normalized_results.get("delivery"), dict) else {}
    word_choice = normalized_results.get("word_choice") if isinstance(normalized_results.get("word_choice"), dict) else {}
    voice = normalized_results.get("voice") if isinstance(normalized_results.get("voice"), dict) else {}
    visual = normalized_results.get("visual") if isinstance(normalized_results.get("visual"), dict) else {}

    wpm = (((delivery.get("tempo") or {}).get("wpm_avg") or {}).get("value"))
    pause_ratio = (((delivery.get("pauses") or {}).get("pause_ratio") or {}).get("value"))
    pause_percent = round(float(pause_ratio) * 100, 2) if isinstance(pause_ratio, (int, float)) else None
    fillers_per_min = (((word_choice.get("fillers") or {}).get("density") or {}).get("value"))
    redundancy_percent = (((word_choice.get("conciseness") or {}).get("redundancy_score") or {}).get("value"))
    pitch_cv = (((voice.get("pitch") or {}).get("cv") or {}).get("value"))
    eye_contact = (((visual.get("eye_contact") or {}).get("value")))

    excerpt = _best_excerpt(transcript_text, max_chars=800)

    if not is_llm_enabled():
        return _goal_fallback(preset_id, reason="llm_disabled")

    client = get_local_llm_client()
    if client is None:
        return _goal_fallback(preset_id, reason="llm_unreachable")
    assert client is not None
    preset_label_ru = str(get_baseline_for_preset(preset_id).get("label_ru") or preset_id)
    metrics_map = {
        "wpm": wpm,
        "pause_percent": pause_percent,
        "fillers_per_min": fillers_per_min,
        "redundancy_percent": redundancy_percent,
        "pitch_cv": pitch_cv,
        "eye_contact": eye_contact,
    }
    criteria = _compute_goal_criteria(goal=goal, metrics=metrics_map, norms=norms, weights=profile.get("weights") if isinstance(profile.get("weights"), dict) else {})
    criteria = build_goal_criteria_explanations(criteria, metrics_map, norms, {"goal": goal, "audience": audience})
    status = _goal_status_from_criteria(criteria)
    goal_ru = GOAL_RU.get(goal, "информировать")
    audience_ru = AUDIENCE_RU.get(audience, "для широкой аудитории")
    criteria_lines = "\n".join(
        f"- {item['title']}: {item['score']}/100 ({item['verdict']}); метрики: {', '.join(item['metrics'])}"
        for item in criteria
    )
    system_prompt = "Ты — коуч по публичным выступлениям. Пиши только по-русски. Верни строго JSON. Не выдумывай факты — опирайся на метрики и сценарий."
    user_prompt = (
        "Сценарий:\n"
        f"preset={preset_label_ru} ({preset_id})\n"
        f"цель={goal_ru} аудитория={audience_ru} тон={tone}\n\n"
        "Нормы для сценария:\n"
        f"WPM {norms['wpm']['min']}-{norms['wpm']['max']}\n"
        f"Паузы {norms['pause_percent']['min']}-{norms['pause_percent']['max']} %\n"
        f"Паразиты {norms['fillers_per_min']['min']}-{norms['fillers_per_min']['max']} /мин\n"
        f"Избыточность {norms['redundancy_percent']['min']}-{norms['redundancy_percent']['max']} %\n"
        f"Интонация pitch_cv {norms['pitch_cv']['min']}-{norms['pitch_cv']['max']}\n"
        f"Зрительный контакт {norms['eye_contact']['min']}-{norms['eye_contact']['max']} /5\n\n"
        "Фактические метрики:\n"
        f"WPM={wpm}\n"
        f"Паузы={pause_percent}%\n"
        f"Паразиты={fillers_per_min}/мин\n"
        f"Избыточность={redundancy_percent}%\n"
        f"pitch_cv={pitch_cv}\n"
        f"зрительный контакт={eye_contact}/5\n\n"
        "Оценка критериев (0–100, это факты):\n"
        f"{criteria_lines}\n\n"
        "Фрагмент речи:\n"
        f"<<<{excerpt}>>>\n\n"
        "Сгенерируй:\n"
        "1) summary — 1 предложение (80–180 символов), обязательно упомяни цель и аудиторию.\n"
        "2) reasons — 2–4 пункта, каждый пункт ОБЯЗАТЕЛЬНО содержит число метрики, диапазон нормы и связь с целью/аудиторией.\n"
        "3) actions — 3–5 действий, конкретные улучшения, привязанные к 1 метрике или 1 критерию.\n\n"
        "Верни строго JSON:\n"
        "{\n"
        "  \"summary\":\"...\",\n"
        "  \"reasons\":[{\"metric\":\"wpm\",\"value\":139,\"norm\":\"150–190\",\"text\":\"...\"}],\n"
        "  \"actions\":[\"...\"]\n"
        "}"
    )
    request_id = f"goal-eval-{uuid.uuid4().hex[:10]}"
    goal_max_tokens = min(max(180, int(settings.local_llm_max_tokens)), 220)
    llm_result = generate_json_block(
        block_name="goal",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema_validator=lambda payload: _has_goal_text_core_fields(payload),
        max_tokens=goal_max_tokens,
        temperature=0.2,
        request_id=request_id,
        session_id="goal_eval",
        client=client,
        llm_enabled=True,
    )
    llm_payload = llm_result.get("payload") if llm_result.get("ok") and isinstance(llm_result.get("payload"), dict) else None
    if llm_payload and not is_russian_text(
        " ".join(
            [
                str(llm_payload.get("summary") or ""),
                " ".join(str(item.get("text") or "") for item in llm_payload.get("reasons", []) if isinstance(item, dict)),
                " ".join(str(item) for item in llm_payload.get("actions", []) if isinstance(item, str)),
            ]
        )
    ):
        ru_retry = generate_json_block(
            block_name="goal",
            system_prompt="Только русский. Верни только JSON. Никакого английского.",
            user_prompt=f"{user_prompt}\n\nПерепиши результат полностью по-русски, сохрани структуру JSON. Без англицизмов.",
            schema_validator=lambda payload: _has_goal_text_core_fields(payload),
            max_tokens=goal_max_tokens,
            temperature=0.2,
            request_id=f"{request_id}-repair-ru",
            session_id="goal_eval",
            client=client,
            llm_enabled=True,
        )
        if ru_retry.get("ok") and isinstance(ru_retry.get("payload"), dict):
            llm_payload = ru_retry.get("payload")
            llm_result = ru_retry
        else:
            llm_payload = None
            llm_result = ru_retry
    if llm_payload and not _valid_goal_text_payload(llm_payload, goal_ru=goal_ru, audience_ru=audience_ru):
        retry_prompt = f"{user_prompt}\n\nВерни только JSON. Условия: summary 80-180, reasons 2-4 с value+norm, actions 3-5 по 70-140 символов."
        retry_result = generate_json_block(
            block_name="goal",
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            schema_validator=lambda payload: _has_goal_text_core_fields(payload),
            max_tokens=goal_max_tokens,
            temperature=0.2,
            request_id=f"{request_id}-repair-schema",
            session_id="goal_eval",
            client=client,
            llm_enabled=True,
        )
        if retry_result.get("ok") and isinstance(retry_result.get("payload"), dict):
            llm_payload = retry_result.get("payload")
            llm_result = retry_result
    if isinstance(llm_payload, dict):
        normalized_payload = _coerce_goal_text_payload(
            llm_payload,
            goal_ru=goal_ru,
            audience_ru=audience_ru,
            norms=norms,
            metrics=metrics_map,
            criteria=criteria,
        )
        if normalized_payload and _valid_goal_text_payload(normalized_payload, goal_ru=goal_ru, audience_ru=audience_ru):
            logger.warning("LLM_BLOCK=goal source=llm reason=llm session=goal_eval req=%s latency=%s", llm_result.get("request_id"), llm_result.get("llm_latency_ms") if llm_result.get("llm_latency_ms") is not None else "na")
            return {
                "status": status,
                "achieved": _status_to_achieved(status),
                "criteria": criteria,
                **normalized_payload,
                "source": "llm",
                "fallback_reason": None,
                "request_id": llm_result.get("request_id"),
                "llm_latency_ms": llm_result.get("llm_latency_ms"),
            }

    reason = str(llm_result.get("reason") or "schema_invalid")
    if llm_result.get("ok") and isinstance(llm_result.get("payload"), dict):
        payload = llm_result.get("payload") or {}
        ru_probe = " ".join(
            [
                str(payload.get("summary") or ""),
                " ".join(str(item.get("text") or "") for item in payload.get("reasons", []) if isinstance(item, dict)),
                " ".join(str(item) for item in payload.get("actions", []) if isinstance(item, str)),
            ]
        )
        if not is_russian_text(ru_probe):
            reason = "not_russian"
    logger.warning(
        "goal fallback diagnostic",
        extra={"reason": reason, "request_id": llm_result.get("request_id"), "snippet": llm_result.get("content_snippet", "")},
    )
    return _goal_fallback(
        preset_id,
        reason=reason,
        request_id=llm_result.get("request_id") if isinstance(llm_result.get("request_id"), str) else request_id,
        norms=norms,
        metrics=metrics_map,
        goal=goal,
        audience=audience,
        criteria=criteria,
        status=status,
    )


def _valid_goal_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("achieved") not in {"yes", "partial", "no"}:
        return False
    summary = str(payload.get("summary") or "").strip()
    if len(summary) < 40 or len(summary) > 160:
        return False
    reasons = payload.get("reasons")
    actions = payload.get("actions")
    if not isinstance(reasons, list) or not (2 <= len(reasons) <= 4):
        return False
    if not isinstance(actions, list) or not (3 <= len(actions) <= 5):
        return False
    if any(not isinstance(item, dict) for item in reasons):
        return False
    for item in reasons:
        if not isinstance(item.get("metric"), str) or not isinstance(item.get("verdict"), str) or not isinstance(item.get("why"), str):
            return False
        why = str(item.get("why")).strip()
        if not (30 <= len(why) <= 170):
            return False
        if not any(ch.isdigit() for ch in why):
            return False
        if "норма" not in why.lower() and re.search(r"\d+\s*[–-]\s*\d+", why) is None:
            return False
    if any(not isinstance(action, str) or not (20 <= len(action.strip()) <= 120) for action in actions):
        return False
    russian_probe = f"{payload.get('summary', '')} {' '.join(actions)}"
    return is_russian_text(russian_probe)


def _has_goal_text_core_fields(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        isinstance(payload.get("summary"), str)
        and isinstance(payload.get("reasons"), list)
        and isinstance(payload.get("actions"), list)
    )


def _valid_goal_text_payload(payload: dict[str, Any], *, goal_ru: str, audience_ru: str) -> bool:
    if not _has_goal_text_core_fields(payload):
        return False
    summary = str(payload.get("summary") or "").strip()
    if not (80 <= len(summary) <= 180):
        return False
    if goal_ru not in summary.lower() or audience_ru not in summary.lower():
        return False
    reasons = payload.get("reasons", [])
    actions = payload.get("actions", [])
    if not isinstance(reasons, list) or not (2 <= len(reasons) <= 4):
        return False
    if not isinstance(actions, list) or not (3 <= len(actions) <= 5):
        return False
    for item in reasons:
        if not isinstance(item, dict):
            return False
        text = str(item.get("text") or "").strip()
        if not text or re.search(r"\d", text) is None or re.search(r"\d+\s*[–-]\s*\d+", str(item.get("norm") or text)) is None:
            return False
    for action in actions:
        if not isinstance(action, str) or not (70 <= len(action.strip()) <= 140):
            return False
    return is_russian_text(f"{summary} {' '.join(str(action) for action in actions)}")


def _coerce_goal_text_payload(
    payload: dict[str, Any],
    *,
    goal_ru: str,
    audience_ru: str,
    norms: dict[str, Any],
    metrics: dict[str, Any],
    criteria: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _has_goal_text_core_fields(payload):
        return None
    summary = str(payload.get("summary") or "").strip()
    if goal_ru not in summary.lower() or audience_ru not in summary.lower():
        lead = "достигнута" if sum(item.get("score", 0) for item in criteria) / max(1, len(criteria)) >= 75 else "достигнута частично"
        summary = f"Цель «{goal_ru}» {lead} {audience_ru}: метрики показывают смешанный результат, поэтому важны точечные улучшения подачи."
    summary = summary[:180]
    reasons: list[dict[str, Any]] = []
    for item in payload.get("reasons", []):
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        if metric not in {"wpm", "pause_percent", "fillers_per_min", "redundancy_percent", "pitch_cv", "eye_contact"}:
            continue
        text = str(item.get("text") or item.get("why") or "").strip()
        value = metrics.get(metric)
        norm = norms.get(metric) if isinstance(norms.get(metric), dict) else {}
        norm_text = str(item.get("norm") or f"{norm.get('min')}–{norm.get('max')}")
        if re.search(r"\d+\s*[–-]\s*\d+", norm_text) is None:
            norm_text = f"{norm.get('min')}–{norm.get('max')}"
        if re.search(r"\d", text) is None:
            text = f"Метрика {metric}={value} при норме {norm_text} влияет на достижение цели {goal_ru} {audience_ru}."
        reasons.append({"metric": metric, "value": value, "norm": norm_text, "text": text[:220]})
        if len(reasons) >= 4:
            break
    if len(reasons) < 2:
        reasons = _fallback_goal_reasons(norms=norms, metrics=metrics, goal_ru=goal_ru, audience_ru=audience_ru)
    actions = [str(item).strip() for item in payload.get("actions", []) if isinstance(item, str) and str(item).strip()]
    cleaned_actions: list[str] = []
    for action in actions:
        if len(action) < 70:
            action = f"{action}. Сфокусируйтесь на одной метрике в следующем прогоне и сравните результат с нормой сценария."
        cleaned_actions.append(action[:140])
        if len(cleaned_actions) >= 5:
            break
    if len(cleaned_actions) < 3 or not is_russian_text(" ".join(cleaned_actions)):
        cleaned_actions = [item[:140] for item in (GOAL_FALLBACK_ACTIONS.get(DEFAULT_PRESET_ID) or [])[:3]]
    normalized = {
        "summary": summary,
        "reasons": reasons[:4],
        "actions": cleaned_actions[:5],
    }
    return normalized


def _normalize_goal_payload_loose(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    achieved = payload.get("achieved")
    summary = payload.get("summary")
    reasons = payload.get("reasons")
    actions = payload.get("actions")
    if achieved not in {"yes", "partial", "no"} or not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(reasons, list) or not isinstance(actions, list):
        return None
    clean_reasons: list[dict[str, str]] = []
    for item in reasons:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip() or "wpm"
        verdict = str(item.get("verdict") or "").strip()
        why = str(item.get("why") or "").strip()
        if verdict and why:
            clean_reasons.append({"metric": metric, "verdict": verdict[:120], "why": why[:220]})
        if len(clean_reasons) >= 4:
            break
    clean_actions = [str(action).strip()[:140] for action in actions if isinstance(action, str) and str(action).strip()]
    clean_actions = list(dict.fromkeys(clean_actions))[:5]
    if len(clean_reasons) < 2:
        return None
    if len(clean_actions) < 3:
        return None
    return {
        "achieved": achieved,
        "summary": summary.strip()[:220],
        "reasons": clean_reasons[:4],
        "actions": clean_actions[:5],
    }


def _goal_fallback(
    preset_id: str,
    *,
    reason: str,
    request_id: str | None = None,
    norms: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    goal: str = "inform",
    audience: str = "general",
    criteria: list[dict[str, Any]] | None = None,
    status: str = "partial",
) -> dict[str, Any]:
    actions = GOAL_FALLBACK_ACTIONS.get(preset_id) or GOAL_FALLBACK_ACTIONS[DEFAULT_PRESET_ID]
    safe_reason = reason if reason in {
        "llm_disabled", "llm_unreachable", "timeout", "http_error", "empty_content",
        "json_extract_failed", "json_parse_failed", "schema_invalid", "filtered_all_items",
        "low_quality", "persistence_overwritten", "ui_mapping_wrong", "not_russian",
    } else "low_quality"
    logger.warning("LLM_BLOCK=goal source=fallback reason=%s session=goal_eval req=%s latency=na", safe_reason, request_id or "na")
    goal_ru = GOAL_RU.get(goal, "информировать")
    audience_ru = AUDIENCE_RU.get(audience, "для широкой аудитории")
    top_reasons = _fallback_goal_reasons(norms=norms or {}, metrics=metrics or {}, goal_ru=goal_ru, audience_ru=audience_ru)
    return {
        "status": status if status in {"achieved", "partial", "not_achieved"} else "partial",
        "achieved": _status_to_achieved(status if status in {"achieved", "partial", "not_achieved"} else "partial"),
        "summary": f"Цель «{goal_ru}» для формата {AUDIENCE_RU.get(audience, audience_ru)} оценить сложно: часть метрик в норме, часть требует улучшений.",
        "criteria": criteria or [],
        "reasons": top_reasons,
        "actions": actions[:5],
        "source": "fallback",
        "fallback_reason": safe_reason,
        "request_id": request_id,
        "llm_latency_ms": None,
    }


def _best_excerpt(transcript_text: str | None, *, max_chars: int = 800) -> str:
    text = " ".join((transcript_text or "").split())
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    chunk = max(120, max_chars // 3 - 4)
    first = text[:chunk].strip()
    mid_start = max(0, len(text) // 2 - chunk // 2)
    middle = text[mid_start : mid_start + chunk].strip()
    last = text[-chunk:].strip()
    return " … ".join([first, middle, last])[:max_chars]


def _status_to_achieved(status: str) -> str:
    return {"achieved": "yes", "partial": "partial", "not_achieved": "no"}.get(status, "partial")


def _score_metric(metric: str, value: float | int | None, norms: dict[str, Any]) -> int:
    metric_norm = norms.get(metric) if isinstance(norms.get(metric), dict) else {}
    min_v = metric_norm.get("min")
    max_v = metric_norm.get("max")
    if not isinstance(value, (int, float)) or not isinstance(min_v, (int, float)) or not isinstance(max_v, (int, float)):
        return 55
    if min_v <= value <= max_v:
        return 100
    distance = min_v - value if value < min_v else value - max_v
    span = max(0.1, float(max_v - min_v))
    penalty = min(75.0, (distance / span) * 110.0)
    return max(0, int(round(100.0 - penalty)))


def _criterion_verdict(score: int) -> str:
    if score >= 80:
        return "Критерий в норме для сценария."
    if score >= 60:
        return "Есть отклонения, но контроль сохраняется."
    if score >= 40:
        return "Заметное отклонение влияет на цель."
    return "Критерий проседает и мешает цели."


def _compute_goal_criteria(*, goal: str, metrics: dict[str, Any], norms: dict[str, Any], weights: dict[str, Any]) -> list[dict[str, Any]]:
    templates = GOAL_CRITERIA_MAP.get(goal) or GOAL_CRITERIA_MAP["inform"]
    items: list[dict[str, Any]] = []
    for key, title, metric_keys in templates:
        metric_scores = [_score_metric(metric_key, metrics.get(metric_key), norms) for metric_key in metric_keys]
        base_score = int(round(sum(metric_scores) / max(1, len(metric_scores))))
        weight = float((weights.get(key) if isinstance(weights, dict) and isinstance(weights.get(key), (int, float)) else 1.0))
        adjusted = int(max(0, min(100, round(base_score * min(1.15, max(0.85, weight))))))
        items.append({
            "key": key,
            "title": title,
            "score": adjusted,
            "verdict": _criterion_verdict(adjusted),
            "metrics": metric_keys,
        })
    return items


def _goal_status_from_criteria(criteria: list[dict[str, Any]]) -> str:
    if not criteria:
        return "partial"
    avg = sum(int(item.get("score") or 0) for item in criteria) / max(1, len(criteria))
    if avg >= 75:
        return "achieved"
    if avg >= 45:
        return "partial"
    return "not_achieved"


def _fallback_goal_reasons(*, norms: dict[str, Any], metrics: dict[str, Any], goal_ru: str, audience_ru: str) -> list[dict[str, Any]]:
    ranked: list[tuple[float, str, str]] = []
    for metric in ("wpm", "pause_percent", "fillers_per_min", "redundancy_percent", "pitch_cv", "eye_contact"):
        value = metrics.get(metric)
        metric_norm = norms.get(metric) if isinstance(norms.get(metric), dict) else {}
        min_v = metric_norm.get("min")
        max_v = metric_norm.get("max")
        if not isinstance(value, (int, float)) or not isinstance(min_v, (int, float)) or not isinstance(max_v, (int, float)):
            continue
        if value < min_v:
            dev = float(min_v - value)
            verdict = "ниже нормы"
        elif value > max_v:
            dev = float(value - max_v)
            verdict = "выше нормы"
        else:
            dev = 0.0
            verdict = "в норме"
        ranked.append((dev, metric, verdict))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = ranked[:2] if ranked else [(0.0, "wpm", "оценка ограничена"), (0.0, "pause_percent", "оценка ограничена")]
    items: list[dict[str, Any]] = []
    for _, metric, verdict in chosen:
        value = metrics.get(metric)
        norm = norms.get(metric) if isinstance(norms.get(metric), dict) else {}
        norm_text = f"{norm.get('min')}–{norm.get('max')}"
        items.append(
            {
                "metric": metric,
                "value": value,
                "norm": norm_text,
                "text": f"Метрика {metric}: значение {value}, норма {norm_text}. Для цели «{goal_ru}» {audience_ru} это снижает качество подачи.",
            }
        )
    return items[:2]


def build_goal_criteria_explanations(
    criteria_scores: list[dict[str, Any]],
    metrics: dict[str, Any],
    norms: dict[str, Any],
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    _ = metrics, norms
    audience_key = str(scenario.get("audience") or "general")
    audience_ru = AUDIENCE_RU.get(audience_key, "для широкой аудитории")
    audience_hint = AUDIENCE_HINTS_RU.get(audience_key, AUDIENCE_HINTS_RU["general"])
    goal_ru = GOAL_RU.get(str(scenario.get("goal") or "inform"), "информировать")
    enriched: list[dict[str, Any]] = []
    for item in criteria_scores:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        score = int(item.get("score") or 0)
        tone = "high" if score >= 85 else "mid" if score >= 60 else "low"
        explanation = _criteria_explanation_by_key(
            key=key,
            tone=tone,
            audience_ru=audience_ru,
            audience_hint=audience_hint,
            goal_ru=goal_ru,
        )
        enriched.append({**item, "explanation": explanation[:160]})
    return enriched


def _criteria_explanation_by_key(*, key: str, tone: str, audience_ru: str, audience_hint: str, goal_ru: str) -> str:
    audience_noun = audience_ru.replace("для ", "")
    if key in {"clarity", "confidence", "conciseness"}:
        if tone == "high":
            return f"Формулировки понятные: паразитов мало, избыточность невысокая — {audience_hint}."
        if tone == "mid":
            return f"В целом понятно, но местами есть лишние слова/повторы — для {audience_noun} это снижает чёткость."
        return f"Смысл теряется из-за повторов или лишних слов — {audience_hint}."
    if key in {"tempo", "dynamics", "energy"}:
        if tone == "high":
            return f"Темп подходит сценарию и помогает держать внимание {audience_noun}."
        if tone == "mid":
            return "Темп близок к норме, но на ключевых тезисах можно сделать подачу чуть динамичнее."
        return f"Темп ниже нормы: часть тезисов звучит растянуто и теряет динамику для {audience_noun}."
    if key in {"pause_structure", "pauses", "rhythm"}:
        if tone == "high":
            return "Паузы естественные: они помогают структуре и дают слушателю время осмыслить мысль."
        if tone == "mid":
            return "Паузы в целом уместны, но иногда ритм можно сделать ровнее."
        return "Паузы мешают ритму: либо слишком частые, либо их не хватает для структуры."
    if key in {"intonation", "emotion"}:
        if tone == "high":
            return "Интонация достаточно вариативна: ключевые фразы выделяются, речь не звучит монотонно."
        if tone == "mid":
            return "Интонация в целом нормальная, но на выводах можно добавлять контраст."
        return "Интонация слишком ровная: важные мысли звучат одинаково и хуже запоминаются."
    if key in {"contact", "trust"}:
        if tone == "high":
            return f"Зрительный контакт поддерживает вовлечённость: для {goal_ru} это повышает доверие."
        if tone == "mid":
            return "Контакт в целом есть, но на ключевых тезисах лучше чаще смотреть в камеру."
        return "Контакт слабый: без него сложнее удерживать внимание и доверие аудитории."
    return "Показатель в рабочем диапазоне, но для лучшего эффекта стоит точечно усилить подачу."


def _map_failure_reason(reason: str) -> str:
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
    if "http" in normalized or "status" in normalized:
        return "http_error"
    return "http_error"
