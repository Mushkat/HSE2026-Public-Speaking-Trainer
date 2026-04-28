from __future__ import annotations

from copy import deepcopy

SCENARIO_PRESET_LABELS_RU: dict[str, str] = {
    "scientific_lecture": "Научная лекция",
    "conference_talk": "Доклад на конференции",
    "pitch_sales": "Питч / продажа",
    "interview_self_intro": "Интервью / самопрезентация",
    "storytelling": "Сторителлинг",
    "kids_lesson": "Урок для детей",
}

DEFAULT_PRESET_ID = "conference_talk"
DEFAULT_STRUCTURED = {
    "goal": "inform",
    "audience": "general",
    "tone": "friendly",
}

WHY_TEXTS = {
    "wpm": "Темп влияет на понимание и вовлечённость аудитории.",
    "pause_percent": "Паузы помогают структуре; избыток делает речь рваной.",
    "fillers_per_min": "Паразиты снижают уверенность и ясность.",
    "redundancy_percent": "Избыточность увеличивает длину и снижает ясность.",
    "pitch_cv": "Интонация помогает удерживать внимание.",
    "eye_contact": "Зрительный контакт повышает доверие.",
}

SCENARIO_BASELINES: dict[str, dict] = {
    "scientific_lecture": {
        "norms": {
            "wpm": {"min": 120, "max": 160, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 12, "max": 28, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.2, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 30, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.10, "max": 0.30, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 3, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.35, "word_choice": 0.30, "voice": 0.20, "visual": 0.15},
    },
    "conference_talk": {
        "norms": {
            "wpm": {"min": 130, "max": 170, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 10, "max": 25, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.5, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 35, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.12, "max": 0.35, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 3, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.30, "word_choice": 0.25, "voice": 0.20, "visual": 0.25},
    },
    "pitch_sales": {
        "norms": {
            "wpm": {"min": 150, "max": 190, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 8, "max": 20, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.0, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 25, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.18, "max": 0.45, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 4, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.35, "word_choice": 0.30, "voice": 0.15, "visual": 0.20},
    },
    "interview_self_intro": {
        "norms": {
            "wpm": {"min": 130, "max": 175, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 10, "max": 25, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.2, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 30, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.12, "max": 0.40, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 4, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.25, "word_choice": 0.25, "voice": 0.20, "visual": 0.30},
    },
    "storytelling": {
        "norms": {
            "wpm": {"min": 120, "max": 165, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 12, "max": 32, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.5, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 40, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.18, "max": 0.50, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 3, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.25, "word_choice": 0.20, "voice": 0.25, "visual": 0.30},
    },
    "kids_lesson": {
        "norms": {
            "wpm": {"min": 105, "max": 145, "why": WHY_TEXTS["wpm"]},
            "pause_percent": {"min": 12, "max": 30, "why": WHY_TEXTS["pause_percent"]},
            "fillers_per_min": {"min": 0.0, "max": 1.2, "why": WHY_TEXTS["fillers_per_min"]},
            "redundancy_percent": {"min": 0, "max": 35, "why": WHY_TEXTS["redundancy_percent"]},
            "pitch_cv": {"min": 0.20, "max": 0.55, "why": WHY_TEXTS["pitch_cv"]},
            "eye_contact": {"min": 3, "max": 5, "why": WHY_TEXTS["eye_contact"]},
        },
        "weights": {"delivery": 0.30, "word_choice": 0.20, "voice": 0.30, "visual": 0.20},
    },
}


def get_preset_label_ru(preset_id: str | None) -> str | None:
    if not isinstance(preset_id, str):
        return None
    return SCENARIO_PRESET_LABELS_RU.get(preset_id)


def get_baseline_for_preset(preset_id: str) -> dict:
    baseline = SCENARIO_BASELINES.get(preset_id) or SCENARIO_BASELINES[DEFAULT_PRESET_ID]
    return deepcopy(baseline)
