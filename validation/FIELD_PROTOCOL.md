# Field protocol: laser vs ActCheck on 1–2 tiled walls

A small-N check of the measured tiled area against your own laser or tape measurement (target:
room error ≤ 3 %). Photos, measurements and consent notes stay in `data/private/`, which is
git-ignored.

## Before you start

- Get the owner's consent to photograph and measure, and note it in `data/private/`.
- Pick walls you can photograph **whole at 1× from 2–3 m**. A half-tiled wall or a kitchen
  backsplash (with the counter cleared) is ideal. Prefer walls with nothing in front of the tiles.

## Measure each tiled wall

1. Measure the width and height of the **tiled area**, not of the room, with a laser (or a tape,
   ±5 mm). Measure each dimension in two places and use the mean.
2. Measure each opening separately (door, window, untiled niche): width × height.
3. `laser_area_m2` = width × height − openings. Write the raw numbers in `notes`, for example
   `2.40x2.10 minus door 0.80x2.00`. Don't use commas in notes.
4. If a bathtub, cabinet or mirror covers part of the tiles, measure only the visible tiled part
   (for example, above the bathtub rim) and note what is hidden and its size, for example
   `bathtub 1.70x0.55 hidden`. Also note any toilet or sink standing in front of the tiles.

## Tile size

- **Box label (preferred):** use the printed size and set `tile_source=box_label`. If the label
  also gives a work size in mm (for example 298×598), use that.
- **No box:** measure one tile edge to edge on both sides (±1 mm) and set `tile_source=tape`.
- **Grout:** measure from one tile's edge to the same edge three tiles along (that span is
  3 tiles + 3 joints). Then `grout_mm` = span ÷ 3 − tile size. Leave it empty if unsure; the
  default is 2 mm.

## Photo: one per wall

- Get the **whole tiled area in frame, with a margin on every side** (some ceiling, floor or
  neighbouring wall visible; tiles of a neighbouring wall or the floor are not counted). If the photo edge cuts tiles, the wall is reported `partial`, and a
  partial wall can't pass the gate.
- Use the **main camera (1×)**, not the ultra-wide (0.5×), which bends the grout lines.
- Shoot **as frontally as possible**: face the middle of the wall from 2–3 m with the phone
  upright, and turn on the grid or level. Landscape or portrait are both fine.
- Use even light: all room lights on, **flash off** (glare on glossy tiles hides the joints).
- Keep people, faces and documents out of the frame. Take 2–3 shots and keep the sharpest.
- Save as JPEG at full resolution (iPhone: Settings → Camera → Formats → Most Compatible), or
  convert a HEIC with `sips -s format jpeg IMG_1234.HEIC --out w1.jpg`. Copy the originals by
  AirDrop or cable, not through a messenger.

## Files

```text
data/private/rooms/rooms.csv
data/private/rooms/r1/w1.jpg      <room_id>/<wall_id>.jpg (.jpeg and .png also work)
data/private/rooms/r1/w2.jpg
```

`rooms.csv` uses the `validation/rooms.csv` columns plus the optional `grout_mm` and
`tile_source` columns. `finish` is gloss or matte; `grout` is the joint colour, light or dark.
Use short anonymous ids and `.` as the decimal point:

```csv
room_id,wall_id,laser_area_m2,tile_w_mm,tile_h_mm,finish,grout,notes,grout_mm,tile_source
r1,w1,4.62,300,600,gloss,light,2.20x2.10,2,box_label
r1,w2,3.44,300,600,gloss,light,2.40x2.10 minus door 0.80x2.00,2,box_label
```

## Privacy

- Keep everything under `data/private/` and `outputs/`, which are git-ignored. Check with
  `git check-ignore -v data/private/rooms/rooms.csv`, which should print a matching rule, and
  never `git add -f` these files.
- Keep names, addresses and faces out of photos, ids, file names and notes. Only anonymised rows
  that the owner approved go into the public `validation/rooms.csv`. Don't publish overlays of
  private rooms.

## Run from the repo root

```sh
uv run python -m validation.run_validation
uv run python -m validation.roc outputs/validation/roc_input.json --out outputs/validation/roc.json
```

The first command sends each photo to SAM. It needs `META_API_KEY` in `.env` and makes about 15
requests per wall, which are cached for reruns. It writes `outputs/validation/field_results.csv`
and `field_results.md`, and the overlays go to `outputs/measure/`. The second command writes
`roc.json` and `roc.md`. To pool the field rows with the synthetic ones, also pass
`outputs/synthetic_eval/roc_input_sam.json`; each kind stays labelled.

## Reading the result

- A room **passes the ≤ 3 % gate** only if every wall is `measured` and |error| ≤ 3 %.
- `partial`: a number exists, but the tool doesn't trust it. `wall_out_of_frame` means retake
  with a margin. `undetected_area` means glare or covered tiles. `high_residual` means the joints
  don't fit one flat grid (lens distortion, an uneven wall, or a second wall in the frame); use
  1×, step back and shoot frontally. Partial walls are listed but not counted in MAPE.
- `unavailable`: no number. For `too_few_tiles` or `lattice_fit_failed`, retake sharper and more
  frontally, and check the tile size. `segmentation_failed` means a key or network problem.
  `unreadable_image` means the file can't be opened (for example, a HEIC renamed to `.jpg`).
- `missing_photo`: there is no file at `data/private/rooms/<room_id>/<wall_id>.jpg`.
- Open every overlay (`overlay_png` column) and check that the highlighted tiles cover exactly
  the tiled wall.
- Report the result as "field check, N = 2", not as accuracy. The ROC numbers come from planted
  (artificial) inflation of your laser values, not from real bills.
