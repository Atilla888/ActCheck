# Wall Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `measure_wall` / `measure_room` (photo + tile size → tiled m² ± σ, overlay,
explicit refusal) on A's schemas, and the validation that shows how far to trust it.

**Architecture:** Cached SAM 3.1 tile masks (full frame + 3×3 crops, merged) → quadrilaterals →
lattice-constrained homography from tile centres → plane-space raster area with bootstrap and
tolerance uncertainty → overlay. Synthetic walls with exact ground truth drive the tests and
the end-to-end accuracy table; the user's 1–2 field walls are a small-N check.

**Tech Stack:** Python 3.12, numpy, OpenCV, Pillow, scipy, pydantic v2, `meta-sam-parser`,
`openai` AsyncOpenAI (Responses API), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-02-wall-measurement-design.md`

## Global Constraints

- No new dependencies; no edits to `schemas/` (A's draft is the contract).
- SAM: settings from `.env` (`META_API_KEY`, `META_API_BASE_URL`, `META_SAM_MODEL`); prompt `tile`; metadata `{"include_confidence": "true", "mask_encoding": "lossless"}`; input ≤1600 px long side, JPEG q95 after EXIF transpose; ≤6 concurrent requests; `max_retries=0`; refuse any base URL other than `https://api.meta.ai/v1`.
- Cache: `data/cache/sam_benchmark/<sha256(sorted spec JSON)>.json`, spec = image sha256, model, base URL, prompt, metadata — byte-compatible with the existing benchmark cache.
- Spend cap for this plan: $3 (~1,200 SAM images). Stop and ask before exceeding it.
- Every σ is 1σ. Overlays show ±2σ labelled `(2σ)`.
- Synthetic and planted results are labelled as such everywhere; no field-accuracy claim beyond the user's measured walls.
- Outputs under `outputs/` and private inputs under `data/private/` (both git-ignored). Never commit photos, caches or overlays of private rooms.
- Ruff: line length 100, rules E, F, I, UP, B. Commit after each task on `measure/wall-measurement`; never push.

## Review Focus

- Wall continues out of frame → `status="partial"`, warning `wall_out_of_frame`, wall listed in `unverified_walls` (Task 6 `test_out_of_frame_wall_is_partial`).
- Tile size entered in the other orientation (300×600 for tiles laid 600 wide) → same area (Task 3 `test_orientation_swap_preserves_area`).
- Two tiled walls meeting at a corner → one plane measured, area not inflated by the other (Task 3 `test_corner_picks_one_plane`).
- 25 mm mosaic → raster resolution and lattice still within 2 % (Task 4 `test_mosaic_area`).
- Glossy patch with no masks inside the wall → filled when ≤4 cells, otherwise a `not_visible` allowance, never silently dropped (Task 4 `test_hole_filling_and_allowance`).

---

### Task 1: Shared cached SAM client

**Files:**
- Create: `measure/__init__.py` (empty for now), `measure/sam_client.py`
- Modify: `validation/benchmark_tiles.py` (import `digest`, `crops_for`, `input_image`, `infer`, `Settings`, `CACHE` from `measure.sam_client` instead of defining them)
- Test: `tests/test_sam_client.py`

**Interfaces:**
- Produces:
  - `prepare(image: Image.Image, crop: tuple[int,int,int,int] | None, max_side: int = 1600) -> tuple[tuple[int,int], bytes]` — image already EXIF-oriented RGB.
  - `request_spec(data: bytes, prompt: str, settings) -> dict`; `cache_key(spec) -> str`.
  - `class SegmentationError(RuntimeError)`.
  - `segment(image: Image.Image, concepts: Sequence[str] = (), *, crops: bool = True, client=None) -> Segmentation` (sync; runs one event loop).
  - `@dataclass Segmentation: source_size, tiles: list[dict], concepts: dict[str, list[dict]], requests: int, cached: int, seconds: float` — `tiles` are `crop_merge.merge_detections` output (source pixels); concept detections are `convert_record` dicts with confidence ≥ 0.5.

