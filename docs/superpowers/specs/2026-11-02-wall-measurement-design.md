# Wall measurement (`measure/`) — design

Date: 2026-11-02 (Asia/Almaty). Owner: B (Atilla). Status: approved scope — measurement and
validation only; A wires the API, agent and frontend.

## Goal

Turn one photo of a tiled wall plus the tile size into a tiled area in m² with an honest
uncertainty, an overlay a non-expert can check, and a clear refusal when the photo cannot
support a number. Implements the public boundary of team plan §5.1 against A's merged
`schemas/measure.py` (no schema changes).

```python
measure_wall(image_path, tile, wall_id, exclude_concepts=None) -> WallMeasurement
measure_room(walls, tile) -> RoomMeasurement
count_objects(image_path, concept) -> ObjectCount          # stretch
```

Never raises on a bad photo: failures return `status="unavailable"`, area fields `None`,
warnings, and a failure overlay. Deterministic for identical inputs (cached SAM, fixed seeds).

## Pipeline

1. **Segment** (`sam_client.py`). EXIF-orient the photo. One full-frame request plus nine
   overlapping crops (the existing 3×3, 4 % overlap strategy), each ≤1600 px, prompt `tile`.
   Same request preparation and cache key as the benchmark, so the 240 cached responses are
   reused. Masks are mapped to source pixels and deduplicated with `measure/crop_merge.py`.
   Exclusion concepts get one full-frame request each.
2. **Quads.** Per detection: outer contour → convex hull → 4-vertex polygon. Centre = diagonal
   intersection (projectively exact, insensitive to symmetric mask erosion). Reject non-quads,
   low solidity, and local area outliers (>1.7× neighbours = suspected merge, counted in
   `n_merged_suspected`). Edge-truncated masks never seed the lattice.
3. **Lattice + homography** (`lattice.py`). Seed tile near the median centre maps to one cell.
   Iteratively grow a radius: map centres to the plane, assign row index `j`, per-row offset
   (stack bond, running bond and irregular offsets), column index `i`; refit
   `H: image → plane (mm)` from centres to lattice centres with RANSAC; repeat until stable.
   Pitch is `(w+g, h+g)`. Orientation (w/h swap) and bond shear are area-preserving maps of the
   same lattice, so they cannot bias area; orientation is chosen only for display.
   Quality: inlier RMS reprojection error (`lattice_residual_px`) and row straightness
   (`lens_straightness_px`).
4. **Area** (`area.py`). Rasterise in the plane (1–5 mm/px). Region = full lattice cells of
   inlier tiles ∪ rectified partial-tile masks (grown by half a grout joint) ∪ enclosed small
   holes (≤4 cells, lattice completion), clipped to the rectified image frame. Larger
   unexplained holes become `not_visible` allowances, never measured area.
   `tiled_area_m2` counts tiles + joints (A's convention). `full_tiles` = inlier complete tiles;
   `partial_tiles_equiv` = region / cell area − full tiles.
5. **Exclusions.** Door/window → `opening` (area inside the tiling extent minus tiled area).
   Mirror, bathtub, cabinet, etc. → `not_visible`, area of the rectified silhouette inside the
   region's column band (an upper-bound allowance, as A's `compare.py` expects).
6. **Uncertainty (1σ).** Random: bootstrap of the homography over inlier centres (64 draws,
   seed 0) applied to the region polygon, plus ±1 px boundary localisation along the perimeter,
   in quadrature. Systematic: tile tolerance (box label 0.5 mm, tape 1 mm, act/user 1.5 mm) and
   grout tolerance 1 mm per pitch, `σ = A·(δp/px + δp/py)`. Room: random in quadrature,
   systematic linearly (A's schema).
7. **Status.** `unavailable`: unreadable image, segmentation error, <12 lattice inliers,
   degenerate or poorly fitting homography. `partial`: region touches the image border
   (wall continues out of frame), large undetected holes, or elevated residual. `measured`
   otherwise. `measure_room` lists every non-`measured` wall in `unverified_walls`, so A's
   comparison cannot call a line over-billed while part of the room is unverified.
8. **Overlay** (`overlay.py`). Tiles filled and numbered in lattice order, partial tiles and
   completed cells distinct, exclusions grey with labels, region outline, caption
   `4.12 ± 0.18 m² (2σ)`. Failure overlay: source image (or blank canvas) with a reshoot banner.
   Optional animation (tiles light up in order with a counter) for the video.
9. **CLI** (`cli.py`): `python -m measure.cli wall photo.jpg --tile 300x600 [--grout 2]` prints
   JSON and writes the overlay; `room` and `--animate` subcommands/options.

## Validation

- **Synthetic walls** (`validation/synthetic.py`): rendered under a pinhole camera with known
  pose, tile size, bond, grout, gloss, occluders and openings; ground-truth area known exactly.
  Two uses: (a) geometry tests with SAM-like masks (erosion, jitter, dropouts, merges, false
  positives); (b) an end-to-end run through real SAM. Always labelled synthetic.
- **Field walls** (`validation/run_validation.py`): 1–2 laser/tape-measured walls from the
  user, private photos, reported as a small-N check against the ≤3 % target.
- **Planted inflation ROC** (`validation/roc.py`): bills inflated 0–30 % over known truth;
  rule `billed > measured + k·σ + hidden`; ROC/AUC over k and the smallest inflation detected
  at k = 2. Labelled `planted`.
- **Reference photos** (Pexels): no physical scale, so only fit/refusal behaviour and overlays.

## Non-goals

FastAPI, agent loop and frontend wiring (A). Curved walls, herringbone, multi-plane fusion,
schema changes, lens calibration. The classical-grout ablation is a stretch goal.

## Risks

Wrong tile size from the user is undetectable from one photo and scales area directly — the
agent must show the tile size it used. SAM misses at the region boundary under-measure; the
overlay makes this visible and the capture guide asks for the whole wall in frame. Strong
wide-angle distortion raises the residual and downgrades the status instead of hiding error.
