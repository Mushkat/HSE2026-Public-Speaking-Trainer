# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    HF_HOME=/models/huggingface \
    XDG_CACHE_HOME=/models/.cache

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        findutils \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        patchelf \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

RUN set -eux; \
    libs="$(find /usr/local -type f -name 'libctranslate2*.so*' || true)"; \
    if [ -z "$libs" ]; then \
      echo "No libctranslate2 shared libraries found"; \
      exit 1; \
    fi; \
    for lib in $libs; do \
      echo "Clearing execstack for $lib"; \
      patchelf --clear-execstack "$lib"; \
    done

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /models/faster-whisper /models/huggingface /models/.cache /app/storage

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
