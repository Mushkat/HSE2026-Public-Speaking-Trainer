from __future__ import annotations

import json
import uuid

from app.core.local_llm import LocalLLMOptions, get_local_llm_client


TEXT = (
    "Сегодня мы запускаем пилот в трёх филиалах. "
    "Главный риск - перегрузка команды внедрения, поэтому добавляем еженедельный контроль. "
    "Через две недели измеряем время ответа и удовлетворённость клиентов."
)


def main() -> None:
    client = get_local_llm_client()
    if not client:
        raise SystemExit("LOCAL_LLM_ENABLED=0 or client unavailable")

    system_prompt = "Ты ассистент по публичным выступлениям. Верни JSON по инструкции."
    user_prompt = (
        "Верни строго JSON:\n"
        '{"items":["вопрос 1","вопрос 2","вопрос 3"]}\n\n'
        f"Текст:\n{TEXT}"
    )

    request_id = str(uuid.uuid4())
    payload = client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        options=LocalLLMOptions(max_tokens=200, temperature=0.2),
        trace_id="debug:probe",
        purpose="debug_probe",
        request_id=request_id,
    )
    print(f"request_id: {request_id}")
    print(f"endpoint: {client.last_call_meta.get('endpoint')}")
    print("parsed_json:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
