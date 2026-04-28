from app.services.coaching_builder import (
    _build_questions_retry_prompt,
    _build_questions_user_prompt,
    _build_coaching_brief,
    _contextual_fallback_questions,
    _filter_questions,
    _generate_audience_questions,
    _generate_summary_keywords,
    get_last_coaching_outcomes,
    build_coaching_payload,
    extract_main_idea,
)


def test_coaching_builder_returns_all_sections_in_russian():
    payload = build_coaching_payload(
        results={
            "delivery": {
                "tempo": {"wpm_category": "above"},
                "pauses": {"pause_ratio": {"value": 0.35}, "events": [{"start": 12.0, "end": 13.5}]},
            },
            "word_choice": {
                "fillers": {"count": {"value": 10}, "density": {"value": 3.4}, "events": [{"start": 14.0}]},
                "templates": {"sentence_starters": {"items": [{"starter": "я считаю", "ratio": 0.44, "count": 5, "timecodes": [{"t": 10.0}]}]}},
                "repetitions": {"top_words": [{"word": "важно", "count": 6, "timecodes": [{"t": 22.0}]}], "top_phrases": []},
                "weak_words": {"count": {"value": 7}},
                "conciseness": {"redundancy_score": {"value": 0.58}},
            },
            "voice": {
                "pitch": {"label": "монотонно"},
                "loudness": {"label": "сильные перепады"},
            },
            "visual": {"centering": {"value": 50}, "stability": {"value": 48}},
        },
        transcript_text="Сегодня поговорим про стратегию продукта и план внедрения. Нужны примеры и риски.",
        segments=[
            {"idx": 0, "start_sec": 0, "end_sec": 14, "text": "Сегодня расскажу, как команда меняет стратегию продукта и зачем это нужно клиентам.", "bullets_rewrite": ["Цели и стратегия на квартал."]},
            {"idx": 1, "start_sec": 14, "end_sec": 28, "text": "Разберем шаги внедрения, ограничения и ключевые риски для команды продаж."},
            {"idx": 2, "start_sec": 28, "end_sec": 40, "text": "В конце дам следующий шаг, чтобы план можно было применить сразу после выступления."},
        ],
    )

    assert payload["questions"]["title"] == "Вопросы аудитории"
    assert 3 <= len(payload["questions"]["items"]) <= 5
    assert all("?" == item[-1] for item in payload["questions"]["items"])
    assert all(any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in item) for item in payload["questions"]["items"])
    assert 3 <= len(payload["summary"]["bullets"]) <= 5
    assert isinstance(payload["summary"]["keywords"], list)


def test_summary_keywords_fallback_is_deterministic_when_llm_disabled(monkeypatch):
    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: False)
    payload = build_coaching_payload(
        results={"delivery": {}, "word_choice": {}, "voice": {}, "visual": {}},
        transcript_text="Презентация продукта, стратегия роста, команда продаж, риски внедрения и план запуска.",
        segments=[{"text": "Презентация продукта и стратегия роста для команды продаж."}],
    )
    assert payload["summary"]["keywords"]
    assert payload["summary"]["keywords"] == build_coaching_payload(
        results={"delivery": {}, "word_choice": {}, "voice": {}, "visual": {}},
        transcript_text="Презентация продукта, стратегия роста, команда продаж, риски внедрения и план запуска.",
        segments=[{"text": "Презентация продукта и стратегия роста для команды продаж."}],
    )["summary"]["keywords"]


def test_extract_main_idea_prefers_meaningful_early_sentence():
    segments = [
        {"text": "Ну, в общем, сегодня расскажу о проекте."},
        {"text": "Наша главная задача - сократить время ответа клиенту до 15 минут без потери качества сервиса."},
        {"text": "Дальше покажу детали внедрения и роли команды."},
    ]

    main_idea = extract_main_idea(segments)

    assert "сократить время ответа клиенту до 15 минут" in main_idea.lower()
    assert len(main_idea) <= 180
    assert not main_idea.lower().startswith("ну")


def test_build_coaching_brief_returns_main_idea_and_keywords():
    segments = [
        {"text": "Мы запускаем новый процесс онбординга для менеджеров по продажам."},
        {"text": "Главная цель - сократить время до первой сделки и убрать лишние согласования."},
        {"text": "Для этого мы меняем сценарий обучения и правила передачи лида."},
    ]

    brief = _build_coaching_brief(None, segments)

    assert brief["main_idea"]
    assert brief["excerpt"]
    assert 1 <= len(brief["key_terms"]) <= 8


