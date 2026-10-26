# ActCheck

Photo-based measurement of tiled surfaces, compared with a contractor's work statement. Results must show uncertainty, exclusions, and questions for human review before payment.

The local frontend is implemented in `app/frontend/`: an inspection workspace with illustrative measurements, visual evidence, statement review, local uploads, notes, and printable reports. The measurement backend and model integrations are not connected yet. Example quantities and overlays are clearly labeled synthetic fixtures.

## Run the frontend

With Node.js 24 and npm:

```sh
cd app/frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173/**. Run `npm run build` for a production build. See [frontend documentation](app/frontend/README.md) for behavior, limitations, and verification.

## Ownership and plan

- **Atilla / B:** `measure/`, `validation/`, measurement tests, overlays, and field evidence.
- **Teammate / A:** `agent/`, `app/` including the frontend, protocol export, deployment, and submission.
- **Shared:** `schemas/`; the draft in the team plan is awaiting agreement on October 27.

The frontend was implemented at the user's subsequent request. Coordinate its backend integration with teammate A; the shared measurement schemas remain unchanged.

Read the [model access instructions](docs/MODEL_ACCESS.md). Team and personal planning documents are maintained locally and excluded from this repository.

## Local setup

Use Python 3.12 and `uv` from the repository root:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked
```

The optional application dependencies are reserved for teammate A:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked --group app
```

An empty local `.env` is prepared with owner-only permissions. If creating a new checkout, copy `.env.example` to `.env` and run `chmod 600 .env`. Fill the credentials locally; do not paste keys into chat or commit them. Endpoint and model fields are populated only when verified in the access guide. No service currently loads this configuration; client implementation follows the agreed development window.

## Folder layout

| Path | Purpose |
| --- | --- |
| `schemas/` | Shared Pydantic contract, pending team agreement |
| `measure/` | SAM client, lattice geometry, area, overlays, CLI |
| `validation/` | Room measurements, accuracy, ROC, and ablation |
| `agent/` | Statement parsing, planning, comparison, protocol |
| `app/frontend/` | Working React/Vite inspection frontend; local example mode |
| `app/` | Future FastAPI service and integration |
| `tests/` | Measurement and integration checks, to be implemented |
| `data/samples/` | Consented, anonymized public fixtures only |
| `data/private/` | Private room photos and field records; ignored |
| `data/cache/` | Private model responses and derived cache; ignored |
| `outputs/` | Generated overlays and reports; ignored |
| `docs/` | Access and preparation notes |

Private photos, consent records, and room notes stay in `data/private/`. Publish a reviewed, anonymized validation table only after checking permission. A tracked empty `validation/rooms.csv` provides the planned columns; do not add identifying field notes to it.

## Readiness

- Preparation checks passed: locked offline dependency sync, Python 3.12 imports for all core/application libraries, valid TOML, empty credential fields, owner-only `.env` permissions, and Git exclusions for secrets/private data. Frontend build and browser checks are documented in its README.
- Credentials are intentionally blank; this session makes no paid model calls.
- Meta API reference material is available in `.claude/skills/meta-model-api/SKILL.md`. Model access setup and unresolved details are recorded in `docs/MODEL_ACCESS.md`.
- The repository remote is `https://github.com/Atilla888/ActCheck.git`. Frontend development runs locally; no hosted deployment has been created.
- The acceptance gates remain: at least 16 of 20 walls with at least 30 reliable masks on October 27; at most 3% error on three rooms on October 29. Confirm whether to check each room separately during schema review.
- Stub handoff is October 28; real measurement handoff is October 30.
