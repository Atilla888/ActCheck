# ActCheck

Photo-based measurement of tiled surfaces, compared with a contractor's work statement. Results must show uncertainty, exclusions, and questions for human review before payment.

Wall measurement is implemented in [`measure/`](measure/README.md): SAM 3.1 tile masks → a lattice-constrained homography ("the room is its own ruler") → tiled area in m² with uncertainty, exclusions, an explicit `measured` / `partial` / `unavailable` status and an overlay for every photo. It is validated on synthetic walls with exact ground truth; field accuracy against laser measurements is still pending ([validation](validation/README.md)).

The local frontend in `app/frontend/` is an inspection workspace with illustrative measurements, visual evidence, statement review, local uploads, notes, and printable reports. It is not yet connected to the measurement module; its example quantities and overlays are labeled synthetic fixtures.

## Measure a wall

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked
uv run python -m measure.cli wall photo.jpg --tile 300x600 --source box_label
```

This prints the `WallMeasurement` JSON and writes the overlay to `outputs/measure/`. Uncached photos are sent to SAM (about 15 requests, ~$0.04 per wall) and need `META_API_KEY` in `.env`.

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

For a new checkout, copy `.env.example` to `.env` and run `chmod 600 .env`. Fill the credentials locally; do not paste keys into chat or commit them. The standalone validation client loads this server-side configuration. Model requests upload selected photos and use API credits; completed identical requests can reuse the local cache. The frontend remains in example mode.

## Folder layout

| Path | Purpose |
| --- | --- |
| `schemas/` | Shared Pydantic contract, pending team agreement |
| `measure/` | SAM client and cache, lattice geometry, area and uncertainty, overlays, CLI |
| `validation/` | Room measurements, accuracy, ROC, and ablation |
| `agent/` | Statement parsing, planning, comparison, protocol |
| `app/frontend/` | Working React/Vite inspection frontend; local example mode |
| `app/` | Future FastAPI service and integration |
| `tests/` | Offline benchmark, crop geometry, deduplication, and analysis checks |
| `data/samples/` | Consented, anonymized public fixtures only |
| `data/private/` | Private room photos and field records; ignored |
| `data/cache/` | Private model responses and derived cache; ignored |
| `outputs/` | Generated overlays and reports; ignored |
| `docs/` | Access and preparation notes |

Private photos, consent records, and room notes stay in `data/private/`. Publish a reviewed, anonymized validation table only after checking permission. A tracked empty `validation/rooms.csv` provides the planned columns; do not add identifying field notes to it.

## Readiness

- Preparation checks cover locked offline dependency sync, Python 3.12 imports, valid TOML, and Git exclusions for secrets/private data. Frontend build and browser checks are documented in its README.
- Measurement: `measure_wall` / `measure_room` / `count_objects` implement team plan §5.1 on the shared schema; 121 offline tests pass. On 16 synthetic renders segmented by SAM 3.1, the 11 walls reported as `measured` are within 1.33 % (all within 2σ); the other five are flagged `partial` or refused. Synthetic accuracy is not field accuracy.
- Field check: 1–2 laser-measured walls are planned ([protocol](validation/FIELD_PROTOCOL.md)); no field data exists yet. The 20 collected web photos have no physical scale and only show fit/refusal behaviour.
- The standalone SAM benchmark has been exercised on the collected photos. Credentials stay in the ignored local `.env`.
- Meta API reference material is available in `.claude/skills/meta-model-api/SKILL.md`. Model access setup and unresolved details are recorded in `docs/MODEL_ACCESS.md`.
- The repository remote is `https://github.com/Atilla888/ActCheck.git`. Frontend development runs locally; no hosted deployment has been created.
- Gates: the October 27 mask gate was not met on full frames (3/20) and reached 12/20 screened candidates with crops; the lattice now tolerates missing and merged masks instead. The ≤3 % room gate awaits field data.
- Integration: the measurement API, statuses and example JSON for the agent are documented in [`measure/README.md`](measure/README.md); wiring into `app/` and the agent is teammate A's.
