# Speech Trainer Backend (Stage 1)

## Run locally with Docker

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

The frontend is available at `http://localhost:5173` after running `npm install` and `npm run dev` in `frontend/`.

### Run migrations manually

```bash
docker compose run --rm api alembic upgrade head
```

## Run tests

```bash
cd backend
pytest
```

## cURL examples

### Register

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'
```

### Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'
```

### Create session

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"title":"First session"}'
```

### List sessions

```bash
curl -X GET http://localhost:8000/sessions \
  -H "Authorization: Bearer <TOKEN>"
```

### Upload session media

```bash
curl -X POST http://localhost:8000/sessions/<SESSION_ID>/media \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@/path/to/recording.mp4"
```

## Upload from the UI

1. Register and log in.
2. Create or open a session.
3. Use the "Upload media" panel to choose a recording (mp4, mov, webm, mp3, wav; max 500MB).
4. After upload completes, the file appears in the attached media list and persists after refresh.