def test_fallback_questions_match_exact_new_list():
    items = _contextual_fallback_questions(desired_count=4)

    assert items == [
        "Можете привести один простой пример, который лучше всего показывает вашу главную мысль?",
        "Какие ограничения у этой идеи и в каких случаях она может не сработать?",
        "Что вы советуете сделать первым шагом после выступления, чтобы применить это на практике?",
        "Почему это важно именно сейчас, и что изменится, если следовать вашему совету?",
    ]
    assert _contextual_fallback_questions(desired_count=5)[4] == "Какую одну мысль вы хотите, чтобы люди точно запомнили, и почему?"


def test_questions_filter_removes_duplicates_short_bad_year_and_english():
    source_text = "Мы обсуждаем стратегию продукта, этапы внедрения, риски проекта и примеры из пилота 2024 года."
    keywords = ["стратегию", "проекта", "внедрения", "риски"]
    raw_items = [
        "Какие этапы внедрения вы считаете самыми важными для проекта?",
        "Какие этапы внедрения вы считаете самыми важными для проекта?",
        "Почему?",
        "Какие шаги вы планируете в 2025 году для масштабирования проекта?",
        "What risk matters most for the rollout?",
        "Какие риски проекта вы считаете критичными и как их снижать на этапе внедрения?",
    ]

    filtered, reasons, rejected = _filter_questions(raw_items, source_text, keywords, main_idea="Стратегия продукта и этапы внедрения")

    assert len(filtered) >= 1
    assert all(item.endswith("?") for item in filtered)
    assert "too_short" in reasons
    assert "hallucinated_number" in reasons or "noise_pattern" in reasons
    assert "duplicate" in reasons
    assert "non_russian" in reasons
    assert any(item["reason"] in {"duplicate", "too_short", "hallucinated_number", "noise_pattern", "non_russian"} for item in rejected)


def test_questions_prompt_includes_transcript_excerpt_and_constraints():
    prompt = _build_questions_user_prompt(
        main_idea="Команда сокращает путь клиента до первой сделки.",
        summary_bullets=["Новый онбординг убирает лишние согласования."],
        key_terms=["онбординг", "сделки"],
        source_text="Мы меняем сценарий обучения, чтобы менеджер быстрее доводил клиента до первой сделки.",
    )

    assert "Фрагмент выступления" in prompt
    assert "Мы меняем сценарий обучения" in prompt
    assert "Верни строго JSON" in prompt


def test_questions_retry_prompt_keeps_source_context():
    prompt = _build_questions_retry_prompt(
        main_idea="Команда сокращает путь клиента до первой сделки.",
        summary_bullets=["Новый онбординг убирает лишние согласования."],
        key_terms=["онбординг", "сделки"],
        source_text="Мы меняем сценарий обучения, чтобы менеджер быстрее доводил клиента до первой сделки.",
    )

    assert "Фрагмент выступления" in prompt
    assert "онбординг" in prompt
    assert "Верни строго JSON" in prompt


def test_questions_filter_accepts_relevant_question_from_source_text_even_without_keyword_stem_match():
    source_text = "Мы меняем сценарий обучения менеджеров, чтобы клиент быстрее доходил до первой сделки без лишних согласований."
    keywords = ["онбординг", "сделки"]
    raw_items = [
        "Как вы поймёте, что новый сценарий обучения реально ускорил путь клиента до сделки?",
    ]

    filtered, reasons, rejected = _filter_questions(raw_items, source_text, keywords, main_idea="Сократить путь клиента до первой сделки")

    assert filtered == ["Как вы поймёте, что новый сценарий обучения реально ускорил путь клиента до сделки?"]
    assert reasons == []
    assert rejected == []


def test_llm_disabled_uses_generic_fallback(monkeypatch):
    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: False)
    items = _generate_audience_questions(
        transcript_text="Сегодня разбираем план запуска сервиса и сроки внедрения в отделе продаж.",
        segments=[{"text": "План запуска сервиса включает три шага и дедлайн через 2 недели."}],
        summary_bullets=["План запуска состоит из трёх шагов."],
        session_id="test-session",
    )
    assert len(items) == 3
    assert all(item.endswith("?") for item in items)


def test_question_count_is_between_three_and_five_for_fallback():
    assert len(_contextual_fallback_questions(desired_count=3)) == 3
    assert len(_contextual_fallback_questions(desired_count=4)) == 4
    assert len(_contextual_fallback_questions(desired_count=5)) == 5


