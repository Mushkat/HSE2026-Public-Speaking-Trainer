# Public Speaking Trainer

Веб-приложение для тренировки публичных выступлений. Пользователь загружает аудио- или видеозапись выступления, запускает анализ и получает транскрипт, речевые, голосовые и визуальные метрики, а также рекомендации по улучшению выступления.

## Возможности

- Регистрация и авторизация пользователей
- Создание практик выступлений
- Выбор сценария тренировки
- Загрузка аудио/видео
- Асинхронный анализ записи
- Распознавание речи и построение транскрипта
- Анализ темпа, пауз, слов-паразитов, повторов и слабых слов
- Анализ голоса: вариативность высоты тона и громкости
- Базовый видеоанализ: центрирование, стабильность, зрительный контакт
- Просмотр результатов и прогресса по сессиям
- Повторный анализ после изменения данных

## Демонстрация

Демонстрационное видео: **https://disk.360.yandex.ru/i/pn3Pldh9Qq69oA**

## Технологический стек

- Frontend: React, TypeScript, Vite
- Backend: FastAPI, SQLAlchemy, Pydantic
- Database: PostgreSQL
- Queue: Redis + RQ Worker
- ASR: faster-whisper
- Audio analysis: librosa, parselmouth
- Video analysis: OpenCV
- Optional LLM: локальный LLM-сервис
- Deployment: Docker Compose

## Структура проекта

```text
.
├── backend/          # FastAPI API, модели, сервисы анализа, worker
├── frontend/         # React/Vite клиентская часть
├── llm/              # Опциональный локальный LLM-сервис
├── scripts/          # Smoke/dev scripts
├── models/           # Локальные модели
├── docker-compose.yml
└── docker-compose.gpu.yml
````

## Быстрый запуск

Из корня репозитория:

```bash
docker compose build
docker compose up -d
```

Проверить состояние сервисов:

```bash
docker compose ps
```

Посмотреть логи:

```bash
docker compose logs -f api worker frontend
```

## Адреса сервисов

* Frontend: [http://localhost:5173](http://localhost:5173)
* API health: [http://localhost:8000/health](http://localhost:8000/health)
* Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
* LLM health, если включён: [http://localhost:8080/health](http://localhost:8080/health)

## Запуск с локальным LLM (рекомендуемый способ запуска)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d --build
```

Проверка статуса LLM:

```bash
curl http://localhost:8000/system/llm-status
```

## Smoke-проверки

```bash
bash scripts/smoke.sh
bash scripts/smoke_api.sh
```

## Работа с базой данных

Открыть `psql` внутри контейнера:

```bash
docker compose exec db psql -U postgres -d speech_trainer
```

Полезные запросы:

```sql
SELECT id, email, created_at
FROM users
ORDER BY created_at DESC
LIMIT 20;

SELECT id, user_id, title, created_at
FROM sessions
ORDER BY created_at DESC
LIMIT 20;

SELECT session_id, status, step, progress, error_message, updated_at
FROM statuses
ORDER BY updated_at DESC
LIMIT 20;
```

## Основной пользовательский сценарий

1. Зарегистрироваться или войти в аккаунт.
2. Создать практику.
3. Выбрать сценарий выступления.
4. Загрузить аудио- или видеофайл.
5. Запустить анализ.
6. Дождаться завершения обработки.
7. Посмотреть результаты, транскрипт и рекомендации.
8. При необходимости изменить транскрипт и выполнить повторный анализ.

## Поддерживаемые форматы

* Видео: `mp4`, `mov`, `webm`
* Аудио: `mp3`, `wav`

Ограничение размера файла: до `500 MB`.

Вот готовый блок, который можно просто вставить в README:

## Локальная LLM-модель

Для генерации коучинговых блоков (рекомендации, вопросы аудитории, ключевые слова и др.) в проекте используется локальная языковая модель.

Используемая модель:
- https://huggingface.co/QuantFactory/Meta-Llama-3-8B-Instruct-GGUF/blob/main/Meta-Llama-3-8B-Instruct.Q8_0.gguf

### Важно

Файл модели **не включён в репозиторий**, так как имеет большой размер.

### Как подключить модель

1. Скачать `.gguf` файл по ссылке выше
2. Поместить его в директорию проекта:

```text
/models
````

3. Переименовать файл в:

```text
model.gguf
```

### Использование

После добавления модели можно запустить сервис с поддержкой LLM:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d --build
```

Проверка статуса после загрузки весов:

```bash
curl http://localhost:8000/system/llm-status
```

### Примечания

* LLM используется только для генерации текстовых рекомендаций и не влияет на расчёт базовых метрик.
* При отсутствии модели система продолжает работать, используя fallback-логику.
* Качество рекомендаций зависит от выбранной модели и параметров генерации.


## Очистка окружения

Остановить контейнеры:

```bash
docker compose down
```

Остановить контейнеры и удалить volumes:

```bash
docker compose down -v
```

> Важно: `down -v` удаляет данные PostgreSQL, загруженные медиа и кэш моделей.

## Примечания

* Анализ выполняется асинхронно через Redis/RQ worker.
* Базовые метрики работают без LLM.
* LLM используется только для дополнительных коучинговых блоков и может быть отключён.
* Качество анализа зависит от качества записи, шума, освещения и положения пользователя в кадре.