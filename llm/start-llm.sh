#!/usr/bin/env bash
set -euo pipefail

echo "[llm] GPU self-check: nvidia-smi"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[llm] FATAL: nvidia-smi is not available in container; GPU runtime is not configured." >&2
  exit 1
fi

if ! nvidia-smi; then
  echo "[llm] FATAL: GPU is not visible inside llm container." >&2
  exit 1
fi

if [[ ! -f "${LOCAL_LLM_MODEL_PATH:-/models/model.gguf}" ]]; then
  echo "[llm] FATAL: model file not found at ${LOCAL_LLM_MODEL_PATH:-/models/model.gguf}." >&2
  exit 1
fi

exec /usr/local/bin/llama-server \
  --model "${LOCAL_LLM_MODEL_PATH:-/models/model.gguf}" \
  --host 0.0.0.0 \
  --port 8080 \
  --ctx-size "${LOCAL_LLM_CTX_SIZE:-2048}" \
  --n-predict "${LOCAL_LLM_N_PREDICT:-256}" \
  --parallel "${LOCAL_LLM_PARALLEL:-1}" \
  --batch-size "${LOCAL_LLM_BATCH_SIZE:-512}" \
  --ubatch-size "${LOCAL_LLM_UBATCH_SIZE:-256}" \
  --cache-type-k "${LOCAL_LLM_CACHE_TYPE_K:-q8_0}" \
  --cache-type-v "${LOCAL_LLM_CACHE_TYPE_V:-q8_0}" \
  --threads "${LOCAL_LLM_THREADS:-8}" \
  --threads-batch "${LOCAL_LLM_THREADS_BATCH:-8}" \
  --n-gpu-layers "${LOCAL_LLM_N_GPU_LAYERS:-24}" \
  --cache-ram 0 \
  --no-warmup \
  --temp "${LOCAL_LLM_TEMP:-0.2}" \
  --top-p "${LOCAL_LLM_TOP_P:-0.9}" \
  --repeat-penalty "${LOCAL_LLM_REPEAT_PENALTY:-1.1}"