def test_questions_short_llm_items_are_not_dropped_to_fallback(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):  # noqa: ANN003
            return ('{"items":[{"q":"Какие риски вы видите при внедрении, и какие меры заранее снизят их влияние на сроки и результат команды?"},{"q":"Что именно изменится для команды после запуска, и какие показатели подтвердят, что переход прошел успешно?"},{"q":"Как вы предлагаете измерять успех проекта по неделям, чтобы корректировать подход до появления критичных проблем?"}]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())

    items = _generate_audience_questions(
        transcript_text="Мы меняем процесс внедрения для команды продаж, чтобы клиент быстрее получал результат.",
        segments=[{"text": "Мы меняем процесс внедрения и критерии успеха для команды продаж."}],
        summary_bullets=["Меняется процесс внедрения и критерии успеха."],
        session_id="session-test",
    )

    outcome = get_last_coaching_outcomes().get("questions") or {}
    assert len(items) >= 3
    assert outcome.get("used") == "llm"


def test_keywords_llm_requires_6_to_10_items(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):  # noqa: ANN003
            return ('{"keywords":["рынок","сегментация","ценностное предложение","конверсия","каналы продаж","удержание"]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())
    brief = {
        "excerpt": "Обсуждаем стратегию вывода нового продукта на рынок и рост конверсии через работу с сегментами.",
        "main_idea": "Стратегия вывода продукта на рынок.",
        "key_terms": ["рынок", "конверсия"],
    }

    keywords = _generate_summary_keywords(transcript_text=None, segments=[{"text": brief["excerpt"]}], session_id="s-1", brief=brief)
    assert 6 <= len(keywords) <= 10


def test_build_coaching_payload_includes_llm_source_fields(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):  # noqa: ANN003
            user_prompt = kwargs.get("user_prompt", "")
            if '"bullets"' in user_prompt:
                return ('{"bullets":["В начале вы объясняете проблему команды и показываете, почему текущий процесс тормозит получение результата клиентом.","Далее вы предлагаете новый порядок действий, где каждый этап связан с измеримой метрикой эффективности внедрения.","Отдельно вы подчеркиваете риски запуска и описываете, какие меры снижают вероятность срыва сроков.","В финале вы даете аудитории понятный следующий шаг, который можно выполнить сразу после выступления."]}', "stop", {})
            if '"keywords"' in user_prompt:
                return ('{"keywords":["структура выступления","ключевой тезис","аудиторный фокус","практический шаг","риски внедрения","метрики результата"]}', "stop", {})
            return ('{"items":[{"q":"Какой конкретный следующий шаг должна сделать команда после выступления, чтобы проверить, что новый подход действительно работает на практике?"},{"q":"Какие риски внедрения вы считаете наиболее критичными, и как аудитория может заранее подготовиться к этим ограничениям?"},{"q":"Какие метрики вы рекомендуете отслеживать в первые недели, чтобы понять, что изменения дают ожидаемый результат?"}]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())

    payload = build_coaching_payload(
        results={
            "session_id": "source-test",
            "delivery": {"tempo": {"wpm_category": "normal"}, "pauses": {"pause_ratio": {"value": 0.18}}},
            "word_choice": {"fillers": {"count": {"value": 1}, "density": {"value": 0.7}}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {"top_words": [], "top_phrases": []}, "weak_words": {"count": {"value": 1}}, "conciseness": {"redundancy_score": {"value": 0.2}}},
            "voice": {"pitch": {"label": "выразительно"}, "loudness": {"label": "стабильно"}},
            "visual": {"centering": {"value": 90}, "stability": {"value": 88}},
        },
        transcript_text="Это тестовый текст выступления для проверки источников блоков.",
        segments=[{"idx": 0, "start_sec": 0, "end_sec": 12, "text": "Ключевой фрагмент выступления о структуре и выводах."}],
    )

    assert payload["summary"]["source"] == "llm"
    assert payload["summary"]["fallback_reason"] is None
    assert payload["questions"]["source"] == "llm"
    assert payload["questions"]["fallback_reason"] is None


def test_questions_lenient_acceptance_avoids_fallback(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):
            return ('{"items":[{"q":"Как вы планируете измерять эффект внедрения в первые две недели, чтобы оперативно скорректировать действия команды?"},{"q":"Какие ограничения решения могут повлиять на итоговый результат, и как вы предлагаете смягчить эти риски заранее?"},{"q":"Что нужно подготовить заранее для запуска, чтобы команда прошла переход без задержек и потери качества?"}]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())

    items = _generate_audience_questions(
        transcript_text="Мы запускаем новый процесс внедрения для команды и контролируем метрики каждую неделю.",
        segments=[{"text": "Новый процесс внедрения требует подготовки данных и ролей."}],
        summary_bullets=["Процесс внедрения и контроль метрик."],
        session_id="session-lenient",
    )
    outcome = get_last_coaching_outcomes().get("questions") or {}
    assert len(items) >= 3
    assert outcome.get("used") == "llm"


def test_summary_with_four_bullets_passes_validator(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):  # noqa: ANN003
            user_prompt = kwargs.get("user_prompt", "")
            if '"bullets"' in user_prompt:
                return ('{"bullets":["Вы чётко обозначаете исходную проблему команды и объясняете, почему без изменений теряется скорость принятия решений.","Далее вы предлагаете практичную схему действий с ролями, где каждый шаг связан с измеримой метрикой результата.","Отдельно вы показываете риски запуска и заранее даёте способы их смягчения без перегрузки процесса.","В финале вы формулируете понятный следующий шаг, который аудитория может выполнить сразу после выступления."]}', "stop", {})
            if '"keywords"' in user_prompt:
                return ('{"keywords":["структура выступления","практичный шаг","командный процесс","риски запуска","метрики эффекта","план внедрения"]}', "stop", {})
            return ('{"items":[{"q":"Какой первый шаг команда должна сделать уже сегодня, чтобы запустить предложенный процесс без задержек?"},{"q":"Какие метрики вы считаете обязательными для контроля эффективности на первом этапе внедрения?"},{"q":"Какие риски нужно закрыть заранее, чтобы запуск не потерял темп и качество?"}]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())

    payload = build_coaching_payload(
        results={"session_id": "summary-4", "delivery": {}, "word_choice": {}, "voice": {}, "visual": {}},
        transcript_text="Тестовый текст выступления о запуске процесса и метриках результата.",
        segments=[{"text": "Мы запускаем новый процесс, фиксируем риски и вводим измеримые метрики результата для команды."}],
    )
    assert len(payload["summary"]["bullets"]) == 4
    assert payload["summary"]["source"] == "llm"
    assert payload["summary"]["fallback_reason"] is None


def test_questions_non_russian_triggers_ru_repair_and_keeps_llm(monkeypatch):
    class DummyClient:
        last_call_meta = {}

        def call_llm(self, **kwargs):  # noqa: ANN003
            user_prompt = kwargs.get("user_prompt", "")
            request_id = str(kwargs.get("request_id") or "")
            if '"bullets"' in user_prompt:
                return ('{"bullets":["В начале вы обозначаете проблему и объясняете важность изменений для команды и результата.","Далее вы предлагаете конкретные шаги внедрения и связываете их с метриками эффективности.","Вы отдельно отмечаете риски запуска и предлагаете способы их заранее снизить.","В финале даёте понятный следующий шаг, который аудитория может сделать сразу."]}', "stop", {})
            if '"keywords"' in user_prompt:
                return ('{"keywords":["структура","метрики","риски","внедрение","план","команда"]}', "stop", {})
            if request_id.endswith("-repair-ru"):
                return ('{"items":[{"q":"Какой конкретный шаг команда должна сделать первой, чтобы запуск прошёл без задержек и потери качества результата?"},{"q":"Какие риски внедрения вы считаете наиболее критичными и как предлагаете снизить их до старта работ?"},{"q":"По каким метрикам вы предложите оценить эффект изменений уже в первые недели после запуска?"}]}', "stop", {})
            return ('{"items":[{"q":"What first step should the team take to launch quickly without delays and quality loss?"},{"q":"Which risks are critical and how will you mitigate them before kickoff?"},{"q":"What metrics will prove the changes worked in the first weeks?"}]}', "stop", {})

    monkeypatch.setattr("app.services.coaching_builder.is_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.coaching_builder.get_local_llm_client", lambda: DummyClient())

    payload = build_coaching_payload(
        results={"session_id": "q-ru-repair", "delivery": {}, "word_choice": {}, "voice": {}, "visual": {}},
        transcript_text="Тестовый текст выступления о запуске, рисках и метриках внедрения.",
        segments=[{"text": "Мы запускаем новый процесс и заранее оцениваем риски и метрики результата."}],
    )
    outcome = get_last_coaching_outcomes().get("questions") or {}
    assert payload["questions"]["source"] == "llm"
    assert outcome.get("used") == "llm"
    assert len(payload["questions"]["items"]) >= 3
