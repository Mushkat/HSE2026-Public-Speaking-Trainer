from __future__ import annotations

import json

import app.services.coaching_builder as coaching_builder


class FakeLLMClient:
    def __init__(self) -> None:
        self.last_call_meta = {"raw_response": "{\"items\": [\"Какая одна метрика доказывает эффективность подхода\", \"Как вы измеряете результат на практике\", \"Какие риски вы считаете критичными\", \"Что будет первым шагом после выступления\"]}"}

    def generate_json(self, **_kwargs):
        return {
            "items": [
                "Какая одна метрика доказывает эффективность подхода",
                "Как вы измеряете результат на практике",
                "Какие риски вы считаете критичными",
                "Что будет первым шагом после выступления",
            ]
        }


def main() -> None:
    coaching_builder.is_llm_enabled = lambda: True
    coaching_builder.get_local_llm_client = lambda: FakeLLMClient()

    transcript = (
        "Сегодня объясню, как команда сократила цикл сделки на 20 процентов за счёт нового сценария встречи. "
        "Мы изменили структуру вопросов, добавили контрольные метрики и снизили риски в пилоте."
    )
    segments = [
        {"text": "Мы сократили цикл сделки и хотим масштабировать подход на всю команду продаж."},
        {"text": "Главный риск — потеря качества квалификации, поэтому мы ввели проверку гипотез и метрики."},
    ]
    summary = [
        "Команда сократила цикл сделки за счёт новой структуры встречи.",
        "Подход проверяется метриками и контролем рисков.",
    ]

    result = coaching_builder._generate_audience_questions(
        transcript_text=transcript,
        segments=segments,
        summary_bullets=summary,
        session_id="selftest-session",
    )

    raw_preview = "{" + '"items": ["Какая одна метрика...", "..." ]}'
    filtered, reasons, rejected = coaching_builder._filter_questions(
        [
            "Какая одна метрика доказывает эффективность подхода?",
            "Как вы измеряете результат на практике?",
            "Какие риски вы считаете критичными?",
            "Что будет первым шагом после выступления?",
        ],
        transcript,
        ["метрика", "риск", "результат"],
        require_keyword_match=False,
        main_idea="Сокращение цикла сделки",
    )

    print("RAW_CONTENT_PREVIEW:")
    print(raw_preview)
    print("\nPARSED_JSON:")
    print(json.dumps({"items": filtered}, ensure_ascii=False, indent=2))
    print("\nVALIDATION_DECISIONS:")
    print(json.dumps({"kept": filtered, "reasons": reasons, "rejected": rejected}, ensure_ascii=False, indent=2))
    print("\nFINAL_OUTPUT:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
