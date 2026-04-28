from app.services.scenario_profile import classify_scenario_free_text, evaluate_goal_achievement
from app.services.llm_blocks import is_russian_text


class GoalLLMClient:
    def __init__(self):
        self.last_call_meta = {}

    def call_llm(self, **kwargs):
        return (
            '{"achieved":"yes","summary":"Цель в целом достигнута: подача соответствует задаче, а метрики остаются в рабочем коридоре по сценарию.","reasons":[{"metric":"wpm","verdict":"в норме","why":"Темп 150, норма 130-170, поэтому мысль звучит уверенно и без перегруза."},{"metric":"pause_percent","verdict":"в норме","why":"Паузы 20, норма 10-25, значит аудитория успевает усваивать тезисы."}],"actions":["Сохраняйте текущий темп и фиксируйте структуру выступления на карточках тезисов.","Делайте короткую паузу после каждого ключевого утверждения для лучшего акцента.","Проведите еще один прогон с записью, чтобы удержать стабильность метрик."]}',
            "stop",
            {},
        )


def test_goal_achievement_uses_llm_when_payload_valid(monkeypatch):
    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: GoalLLMClient())

    result = evaluate_goal_achievement(
        scenario_profile={
            "preset_id": "conference_talk",
            "goal": "inform",
            "norms": {
                "wpm": {"min": 130, "max": 170},
                "pause_percent": {"min": 10, "max": 25},
                "fillers_per_min": {"min": 0, "max": 1.5},
                "redundancy_percent": {"min": 0, "max": 35},
                "pitch_cv": {"min": 0.12, "max": 0.35},
                "eye_contact": {"min": 3, "max": 5},
            },
        },
        normalized_results={
            "delivery": {"tempo": {"wpm_avg": {"value": 150}}, "pauses": {"pause_ratio": {"value": 0.2}}},
            "word_choice": {"fillers": {"density": {"value": 1.0}}, "conciseness": {"redundancy_score": {"value": 22}}},
            "voice": {"pitch": {"cv": {"value": 0.2}}},
            "visual": {"eye_contact": {"value": 4}},
        },
        transcript_text="Краткий фрагмент выступления",
    )

    assert result["source"] == "llm"
    assert result["fallback_reason"] is None
    assert result["achieved"] == "yes"


def test_goal_achievement_loose_normalization_accepts_valid_core_fields(monkeypatch):
    class GoalLooseClient:
        def __init__(self):
            self.last_call_meta = {}

        def call_llm(self, **kwargs):
            return (
                '{"achieved":"partial","summary":"Цель достигнута частично: часть подачи убедительна, но есть отклонения от нормы в темпе и паузах.","reasons":[{"metric":"wpm","verdict":"выше нормы","why":"Темп 180, норма 130-170, поэтому часть аргументов звучит слишком быстро."},{"metric":"pause_percent","verdict":"ниже нормы","why":"Паузы 8, норма 10-25, поэтому ключевые переходы недостаточно отделены."}],"actions":["Снизьте темп в блоках с цифрами, чтобы слушатели успевали фиксировать выводы.","Добавляйте короткую паузу после каждого важного тезиса перед следующим аргументом.","Сделайте повторный прогон и проверьте, что темп и паузы вернулись в норму."]}',
                "stop",
                {},
            )

    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: GoalLooseClient())

    result = evaluate_goal_achievement(
        scenario_profile={"preset_id": "conference_talk", "goal": "inform", "norms": {
            "wpm": {"min": 130, "max": 170},
            "pause_percent": {"min": 10, "max": 25},
            "fillers_per_min": {"min": 0, "max": 1.5},
            "redundancy_percent": {"min": 0, "max": 35},
            "pitch_cv": {"min": 0.12, "max": 0.35},
            "eye_contact": {"min": 3, "max": 5},
        }},
        normalized_results={
            "delivery": {"tempo": {"wpm_avg": {"value": 180}}, "pauses": {"pause_ratio": {"value": 0.08}}},
            "word_choice": {"fillers": {"density": {"value": 1.0}}, "conciseness": {"redundancy_score": {"value": 22}}},
            "voice": {"pitch": {"cv": {"value": 0.2}}},
            "visual": {"eye_contact": {"value": 4}},
        },
        transcript_text="Фрагмент",
    )

    assert result["source"] == "llm"
    assert result["fallback_reason"] is None


def test_goal_achievement_english_actions_trigger_ru_repair_then_fallback(monkeypatch):
    class EnglishGoalClient:
        def __init__(self):
            self.last_call_meta = {}

        def call_llm(self, **kwargs):
            return (
                '{"summary":"Goal achieved for clients with clear structure.","reasons":[{"metric":"wpm","value":120,"norm":"130–170","text":"Tempo is below norm and audience loses attention."},{"metric":"pause_percent","value":26,"norm":"10–25","text":"Pauses are too frequent and break sentence flow."}],"actions":["Speak faster in the middle section.","Use fewer filler words.","Add stronger emphasis in conclusions."]}',
                "stop",
                {},
            )

    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: EnglishGoalClient())

    result = evaluate_goal_achievement(
        scenario_profile={
            "preset_id": "conference_talk",
            "goal": "inform",
            "audience": "clients",
            "norms": {
                "wpm": {"min": 130, "max": 170},
                "pause_percent": {"min": 10, "max": 25},
                "fillers_per_min": {"min": 0, "max": 1.5},
                "redundancy_percent": {"min": 0, "max": 35},
                "pitch_cv": {"min": 0.12, "max": 0.35},
                "eye_contact": {"min": 3, "max": 5},
            },
        },
        normalized_results={
            "delivery": {"tempo": {"wpm_avg": {"value": 120}}, "pauses": {"pause_ratio": {"value": 0.26}}},
            "word_choice": {"fillers": {"density": {"value": 1.0}}, "conciseness": {"redundancy_score": {"value": 22}}},
            "voice": {"pitch": {"cv": {"value": 0.2}}},
            "visual": {"eye_contact": {"value": 4}},
        },
        transcript_text="Фрагмент",
    )

    assert result["source"] == "fallback"
    assert result["fallback_reason"] == "not_russian"
    assert all(is_russian_text(item, min_cyrillic_chars=10) for item in result["actions"])


def test_classify_scenario_free_text_no_name_error_with_llm(monkeypatch):
    class ScenarioClient:
        def call_llm(self, **kwargs):
            return (
                '{"preset_id":"pitch_sales","goal":"sell","audience":"clients","tone":"energetic"}',
                "stop",
                {},
            )

    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: ScenarioClient())

    result, reason = classify_scenario_free_text("Питч для клиентов о новом продукте")
    assert reason is None
    assert result["preset_id"] == "pitch_sales"
    assert result["goal"] == "sell"


def test_classify_scenario_free_text_uses_keyword_fallback_without_llm(monkeypatch):
    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: False)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: None)

    result, reason = classify_scenario_free_text("Урок для детей в школе про безопасность")
    assert reason == "llm_unavailable"
    assert result["preset_id"] == "kids_lesson"
    assert result["goal"] == "teach"
