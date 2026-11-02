# Measurement — Atilla / B

One photo of a tiled wall plus the tile size → tiled area in m² with a 1σ uncertainty, the
exclusions the agent must allow for, and an overlay a person can check. Implements team plan
§5.1 against `schemas/measure.py` (unchanged).

```python
from measure import measure_wall, measure_room, count_objects
from schemas.measure import TileSpec

tile = TileSpec(width_mm=300, height_mm=600, grout_mm=2, source="box_label")
wall = measure_wall("wall2.jpg", tile, "wall_2")            # never raises on a bad photo
room = measure_room([("wall_1", "w1.jpg"), ("wall_2", "w2.jpg")], tile)
sockets = count_objects("wall2.jpg", "socket")              # one SAM concept, full frame
```

`exclude_concepts` defaults to `door, mirror, window, bathtub`; pass more (`toilet`, `sink`,
`cabinet`) when the user mentions them, or `[]` to skip exclusions. Keyword-only extras:
`output_dir` (overlay folder) and `segmenter` (tests).

Examples of the exact JSON: [`data/samples/measure_example.json`](../data/samples/measure_example.json)
and [`room_example.json`](../data/samples/room_example.json) with their overlays (synthetic walls).

## How it works

1. **SAM 3.1 tiles** (`sam_client.py`): prompt `tile` on the full frame plus nine overlapping
   crops (≤1600 px each), mapped to source pixels and deduplicated (`crop_merge.py`). One
   full-frame request per exclusion concept, plus `floor`.
2. **Lattice** (`lattice.py`): masks → quadrilaterals → a homography fitted from tile centres to
   the tile lattice (pitch = tile + joint). Scale comes from the pitch, not from mask edges.
   Stack and running bond, both orientations; merged masks, cut tiles and tiles from other
   planes are rejected.
3. **Area** (`area.py`): matched tiles count one pitch cell each; cut tiles, borders and
   bands count when their rectified mask is an aligned rectangle on the wall's joint lines or
   next to counted tiles. Single missed tiles are bridged, row ends cut short by missed edge
   tiles follow their neighbours (≤2 tiles, adds uncertainty), and unexplained gaps inside the
   counted outline are reported, never silently dropped. Exclusion masks (and the floor) block
   counting.
4. **Overlay** (`overlay.py`): teal = matched tiles (numbered), amber = other counted area,
   dashed = inferred, grey = exclusions with their area, caption `A ± 2σ m² (2σ)`.

## Statuses — what the agent should do

| `status` | Meaning | Agent behaviour |
| --- | --- | --- |
| `measured` | Lattice fits, whole tiled wall in frame | Compare `tiled_area_m2 ± 2σ` + hidden allowance (`agent/compare.py`) |
| `partial` | A number exists but is not trustworthy for over-billing | `measure_room` lists the wall in `unverified_walls`, so `compare.py` answers `incomplete`; ask for a reshoot with the reasons |
| `unavailable` | No honest number; area fields are `None` | Ask for a reshoot; never treat as 0 m² |

| Warning | Status effect | Tell the user |
| --- | --- | --- |
| `wall_out_of_frame` | partial | Step back so the whole tiled wall plus a margin is in the photo |
| `undetected_area` | partial | Part of the wall was not recognised (glare, cover): retake in even light |
| `high_residual` | partial | Joints don't fit one flat grid: main camera 1×, frontal, one wall per photo |
| `merged_tiles` | — | Informational: SAM merged neighbouring tiles; the lattice compensates |
| `exclusions_unavailable` | — | Doors/mirrors/bathtubs could not be checked; no hidden allowance |
| `too_few_tiles` | unavailable | Too few whole tiles recognised: closer, sharper, check the tile size |
| `lattice_fit_failed` | unavailable | Tiles don't form one grid (curved wall, herringbone, two walls) |
| `segmentation_failed` | unavailable | SAM unreachable or no key and not cached |
| `unreadable_image` | unavailable | File can't be opened (HEIC renamed to .jpg, empty file) |

## Numbers and exclusions

- `tiled_area_m2` counts tiles plus joints (what acts bill), visible part only.
- `sigma_random_m2` (homography bootstrap, edge localisation, inferred tiles) and
  `sigma_system_m2` (tile tolerance: box label 0.5 mm, tape 1 mm, act/user 1.5 mm; joint 1 mm)
  are 1σ. `measure_room`: random in quadrature, systematic linearly.
- `excluded` with reason `opening` (door, window) is not tiled and not billed. Reason
  `not_visible` (mirror, bathtub, `undetected`) is an **upper-bound allowance**: the area may or
  may not be tiled. `RoomMeasurement.hidden_area_m2` sums them for `compare.py`.
- **Wrong tile size scales the area directly** and cannot be detected from one photo: show the
  user which tile size was used. An occluder SAM does not recognise gets no allowance; ask the
  user (voice note) what covers the lower wall and add it as hidden area.

## Overlay, files, environment

- `overlay_png` always exists: `<output_dir or $ACTCHECK_OUTPUT_DIR/measure>/<wall_id>-<sha8>.png`
  (absolute path by default). Failures get the photo (or a blank canvas) with a red banner;
  partial results get an amber banner above the photo.
- CLI: `uv run python -m measure.cli wall photo.jpg --tile 300x600 [--grout 2] [--source box_label]
  [--wall-id w1] [--exclude door mirror ...] [--out DIR] [--animate]` prints the JSON; `room
  --tile 300x600 w1=a.jpg w2=b.jpg`; `count photo.jpg --concept socket`. `--animate` writes an
  MP4 of the tiles lighting up (video and X).
- Needs `META_API_KEY` in `.env` for uncached photos. Responses and decoded masks are cached in
  `data/cache/sam_benchmark/`, so a repeated photo costs nothing and returns identical results.
- Mask decoding runs in worker processes: scripts must use `if __name__ == "__main__":`
  (otherwise it falls back to one process, slower). `ACTCHECK_SAM_WORKERS=1` disables workers.
  `ACTCHECK_FONT` sets a TrueType font for overlays (else system Arial/DejaVu, else ASCII text).
- Cost: 15 SAM images per wall (1 + 9 crops + 4 exclusions + floor) ≈ $0.04. Time: a few seconds
  when cached; uncached roughly 30–60 s per wall (SAM latency ~9 s per request, 6 in parallel).

## Validation (see [validation/README.md](../validation/README.md))

- **Synthetic, real SAM 3.1** — 16 rendered walls with exact areas: 11 `measured`, median error
  0.88 %, max 1.33 %, all within 2σ; 4 `partial` (SAM saw only part of the wall, all flagged);
  1 `unavailable` (25 mm mosaic).
- **Synthetic, SAM-like masks** — 40 random walls: 35 `measured`, median 0.57 %, max 4.86 %, all
  within 2σ.
- **Reference photos** (20 web photos, no physical scale): 14 `partial`, 6 `unavailable`, no
  area reported; overlays show plausible single-wall fits.
- **Field**: not yet measured. `validation/FIELD_PROTOCOL.md` describes the 1–2 wall check.

Synthetic accuracy is not field accuracy. Unsupported: curved walls, herringbone, walls spanning
several planes in one photo, mosaic tiles smaller than ~30 px in the photo.
