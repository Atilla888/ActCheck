# Validation — Atilla / B

`rooms.csv` is an empty public template using the team-plan columns. Keep actual field records, identifying notes, consent evidence, and photos under ignored `data/private/`; publish only approved anonymized rows here.

Record laser ground truth independently from predictions. Preserve wall-to-room grouping. Keep all versions of a room together when splitting data for threshold selection and evaluation. Label artificially inflated statements as `planted`; do not present them as observed contractor behavior.

Planned outputs: per-wall and per-room accuracy, MAPE and median error, uncertainty coverage, ROC/AUC over 0–30% planted inflation, and a matched comparison against a classical grout detector. Do not invent rooms, ground truth, or validation scores.

## Collected-photo SAM benchmark

`benchmark_tiles.py` audits `bathroom_tiles_20/sources.csv` against the actual JPEGs, then
calls SAM using server-side settings from `.env`. It preserves originals, normalizes EXIF
orientation, caches completed response events, and produces contour overlays and mask metadata.
The API client/parser are pinned in `pyproject.toml` and `uv.lock`.

From the repository root:

```sh
uv sync
uv run python validation/benchmark_tiles.py --audit-only
uv run python validation/benchmark_tiles.py --max-side 1600 --crops
uv run python validation/summarize_tiles.py
uv run pytest -q tests/test_tile_benchmark.py
```

The second command with inference sends the collected images to Meta and uses API credits.
It runs the three plan prompts separately (`tile`, `wall tile`, `ceramic tile`) and nine
source-space overlapping crops on image 01. Six requests at most run concurrently; no automatic
HTTP retries. Completed identical requests reuse the cache. Defaults without `--max-side`
submit original resolution; an original 7296×5472 image was rejected with HTTP 400 in the first
trial. A 1600-pixel long-side input was accepted. This is an observed fallback, not a verified
maximum image size. Both full-frame and crop trial dimensions are recorded.

Outputs are local and ignored:

- `outputs/tile_benchmark/report.html`: table and linked overlays (open manually if desired).
- `outputs/tile_benchmark/results.csv`: per-photo, per-prompt candidate counts.
- `outputs/tile_benchmark/runs.json`: observed request latency, dimensions, cache keys and errors.
- `outputs/tile_benchmark/*_masks.json`: source-input coordinate boxes and mask diagnostics.
- `data/cache/sam_benchmark/`: raw response-event caches; no authentication headers or keys.

**Do not equate candidate count with the plan's reliable-mask gate.** The diagnostic filter uses
confidence ≥0.5, area ≥25 pixels and ≤10% of the input image, and rotated-rectangle occupancy
≥0.65. It does not reject mirrors, floors, duplicate physical surfaces or mixed wall planes.
Thresholds are exploratory and uncalibrated. Select the actual wall and annotate correct,
independent tile masks before claiming ≥30 reliable masks. Choosing the best prompt on the same
20 photos is development/tuning, not an independent evaluation. Crops are reported individually;
never sum their overlapping detections as independent tiles.

These downloaded reference photos have no physical tile dimensions or reference wall areas.
They cannot validate the ≤3% room-area requirement. Curved wall 16 is also outside the single
planar homography assumption. Keep the field-measurement validation above as a separate task.

## Crop strategy across the whole collection

The crop experiment extends the diagnostic above without changing the original photos:

```sh
uv run python -m validation.crop_benchmark --concurrency 3
uv run python -m validation.analyze_crops --rescreen-existing --workers 4
uv run pytest -q tests/test_tile_benchmark.py tests/test_crop_merge.py \
  tests/test_crop_benchmark.py tests/test_crop_analysis.py
```

It uses a fixed `tile` prompt and nine overlapping source-resolution windows per photo,
with a 1600-pixel maximum long side per request. The model receives up to 180 crop inputs;
completed identical requests are reused. The initial image-01 crop experiment is reused too.
No Spark calls or invented measurements are involved.

- Request jobs, attempt manifests, and completion accounting live in `outputs/tile_crops/`.
- `measure/crop_merge.py` maps mask-local pixels through each actual resized crop into the
  EXIF-oriented original. Separate x/y scale factors account for resize rounding.
- Deduplication uses mask overlap, keeps complete observations over cropped fragments, and
  suppresses broad multi-tile masks only when separate smaller instances support doing so.
  Adjacent tiles are not merged just because their bounding boxes overlap.
