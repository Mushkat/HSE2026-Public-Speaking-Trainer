from __future__ import annotations

import json
import uuid

from app.core.local_llm import LocalLLMOptions, get_local_llm_client


def _run_once(run_idx: int) -> None:
    client = get_local_llm_client()
    if not client:
        raise SystemExit("LOCAL_LLM_ENABLED=0 or client unavailable")

    request_id = str(uuid.uuid4())
    system_prompt = "Ты проверяешь локальную LLM интеграцию. Отвечай строго JSON-объектом."
    user_prompt = (
        "Верни JSON формата:\n"
        '{"items":["Q1?","Q2?","Q3?"]}\n\n'
        "Текст:\n"
        "Сегодня команда запускает пилот в трёх филиалах. "
        "Ключевой риск - нехватка ресурсов на внедрение."
    )

    payload = client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt[:900],
        options=LocalLLMOptions(max_tokens=180, temperature=0.2),
        trace_id=f"selftest:llm:{run_idx}",
        purpose="selftest",
        request_id=request_id,
        session_id=f"llm_selftest_run_{run_idx}",
    )
    meta = client.last_call_meta
    if not isinstance(payload, dict):
        raise SystemExit(f"selftest run {run_idx} failed: {meta.get('failure_reason') or 'payload_missing'}")

    extracted_preview = ""
    response_payload = meta.get("response_payload") if isinstance(meta.get("response_payload"), dict) else {}
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else []
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            extracted_preview = content[:300]

    print(f"=== run {run_idx} ===")
    print(f"request_id: {request_id}")
    print(f"endpoint: {meta.get('endpoint')}")
    print(f"timeout_connect_sec: {meta.get('timeout_connect_sec')}")
    print(f"timeout_read_sec: {meta.get('timeout_read_sec')}")
    print(f"raw_response_length: {len(meta.get('raw_response') or '')}")
    print(f"failure_reason: {meta.get('failure_reason')}")
    print(f"extracted_content_preview: {extracted_preview}")
    print("parsed_json:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))



def main() -> None:
    for idx in range(1, 4):
        _run_once(idx)


if __name__ == "__main__":
    main()
