up:
	docker compose up --build

build:
	DOCKER_BUILDKIT=1 docker compose build

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

reset:
	docker compose down -v
	docker builder prune -f


asr-smoke:
	docker compose run --rm worker python /app/scripts/asr_runtime_smoke.py