- [ ] **Step 1: Write failing tests** — `test_prepare_matches_benchmark_cache_key` (for image 01 crop 4 the spec key equals the `cache_key` in `outputs/tile_crops/jobs/01_crop04.json`; skip if the photo is absent); `test_segment_uses_cache_without_client` (image 01 with `client=None` and no key returns ≥100 tiles, `requests == 10`, `cached == 10`); `test_cache_miss_without_key_raises` (a 64×64 random image → `SegmentationError`).
- [ ] **Step 2: Run** `uv run pytest -q tests/test_sam_client.py` → FAIL (module missing).
- [ ] **Step 3: Implement.** Move the four functions and `Settings` verbatim; make `meta_api_key` optional. `segment` builds 1 full-frame + 9 crop inputs (`crops_for`), one input per concept, gathers under `asyncio.Semaphore(6)`, converts with `convert_record(record, input_size, crop_box, source_size, run_id)` and merges tiles with `merge_detections`. Without a key, a cache miss raises `SegmentationError`.
- [ ] **Step 4: Run** `uv run pytest -q` → all pass (57 existing + new).
- [ ] **Step 5: Commit** `git commit -m "Add shared cached SAM client for measurement"`.

### Task 2: Synthetic walls with exact ground truth

**Files:**
- Create: `validation/synthetic.py`
- Test: `tests/test_synthetic.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) SyntheticWall(wall_w_mm=2400, wall_h_mm=2100, tile_w_mm=300, tile_h_mm=600, grout_mm=2, bond="stack"|"running", yaw_deg=0, pitch_deg=0, roll_deg=0, image_size=(1600,1200), fill=0.8, door=None (x,y,w,h mm, untiled opening), occluder_h_mm=0 (bottom band hidden), gloss=0.0, seed=0)`.
  - `render_wall(wall) -> Render` with `image` (H×W×3 uint8 RGB), `plane_to_image` (3×3, mm→px), `tiles: list[SynthTile(i, j, polygon (k,2) px, full: bool)]`, `tiled_area_m2` (wall − door, tiles + joints), `visible_tiled_area_m2`, `hidden_area_m2`, `opening_area_m2`, `occluder_polygon`, `door_polygon` (px or None).
  - `fake_detections(render, *, seed=0, erosion_px=1.0, jitter_px=0.5, dropout=0.0, merge_rate=0.0, false_positives=0) -> list[dict]` in `crop_merge` detection format (`id`, `run_id`, `box`, `contours[{points, hole, depth}]`, `confidence`, `area_px`, `rectangularity`, `edge_truncated`, `crop_boundary`, `image_boundary`, `candidate`).
  - `fake_concept(polygon, label) -> dict` (same format) for exclusion tests.

- [ ] **Step 1: Failing tests** — `test_ground_truth_areas` (2400×2100 wall with a 800×2000 door: `tiled_area_m2 == pytest.approx(5.04 - 1.6)`); `test_tiles_cover_wall` (sum of tile+joint cells clipped to the wall equals `wall_w*wall_h`); `test_running_bond_offsets` (rows alternate x offset 0 / half pitch); `test_fake_detections_dropout_and_merge` (dropout 0.3 keeps 70 % ± 5 % of visible full tiles; merge_rate 0.1 yields masks ≈2× median area); `test_render_deterministic` (same seed → identical bytes).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Pinhole camera `K = [[f,0,cx],[0,f,cy],[0,0,1]]`, `f = 0.9·max(image_size)`, rotation from yaw/pitch/roll, distance chosen so the wall spans `fill` of the frame; `plane_to_image = K·[r1 r2 t]`. Render the plane texture at 2 px/mm (tile tint jitter, grout colour, optional gloss ellipse), `cv2.warpPerspective` with a light blur and noise; occluder band drawn last in image space.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `"Add synthetic tiled-wall renderer with exact ground truth"`.