- `validation/tile_wall_regions.json` records manually inspected, hash-bound polygons for
  one selected wall per photo. Mirrors, floors and unrelated planes are excluded where visible.
  These polygons are approximate spatial annotations, not tile-instance ground truth.
- At least 95% of a retained mask must lie in the selected wall region. Crop/image edge
  fragments are excluded from the strict wall-candidate count. A conservative margin of
  0.5% of the input's shorter side (at least two pixels) catches masks that stop slightly
  before a crop seam. Curved image 16 is ineligible for the planar-wall gate.
- The analysis combines crop detections with the cached full-frame `tile` baseline. Both
  methods also receive the same wall screen, making the comparison more meaningful than raw
  whole-photo counts.
- All nine crop jobs plus the baseline must be present and validated for a complete image
  result. Errors and unfinished images never become successful zero-mask results.

`outputs/tile_crops/report.html`, `results.csv`, numbered `*_merged.jpg` overlays and
`*_merged.json` retain the outcome, source transforms, suppression reasons and input/code
fingerprints. `--rescreen-existing` only reuses validated complete merges; changing merge code,
input content or inference configuration invalidates reuse. It never launches a browser.
Parallel analysis uses at most four processes because the official lossless decoder is CPU-heavy.

Counts remain **candidates** until individual masks are checked against the photographed wall.
A cropped fragment can resemble a rectangle, and a fully bounded mask can still cover a partial,
misclassified or occluded tile. The qualitative manual review is separately hash-bound to its
specific overlays; do not apply an old review automatically to regenerated results.

## Wall measurement validation (November 2)

Measurement itself lives in [`measure/`](../measure/README.md). Each check below is labelled by
what it can and cannot show.

**Synthetic walls with exact ground truth** (`synthetic.py`, `synthetic_eval.py`). Rendered
walls under a pinhole camera: tile size, stack/running bond, joints, gloss, door, bottom
occluder, pose. Errors are against the visible tiled area.

```sh
uv run python -m validation.synthetic_eval --mode masks --n 40   # SAM-like masks, no API
uv run python -m validation.synthetic_eval --mode sam            # 16 renders through SAM 3.1
```

| Mode | Walls | measured | partial | unavailable | measured: median / max abs error | within 2σ |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| SAM-like masks (dropout ≤15 %, merges, false positives; ¼ with a tiled neighbouring wall or floor) | 40 | 34 | 2 | 4 | 0.61 % / 4.6 % | 34/34 |
| SAM 3.1 on renders | 16 | 11 | 4 | 1 | 0.89 % / 2.4 % | 11/11 |

"Within 2σ" uses 2(σr + σs), the bound `agent/compare.py` applies to one wall. Partial walls
carry large errors by design (SAM saw part of the wall; all were flagged), and the 25 mm mosaic
render was refused. Renders are cleaner than real bathrooms: this is evidence that the geometry
is right, not field accuracy.

**Planted-inflation ROC** (`roc.py`). Bills inflated 0–30 % over known truth; the agent's rule
`billed > measured + k·σ + hidden`, walls that are not `measured` never flag (the agent answers
`incomplete`). At k = 2: SAM-like masks — no false alarms, 58 % of 20 % inflations caught (hidden
and inferred-area allowances absorb smaller ones on these deliberately degraded masks); SAM
renders — 67 % of 5 % inflations caught (every measured wall), 1 false alarm in 15 honest bills,
from a synthetic bathtub band SAM did not recognise (no hidden allowance). Planted, not observed
bills.

```sh
uv run python -m validation.roc outputs/synthetic_eval/roc_input_sam.json --out outputs/validation/roc_synthetic_sam.json
```

**Reference photos** (`reference_run.py`). The 20 collected web photos have no physical scale,
so tile sizes are visual aspect guesses and no area is reported: 0 measured, 14 partial (mostly
`wall_out_of_frame`), 6 unavailable (`too_few_tiles`: striped, small mosaic, curved wall, mixed
planes). Overlays and a contact sheet go to `outputs/reference_run/`.

**Field check** (`run_validation.py`, [FIELD_PROTOCOL.md](FIELD_PROTOCOL.md)). Laser or tape
areas of 1–2 real walls in `data/private/rooms/rooms.csv` with one photo per wall; reports per-wall
and per-room error and the ≤3 % gate. Not run yet: no field data exists at the time of writing.

```sh
uv run python -m validation.run_validation
```
