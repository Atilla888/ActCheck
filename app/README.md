# ActCheck application

- [frontend/](frontend/README.md) — React/Vite UI (EN/KK/RU).
- [server/](server/main.py) — FastAPI: runs the agent (`agent/pipeline.py`) on uploaded files.

## Run locally

```bash
uv run uvicorn app.server.main:app --reload          # API on :8000 (reads .env)
cd app/frontend && npm ci && npm run dev             # UI on :5173, proxies /api to :8000
```

If port 8000 is taken, start the API with `--port 8077` and the UI with
`ACTCHECK_API=http://127.0.0.1:8077 npm run dev`.

## Run as one container

```bash
docker build -t actcheck .
docker run --env-file .env -p 8000:8000 actcheck     # UI and API on :8000
```

## API

| Method | Path | |
| --- | --- | --- |
| GET | `/api/health` | `{ok, model_key}` |
| GET | `/api/sample?lang=ru\|kk\|en` | The worked example: real agent, synthetic act, stored SAM measurement of a synthetic wall. No model calls. |
| POST | `/api/inspections` | multipart: `act` (images or PDF, 1+), `walls` (photos), `tile_width_mm`, `tile_height_mm`, `grout_mm`, `tile_source`, `lang` → `202 {id, status}` |
| GET | `/api/inspections/{id}` | `{status: queued\|parsing\|measuring\|counting\|protocol\|done\|failed, result, error}` |
| GET | `/api/files/jobs/…`, `/api/files/sample/…` | Uploaded pages and measurement overlays referenced by `result` |
| GET | `/api/docs` | OpenAPI UI |

Inspections run in a background thread and live in memory; a restart forgets them. SAM takes
roughly 30–60 s per uncached wall, so the UI polls. Model credentials stay on the server; the
browser never receives them.