### Task 3: Quads and lattice-constrained homography

**Files:**
- Create: `measure/lattice.py`
- Test: `tests/test_lattice.py`

**Interfaces:**
- Consumes: detections (Task 1/2 format), `schemas.measure.TileSpec`.
- Produces:
  - `MIN_TILES = 12`.
  - `@dataclass Quad(det_id: str, corners: np.ndarray (4,2), center: np.ndarray (2,), area_px: float)`.
  - `extract_quads(detections) -> tuple[list[Quad], int]` — second value = suspected merged masks.
  - `@dataclass LatticeTile(det_id, i: int, j: int, center: np.ndarray)`.
  - `@dataclass LatticeFit(H: np.ndarray (image px → plane mm), pitch: tuple[float,float], cell: tuple[float,float], tiles: list[LatticeTile], row_offsets: dict[int,float], transposed: bool, residual_px: float, straightness_px: float | None, tile_px: float, n_merged_suspected: int)` with methods `to_plane(pts) -> np.ndarray`, `to_image(pts) -> np.ndarray`.
  - `fit_lattice(detections, tile: TileSpec) -> LatticeFit | None`.

- [ ] **Step 1: Failing tests** (all on `render_wall` + `fake_detections`; "area check" = area in mm² of the wall polygon mapped image→plane with the fitted `H`, vs truth):
  `test_frontal_stack_bond` (≤0.3 % area error, residual < 1 px); `test_oblique_running_bond` (yaw 30°, pitch 10°, running bond, ≤0.5 %); `test_dropout_merges_false_positives` (dropout 0.3, merge 0.08, 15 false positives → ≤0.7 %, `n_merged_suspected ≥ 1`); `test_orientation_swap_preserves_area` (TileSpec 600×300 for 300×600 tiles → same area within 0.1 %); `test_corner_picks_one_plane` (two renders composited side by side with different yaw → inlier tiles all from one wall); `test_too_few_tiles_returns_none` (8 detections → `None`); `test_vertical_running_bond` (transposed bond fits, `transposed is True`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Quads: outer contour → convex hull → `approxPolyDP` with ε from 1 % to 10 % of perimeter until 4 vertices; centre = diagonal intersection; reject solidity < 0.85 and area > 1.7× / < 0.4× the median of the 8 nearest quads (> 1.7× counts as merged). Fit, run once normally and once with x/y transposed, keep more inliers then lower residual:

```text
seed = complete quad nearest the median centre; cell = (w,h) or (h,w) to match seed side ratio
H = perspective(seed corners → cell rectangle); r = 2.5·max(pitch)
repeat until r covers all quads (r *= 1.6), then twice more:
    P = H(centres within r of seed, in plane)
    j = round((P.y - ch/2)/py); per row: o_j = circular mean of frac((P.x - cw/2)/px)·px (seed row 0)
    i = round((P.x - cw/2 - o_j)/px); targets = (o_j + i·px + cw/2, j·py + ch/2)
    keep the closest quad per (i,j); H = findHomography(centres, targets, RANSAC, 0.2·min(pitch))
final least-squares H on inliers; residual = RMS image-px error of targets mapped back
straightness = RMS distance of inlier centres from per-row fitted lines (rows with ≥4 tiles)
```
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `"Fit tile lattice homography from SAM masks"`.

### Task 4: Area, exclusions and uncertainty

**Files:**
- Create: `measure/area.py`
- Test: `tests/test_area.py`

**Interfaces:**
- Consumes: `LatticeFit`, detections, concept detections `dict[str, list[dict]]`, `TileSpec`.
- Produces:
  - `OPENING_CONCEPTS = {"door", "window"}`; other concepts → `not_visible`.
  - `tile_tolerance_mm(source) -> float` (`box_label` 0.5, `tape` 1.0, `act`/`user` 1.5); `GROUT_TOLERANCE_MM = 1.0`.
  - `@dataclass AreaResult(tiled_area_m2, full_tiles, partial_tiles_equiv, completed_cells, undetected_m2, border_fraction, sigma_random_m2, sigma_system_m2, excluded: list[ExcludedRegion], region_px: list[np.ndarray], completed_px: list[np.ndarray], partial_ids: list[str])`.
  - `measure_area(fit, detections, image_size, tile, concepts=None, *, seed=0) -> AreaResult`.

- [ ] **Step 1: Failing tests** — `test_full_wall_in_frame` (frontal and yaw 25° walls, fake masks: area within 1 %, `abs(error) ≤ 2·sqrt(σr²+σs²)`, `border_fraction == 0`); `test_wall_cut_by_frame` (fill 1.3 → `border_fraction > 0.02`); `test_door_opening` (door concept polygon → one `opening` region within 5 % of 1.6 m², not counted in area); `test_occluder_allowance` (bottom band 600 mm hidden → `not_visible` area ≥ 0.95·truth hidden); `test_hole_filling_and_allowance` (drop a 2×2 block → `completed_cells == 4`, area within 1 %; drop a 4×4 block → `undetected_m2` ≈ 16 cells and listed as `not_visible`); `test_mosaic_area` (25×25 mm tiles, 2 mm grout, 600×600 mm panel → within 2 %); `test_sigma_system_formula` (σs == area·(δ/px + δ/py), δ = hypot(0.5, 1.0) for `box_label`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Plane raster at `res = clip(min(pitch)/60, 1, 5)` mm/px, size capped at 4000 px (raise `res` if needed). Cells of inlier tiles filled; partial and non-inlier masks warped to the plane and kept only if they fit inside one cell and touch the inlier region, dilated by `grout/2`; enclosed holes via `scipy.ndimage.binary_fill_holes` restricted to components ≤4 cells (filled, counted in `completed_cells`) or larger (→ `undetected_m2`, `ExcludedRegion(label="undetected", reason="not_visible")`); intersect with the warped image frame. `border_fraction` = share of region outline within 3 px of the image border. σr: 64 bootstrap homographies over inlier centres (`np.random.default_rng(seed)`) applied to the region outline, std of polygon areas, in quadrature with `perimeter_mm × mm_per_px`. Openings: concept ∩ region bounding box − region. Occluders: warped silhouette ∩ region x-band.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `"Compute tiled area, exclusions and uncertainty in the wall plane"`.

### Task 5: Overlays and animation

**Files:**
- Create: `measure/overlay.py`
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: `render_overlay(image, fit, area, *, wall_id, status, warnings, out_path) -> Path`; `render_failure(image: Image.Image | None, *, wall_id, reasons: list[str], out_path) -> Path`; `render_animation(image, fit, area, *, wall_id, out_path, fps=24, seconds=6.0) -> Path` (`.gif` via Pillow, `.mp4` via OpenCV `mp4v`).

- [ ] **Step 1: Failing tests** — `test_overlay_written` (PNG exists, decodes, long side ≤2000, differs from the source); `test_failure_without_image` (`image=None` → PNG with banner, 1200×800); `test_animation_frames` (gif has ≥ `fps·seconds·0.9` frames; last frame equals the static overlay size).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Inlier tiles: translucent teal fill + outline + centre dot, numbered in (j, i) order when ≤200 tiles; partial tiles amber; completed cells dashed (cell rectangles mapped with `fit.to_image`); exclusions grey with label; region outline white; caption panel `f"{wall_id} · {area:.2f} ± {2σ:.2f} m² (2σ)"` plus tile count and tile size; status banner for `partial`. Animation lights tiles in (j, i) order with a running counter, ends on the static overlay.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `"Render measurement overlays and tile animation"`.

### Task 6: Public API, status rules and CLI

**Files:**
- Create: `measure/wall.py`, `measure/cli.py`; Modify: `measure/__init__.py`
- Test: `tests/test_measure_wall.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4, 5.
- Produces (re-exported from `measure`):
  - `DEFAULT_EXCLUDE = ("door", "mirror", "window", "bathtub")`
  - `measure_wall(image_path: str, tile: TileSpec, wall_id: str, exclude_concepts: Sequence[str] | None = None, *, output_dir: str | Path | None = None, segmenter: Callable[[Image.Image, Sequence[str]], Segmentation] | None = None) -> WallMeasurement`
  - `measure_room(walls: list[tuple[str, str]], tile: TileSpec, *, output_dir=None, segmenter=None) -> RoomMeasurement`
  - `count_objects(image_path: str, concept: str, *, output_dir=None, segmenter=None) -> ObjectCount`
  - Warning codes: `unreadable_image`, `segmentation_failed`, `too_few_tiles`, `lattice_fit_failed`, `high_residual`, `wall_out_of_frame`, `undetected_area`, `merged_tiles`, `exclusions_unavailable`.
  - Overlay path: `<output_dir or ACTCHECK_OUTPUT_DIR/measure>/<wall_id>-<sha256[:8]>.png`.

- [ ] **Step 1: Failing tests** (fake segmenter wraps `render_wall` + `fake_detections`) — `test_measured_wall` (status `measured`, `quality.method == "sam_lattice"`, area within 1 %, overlay exists); `test_unreadable_image` (text file → `unavailable`, all area fields `None`, `unreadable_image`, overlay exists); `test_segmentation_error` (segmenter raises `SegmentationError` → `unavailable`, `segmentation_failed`); `test_too_few_tiles`; `test_out_of_frame_wall_is_partial`; `test_room_aggregation` (two measured walls + one unavailable: total = sum of two, σ_total = sqrt(σr1²+σr2²) + σs1 + σs2, `status == "partial"`, `unverified_walls == ["w3"]`); `test_deterministic` (two runs → identical `model_dump_json()`); `test_cli_wall_prints_json` (`measure.cli.main(["wall", path, "--tile", "300x600"], segmenter=fake)` returns 0 and stdout parses as `WallMeasurement`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Status: `unavailable` if unreadable, segmentation error, fit `None`, inliers < 12, or `residual_px > 0.25·tile_px`; `partial` if `border_fraction > 0.02`, `undetected_m2 > 0.05·area`, or `residual_px > 0.08·tile_px`; else `measured`. Every unexpected exception becomes `unavailable` + `internal_error:<Type>`. Room: totals over walls with an area; σ random in quadrature, systematic linear; `hidden_area_m2` = Σ `not_visible`; every non-`measured` wall in `unverified_walls`. CLI: `python -m measure.cli wall PHOTO --tile 300x600 [--grout 2] [--source box_label] [--wall-id W] [--exclude ...] [--out DIR] [--animate]`; `room --tile 300x600 W1=a.jpg W2=b.jpg`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check .` → PASS. **Step 5: Commit** `"Expose measure_wall/measure_room with status rules and CLI"`.

### Task 7: Real-photo behaviour on the 20 reference walls

**Files:** Create `validation/reference_run.py`; outputs `outputs/reference_run/` (ignored).

- [ ] **Step 1:** Run `measure_wall` on all 20 photos with a nominal `TileSpec(100,100,source="user")` and the four default exclusions (≈80 new requests, ≈$0.20; tile requests are cached). Record status, warnings, inliers, residual, straightness per photo to `results.csv` + a contact sheet of overlays.
- [ ] **Step 2:** Inspect the contact sheet. For each wrong behaviour (fit on the wrong plane, missed refusal, broken overlay), add a regression test reproducing it with synthetic data in the owning task's test file, fix, re-run.
- [ ] **Step 3:** Commit `"Run measurement on reference photos; fix observed failures"`. Area numbers from this run are never reported (no physical scale).

### Task 8: Synthetic accuracy table (offline sweep + real SAM)

**Files:** Create `validation/synthetic_eval.py`; Test `tests/test_synthetic_eval.py`.

- [ ] **Step 1: Failing test** `test_sweep_offline_small` (3 walls via fake masks → table rows with `truth_m2`, `measured_m2`, `error_pct`, `within_2sigma`, `kind == "synthetic-masks"`).
- [ ] **Step 2: Implement** `sweep(walls, mode)` with `mode in {"masks", "sam"}`; a fixed list of 16 walls covering frontal/oblique (yaw ≤35°, pitch ≤15°), stack/running, 300×600 / 200×200 / 100×300 / 25 mm mosaic, gloss on/off, door, bottom occluder. Writes `outputs/synthetic_eval/{results.csv,summary.md,roc_input.json}`.
- [ ] **Step 3: Run** offline masks mode (40 walls), then `--mode sam` on the 16 renders (≈190 requests, ≈$0.50). Report MAPE, median error, max error, 2σ coverage; label every row synthetic.
- [ ] **Step 4: Commit** `"Add synthetic accuracy evaluation"`.

### Task 9: Field validation, planted ROC and capture protocol

**Files:** Create `validation/run_validation.py`, `validation/roc.py`, `validation/FIELD_PROTOCOL.md`; Test `tests/test_validation_scripts.py`.

**Interfaces:** `roc_table(rows: list[dict], inflations=np.arange(0.025, 0.301, 0.025), ks=np.arange(0, 5.01, 0.25)) -> dict` where each row has `id`, `truth_m2`, `measured_m2`, `sigma_m2`, `hidden_m2`, `kind`; flag rule `billed > measured + k·σ + hidden`, negatives are `billed = truth`.

- [ ] **Step 1: Failing tests** — `test_roc_perfect_measurement` (σ small, error 0 → AUC 1.0, min detectable inflation at k=2 ≤ 5 %); `test_roc_labels_planted` (output marks `"planted": true`); `test_field_table` (CSV with two walls + fake measurer → per-wall `abs_error_pct`, room total, `n_walls == 2`).
- [ ] **Step 2: Implement.** `run_validation.py` reads `data/private/rooms/rooms.csv` (columns of `validation/rooms.csv`) and `data/private/rooms/<room_id>/<wall_id>.jpg`, writes `outputs/validation/field_results.{csv,md}` and ROC input. `FIELD_PROTOCOL.md`: laser/tape procedure, tile size source, photo rules (whole tiled wall in frame with margin, main camera, roughly frontal, one photo per wall), privacy rules.
- [ ] **Step 3: Run** ROC on the synthetic SAM results; **Step 4: Commit** `"Add field validation, planted-inflation ROC and capture protocol"`.

### Task 10: Handoff and documentation

**Files:** Modify `measure/README.md`, `validation/README.md`, `README.md`, `tests/README.md`; create `data/samples/measure_example.json` + `data/samples/measure_example.png` (synthetic wall only).

- [ ] **Step 1:** `measure/README.md`: API, statuses and warning codes with the agent behaviour each implies, JSON example, overlay contract, CLI, cost/latency per wall, limitations (tile size trusted, single plane, no curved walls/herringbone).
- [ ] **Step 2:** Results sections with the numbers from Tasks 7–9, each labelled synthetic / planted / field (N).
- [ ] **Step 3: Verify** `uv run pytest -q && uv run ruff check . && uv run ruff format --check measure validation tests`; whole-branch review by one fresh reviewer; fix findings.
- [ ] **Step 4: Commit** `"Document measurement API and validation results"`.

### Stretch: classical-grout ablation

`validation/ablation.py`: adaptive-threshold grout segmentation → connected components → the same lattice/area pipeline (`quality.method = "fallback_grout"`), on the synthetic set and reference photos. Only after Task 10.
