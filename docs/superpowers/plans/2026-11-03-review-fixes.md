# Measurement Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the paths where `measure_wall` returns a confidently wrong `measured` area (found by the
whole-branch review), so `agent/compare.py` cannot wrongly accuse or wrongly clear a contractor, before
the Nov 4 demo.

**Architecture:** Targeted changes in `measure/area.py`, `measure/wall.py`, `measure/sam_client.py` and
`measure/overlay.py` on top of `main` (which now includes teammate A's retry and parallel-room changes).
Each review finding gets a regression test built from the reviewer's reproduction (physically consistent
side-wall/floor scenes move into `validation/synthetic.py`).

**Tech Stack:** Python 3.12, numpy, OpenCV, Pillow, scipy, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-02-wall-measurement-design.md` (unchanged); review findings
C1–C3, I1–I4 and minors are summarised in each task.

## Global Constraints

- No changes to `schemas/` or `agent/` (teammate A's); the only file of A's touched is one `ENV` line in `Dockerfile`.
- A wrong number must fail towards `partial` (agent answers `incomplete`), never towards a confident `measured`.
- Every σ stays 1σ; the overlay and validation now show `2·(σr + σs)`, the bound `compare.py` applies to one wall.
- No new SAM spending except re-running cached sweeps; no new dependencies.
- Branch `measure/review-fixes`, local commits per task; push only when the user asks.

## Review Focus

- Glass shower screen labelled `door` over visible tiles → tiles still counted, wall flagged (Task 1).
- Neighbouring tiled wall in the frame → its tiles not counted (Task 3).
- SAM misses the outer tiles of a wall that is fully in frame → `partial`, not `measured` low (Task 4).
- 200 MP phone photo → no exception (Task 6).
- Script without `__main__` guard → no duplicate SAM requests from worker processes (Task 6).

---

### Task 1: Exclusion masks never delete visible lattice tiles (C2)

**Files:** `measure/area.py`, `measure/wall.py`, `measure/overlay.py` (warning text); tests in `tests/test_area.py`, `tests/test_measure_wall.py`.

- [ ] Failing tests: `test_door_mask_over_visible_tiles_keeps_them` (door mask over a 0.8×1.9 m block of detected tiles → area within 1 % of truth, warning `exclusion_overlaps_tiles`); `test_floor_mask_over_bottom_rows_keeps_lattice` (floor mask over the bottom two rows → area within 1 %); `test_mask_over_whole_wall_is_not_measured_zero` (mirror mask over everything → status never `measured` with 0 m²).
- [ ] Implement: a lattice cell is clipped by exclusion masks only when they cover < 50 % of it (L-shaped tiles at door corners); cells covered ≥ 50 % stay counted and are recorded as conflicts (`AreaResult.conflict_tiles`). `wall.py`: warning `exclusion_overlaps_tiles` when conflicts exceed 10 % of lattice tiles → `partial`; zero area with a fit → `unavailable` (`lattice_fit_failed`).
- [ ] Run `uv run pytest -q` → green; commit.

### Task 2: Missing exclusion checks make the wall partial (C3)

**Files:** `measure/wall.py`, `tests/test_measure_wall.py`, `measure/README.md`.

- [ ] Change `test_exclusions_unavailable_still_measures` → `test_exclusions_unavailable_is_partial` (status `partial`, area kept, warning present); watch it fail.
- [ ] Add `exclusions_unavailable` to `PARTIAL_WARNINGS`; update the README warning table. Commit.

### Task 3: Only joint-aligned, tile-sized masks count beyond the lattice (C1)

**Files:** `validation/synthetic.py` (`side_wall_detections`, `floor_detections`: tiles of a perpendicular plane seen by the same camera), `measure/area.py`, tests in `tests/test_area.py`.

- [ ] Failing tests: `test_adjacent_wall_tiles_not_counted` (inside corner, equal tiles on both walls, 400 mm and 1000 mm returns → area within 3 % of the main wall or status-relevant `undetected`); `test_tiled_floor_not_counted_without_floor_mask` (perpendicular tiled floor, no floor concept → within 3 %); keep `test_strip_beside_door_and_row_gaps_are_counted` and the lattice corner test green.
- [ ] Implement in `_accept`: a non-lattice mask must be at most 1.15 pitch on both axes, axis-aligned, with parallel top/bottom and left/right edges in the plane (slope ≤ 0.03), and on this lattice's joint lines (`_on_joint_lines`). Masks reached by growing from the cells need the weak alignment (one full row band, or a row edge plus a column edge); masks not connected to the cells need a full row band and a column edge.
- [ ] Commit.

### Task 4: Uncounted tiles beside the counted area make the wall partial (I1)

**Files:** `measure/area.py` (`measure_area(..., image=None)`), `measure/wall.py`, `measure/overlay.py`, tests.

- [ ] Failing tests: `test_missed_outer_tiles_are_partial` (fully framed wall, SAM masks only for the central 60 % → status `partial`, warning `uncounted_tiles`); `test_out_of_frame_with_missed_border_tiles_is_partial` (fill 1.3, masks of frame-cut tiles removed → `wall_out_of_frame`); `test_clean_wall_stays_measured` (no new warning on a complete wall with a painted margin).
- [ ] Implement: probe the ring of lattice cells around the counted region (not excluded, ≥ 50 % in frame) in the image; a cell looks like a tile when its interior colour is within the matched tiles' spread (median ± max(3·MAD, 8) per Lab channel). ≥ max(2, 20 %) tile-like ring cells → `uncounted_tiles` (partial). Region within 0.75 tile of the photo border → `wall_out_of_frame`.
- [ ] Commit.

### Task 5: Inferred area carries uncertainty and has an absolute cap (I2)

**Files:** `measure/area.py`, `tests/test_area.py`.

- [ ] Failing test `test_completed_area_widens_sigma_and_is_capped` (600×600 tiles, 2-cell untiled niche without masks → either inside 2σ or reported as `undetected`, never silently +7 %).
- [ ] Implement: completed holes and bridged gaps add half their area to σ_random (as row extensions do); holes above 0.6 m² are never completed. Commit.

### Task 6: Robustness: huge photos, worker processes, CLI, temp files, container

**Files:** `measure/wall.py`, `measure/sam_client.py`, `measure/cli.py`, `Dockerfile` (one `ENV`), tests.

- [ ] Failing tests: `test_huge_photo_does_not_raise` (16320×12240 PNG → no exception); `test_segment_refuses_in_worker_process` (`multiprocessing.parent_process()` patched non-None → `RuntimeError` before any request); `test_cli_bad_tile_exits_cleanly` (exit code 2, no traceback); `test_cache_writes_use_unique_temp_files`.
- [ ] Implement: allow up to 250 MP in `_load`, larger → `unavailable` `unreadable_image`; worker pool default `min(4, cpu)`, `segment()` raises inside a spawned worker; CLI tile errors through `parser.error`; temp names with pid/uuid; `ENV ACTCHECK_SAM_WORKERS=2` in the Dockerfile. Commit.

### Task 7: One uncertainty convention, re-validated numbers, docs

**Files:** `measure/overlay.py`, `validation/synthetic_eval.py`, `validation/run_validation.py`, `validation/synthetic_eval.py` (corner/floor scenes in masks mode), `measure/README.md`, `validation/README.md`, `README.md`.

- [ ] Caption and validation rows use `σr + σs` (what `compare.py` applies to a wall); add 10 corner and 5 floor scenes to the masks sweep; re-run masks sweep, cached SAM sweep, reference run and ROC; update the numbers and the warning table; field protocol: neighbouring walls may be visible but the measured wall must be whole.
- [ ] `uv run pytest -q`, `ruff check`, `ruff format --check`; commit; one fresh review of the branch diff.

## Outside this plan (user and teammate)

- Field check: measure and photograph 1–2 walls per `validation/FIELD_PROTOCOL.md`, then `uv run python -m validation.run_validation`.
- Merge A's `railway.json` commit (`c7d8d82`) and confirm the Railway deploy answers `/api/health`.
- Open a PR `measure/review-fixes` → `main` after Task 7; tell A that `compare.py` ignores warnings, so statuses carry every safety signal, and that `ObjectCount` cannot say "unavailable".
- Video: run `measure.cli wall <your wall photo> --tile WxH --animate` for the tile-by-tile clip.
