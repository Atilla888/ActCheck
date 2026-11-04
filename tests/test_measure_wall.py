"""Public measurement API: statuses, refusals, room aggregation, determinism and CLI."""

import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

import measure
from measure.cli import main
from measure.lattice import fit_lattice
from measure.sam_client import Segmentation, SegmentationError
from schemas.measure import RoomMeasurement, TileSpec, WallMeasurement
from validation.synthetic import SyntheticWall, fake_concept, fake_detections, render_wall

TILE = TileSpec(width_mm=200, height_mm=200, grout_mm=2, source="box_label")


def photo(tmp_path, name, **wall_args):
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, **wall_args)
    render = render_wall(wall)
    path = tmp_path / f"{name}.png"
    Image.fromarray(render.image).save(path)
    return path, render


def fake_segmenter(render, *, keep=None, concepts_fail=False):
    size = (render.image.shape[1], render.image.shape[0])
    tiles = fake_detections(render, seed=render.wall.seed)
    if keep is not None:
        tiles = tiles[:keep]

    def segment(image, concepts):
        assert image.size == size
        if concepts and concepts_fail:
            raise SegmentationError("SAM request rejected (HTTP 429)")
        found = {concept: [] for concept in concepts}
        if "bathtub" in found and render.occluder_polygon is not None:
            found["bathtub"] = [fake_concept(render.occluder_polygon, "bathtub", size)]
        return Segmentation(source_size=size, tiles=tiles, concepts=found, requests=1)

    return segment


def test_measured_wall(tmp_path):
    path, render = photo(tmp_path, "w1", yaw_deg=15, seed=41)
    result = measure.measure_wall(
        str(path), TILE, "w1", output_dir=tmp_path, segmenter=fake_segmenter(render)
    )
    assert result.status == "measured"
    assert result.quality.method == "sam_lattice"
    assert result.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)
    assert result.warnings == []
    assert Path(result.overlay_png).exists()


def test_large_other_surface_is_partial(tmp_path):
    path, render = photo(tmp_path, "w1", seed=41, fill=0.7)
    size = (render.image.shape[1], render.image.shape[0])
    tiles = fake_detections(render, seed=41)
    fit = fit_lattice(tiles, TILE)
    edge = max(fit.tiles, key=lambda t: t.i).i + 1
    for column in (edge, edge + 1):  # narrower than a tile, so they stay off the lattice
        for j in sorted({t.j for t in fit.tiles}):
            x0, y0, x1, y1 = fit.cell_rect(column, j)
            x1 = x0 + 0.55 * (x1 - x0)
            polygon = fit.to_image([[x0 + 5, y0 + 5], [x1, y0 + 5], [x1, y1 - 5], [x0 + 5, y1 - 5]])
            cv2.fillPoly(render.image, [np.round(polygon).astype(np.int32)], (20, 60, 200))
            detection = fake_concept(polygon, "tile", size)
            detection["id"] = f"other:{column}:{j}"
            tiles.append(detection)
    Image.fromarray(render.image).save(path)
    result = measure.measure_wall(
        str(path),
        TILE,
        "w1",
        (),
        output_dir=tmp_path,
        segmenter=lambda image, concepts: Segmentation(size, tiles, {}, 1),
    )
    assert result.status == "partial"
    assert "other_surface" in result.warnings
    assert [r.reason for r in result.excluded if r.label == "other_surface"] == ["not_visible"]
    assert result.tiled_area_m2 < 1.01 * render.tiled_area_m2  # none of the columns was counted


def test_unreadable_image(tmp_path):
    path = tmp_path / "notes.jpg"
    path.write_text("not an image")
    result = measure.measure_wall(str(path), TILE, "w2", output_dir=tmp_path)
    assert result.status == "unavailable"
    assert result.tiled_area_m2 is None and result.sigma_random_m2 is None
    assert result.full_tiles is None
    assert "unreadable_image" in result.warnings
    assert Image.open(result.overlay_png).size == (1200, 800)


def test_segmentation_error(tmp_path):
    path, _ = photo(tmp_path, "w3", seed=42)

    def failing(image, concepts):
        raise SegmentationError("1 request(s) not cached and META_API_KEY is not set")

    result = measure.measure_wall(str(path), TILE, "w3", output_dir=tmp_path, segmenter=failing)
    assert result.status == "unavailable"
    assert "segmentation_failed" in result.warnings
    assert Image.open(result.overlay_png)


def test_too_few_tiles(tmp_path):
    path, render = photo(tmp_path, "w4", seed=43)
    result = measure.measure_wall(
        str(path), TILE, "w4", output_dir=tmp_path, segmenter=fake_segmenter(render, keep=6)
    )
    assert result.status == "unavailable"
    assert "too_few_tiles" in result.warnings
    assert result.tiled_area_m2 is None


def test_out_of_frame_wall_is_partial(tmp_path):
    path, render = photo(tmp_path, "w5", fill=1.3, seed=44)
    result = measure.measure_wall(
        str(path), TILE, "w5", output_dir=tmp_path, segmenter=fake_segmenter(render)
    )
    assert result.status == "partial"
    assert "wall_out_of_frame" in result.warnings
    assert result.tiled_area_m2 is not None


def test_exclusions_unavailable_is_partial(tmp_path):
    path, render = photo(tmp_path, "w6", seed=45)
    result = measure.measure_wall(
        str(path),
        TILE,
        "w6",
        output_dir=tmp_path,
        segmenter=fake_segmenter(render, concepts_fail=True),
    )
    assert result.status == "partial"  # no hidden-area allowance: the agent must not accuse
    assert result.tiled_area_m2 is not None
    assert "exclusions_unavailable" in result.warnings


def test_room_aggregation(tmp_path):
    first, render_a = photo(tmp_path, "a", seed=46, occluder_h_mm=500)
    second, render_b = photo(tmp_path, "b", yaw_deg=-20, seed=47)
    missing = tmp_path / "c.jpg"
    missing.write_bytes(b"")
    queue = [fake_segmenter(render_a), fake_segmenter(render_b)]  # one call per readable wall

    def route(image, concepts):
        return queue.pop(0)(image, concepts)

    room = measure.measure_room(
        [("w1", str(first)), ("w2", str(second)), ("w3", str(missing))],
        TILE,
        output_dir=tmp_path,
        segmenter=route,
    )
    w1, w2, w3 = room.walls
    assert w3.status == "unavailable"
    assert room.status == "partial"
    assert room.unverified_walls == ["w3"]
    assert room.total_tiled_area_m2 == pytest.approx(w1.tiled_area_m2 + w2.tiled_area_m2, abs=2e-3)
    sigma = (
        math.hypot(w1.sigma_random_m2, w2.sigma_random_m2)
        + w1.sigma_system_m2
        + (w2.sigma_system_m2)
    )
    assert room.sigma_total_m2 == pytest.approx(sigma, abs=2e-3)
    hidden = [r.area_m2 for w in (w1, w2) for r in w.excluded if r.reason == "not_visible"]
    assert room.hidden_area_m2 == pytest.approx(sum(hidden), abs=2e-3)


def test_deterministic(tmp_path):
    path, render = photo(tmp_path, "w7", yaw_deg=10, seed=48)
    runs = [
        measure.measure_wall(
            str(path), TILE, "w7", output_dir=tmp_path, segmenter=fake_segmenter(render)
        ).model_dump_json()
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


def test_count_objects(tmp_path):
    path, render = photo(tmp_path, "w8", seed=49)
    size = (render.image.shape[1], render.image.shape[0])
    sockets = [
        fake_concept([[x, 100], [x + 40, 100], [x + 40, 160], [x, 160]], "socket", size)
        for x in (100, 300, 500)
    ]

    def segmenter(image, concepts):
        return Segmentation(source_size=size, tiles=[], concepts={"socket": sockets})

    result = measure.count_objects(str(path), "socket", output_dir=tmp_path, segmenter=segmenter)
    assert result.count == 3
    assert result.presence_score == pytest.approx(0.9)
    assert Image.open(result.overlay_png)


def test_cli_wall_prints_json(tmp_path, capsys):
    path, render = photo(tmp_path, "w9", seed=50)
    code = main(
        ["wall", str(path), "--tile", "200x200", "--wall-id", "w9", "--out", str(tmp_path)],
        segmenter=fake_segmenter(render),
    )
    assert code == 0
    result = WallMeasurement.model_validate(json.loads(capsys.readouterr().out))
    assert result.status == "measured"
    assert result.tile.width_mm == 200


def test_cli_room_prints_json(tmp_path, capsys):
    path, render = photo(tmp_path, "w10", seed=51)
    code = main(
        ["room", "--tile", "200x200", f"w10={path}", "--out", str(tmp_path)],
        segmenter=fake_segmenter(render),
    )
    assert code == 0
    room = RoomMeasurement.model_validate(json.loads(capsys.readouterr().out))
    assert room.status == "measured" and len(room.walls) == 1


def test_floor_requested_with_exclusions_only(tmp_path):
    path, render = photo(tmp_path, "w11", seed=52)
    requested = []
    inner = fake_segmenter(render)

    def recording(image, concepts):
        requested.append(tuple(concepts))
        return inner(image, concepts)

    measure.measure_wall(str(path), TILE, "w11", output_dir=tmp_path, segmenter=recording)
    measure.measure_wall(str(path), TILE, "w11", [], output_dir=tmp_path, segmenter=recording)
    assert requested[0] == (*measure.DEFAULT_EXCLUDE, "floor")
    assert requested[1] == ()


def test_mask_over_whole_wall_is_not_measured_zero(tmp_path):
    path, render = photo(tmp_path, "w12", seed=53)
    size = (render.image.shape[1], render.image.shape[0])
    whole = cv2.perspectiveTransform(
        np.array([[[-50, -50], [2450, -50], [2450, 2150], [-50, 2150]]], float),
        render.plane_to_image,
    )[0]
    inner = fake_segmenter(render)

    def segmenter(image, concepts):
        result = inner(image, concepts)
        result.concepts["mirror"] = [fake_concept(whole, "mirror", size)]
        return result

    result = measure.measure_wall(str(path), TILE, "w12", output_dir=tmp_path, segmenter=segmenter)
    assert result.status == "partial"
    assert "exclusion_overlaps_tiles" in result.warnings
    assert result.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)


def central_segmenter(render, keep):
    """SAM saw only part of the wall: masks for tiles whose (i, j) passes keep()."""
    size = (render.image.shape[1], render.image.shape[0])
    tiles = [
        d
        for d in fake_detections(render, seed=render.wall.seed)
        if d["truth"] and keep(d["truth"]["i"], d["truth"]["j"])
    ]

    def segment(image, concepts):
        return Segmentation(source_size=size, tiles=tiles, concepts={c: [] for c in concepts})

    return segment


def test_missed_outer_tiles_are_partial(tmp_path):
    path, render = photo(tmp_path, "w13", yaw_deg=10, seed=54)  # 12 x 11 tiles, all in frame
    segmenter = central_segmenter(render, lambda i, j: 2 <= i <= 9 and 2 <= j <= 8)
    result = measure.measure_wall(str(path), TILE, "w13", output_dir=tmp_path, segmenter=segmenter)
    assert result.status == "partial"
    assert "uncounted_tiles" in result.warnings


def test_out_of_frame_with_missed_border_tiles_is_partial(tmp_path):
    path, render = photo(tmp_path, "w14", fill=1.3, seed=55)
    size = (render.image.shape[1], render.image.shape[0])
    tiles = [d for d in fake_detections(render, seed=55) if d["truth"] and not d["edge_truncated"]]

    def segmenter(image, concepts):
        return Segmentation(source_size=size, tiles=tiles, concepts={c: [] for c in concepts})

    result = measure.measure_wall(str(path), TILE, "w14", output_dir=tmp_path, segmenter=segmenter)
    assert result.status == "partial"
    assert "wall_out_of_frame" in result.warnings or "uncounted_tiles" in result.warnings


@pytest.mark.parametrize("seed", [56, 57, 58])
def test_clean_wall_stays_measured(tmp_path, seed):
    path, render = photo(tmp_path, f"w{seed}", yaw_deg=12, gloss=0.4, seed=seed)
    result = measure.measure_wall(
        str(path), TILE, "w", output_dir=tmp_path, segmenter=fake_segmenter(render)
    )
    assert result.status == "measured", result.warnings


def test_huge_photo_does_not_raise(tmp_path, monkeypatch):
    from PIL import Image as PILImage

    path = tmp_path / "huge.png"
    PILImage.new("RGB", (400, 300), "white").save(path)
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 50_000)  # opening trips the bomb guard
    result = measure.measure_wall(str(path), TILE, "huge", output_dir=tmp_path)
    assert result.status == "unavailable" and "unreadable_image" in result.warnings


def test_cli_bad_tile_exits_cleanly(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        main(["wall", str(tmp_path / "x.jpg"), "--tile", "abc"])
    assert stop.value.code == 2
    assert "300x600" in capsys.readouterr().err


def lit_photo(tmp_path, name, wall, missed, light):
    """A photo whose missed tiles sit in shadow or glare (why SAM missed them), and the masks."""
    render = render_wall(wall)
    image = render.image.astype(np.float32)
    region = np.zeros(image.shape[:2], np.uint8)
    for tile in render.tiles:
        if (tile.i, tile.j) in missed:
            x0, y0, x1, y1 = tile.cell_mm
            corners = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], np.float64)
            cell = cv2.perspectiveTransform(corners, render.plane_to_image)[0]
            cv2.fillPoly(region, [np.round(cell).astype(np.int32)], 1)
    lit = region.astype(bool)
    if light == "shadow":
        image[lit] *= 0.7
    elif light == "glare":
        image[lit] = 0.5 * image[lit] + 0.5 * 255
    path = tmp_path / f"{name}.png"
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(path)
    size = (render.image.shape[1], render.image.shape[0])
    tiles = [
        d
        for d in fake_detections(render, seed=wall.seed)
        if d["truth"] and (d["truth"]["i"], d["truth"]["j"]) not in missed
    ]

    def segmenter(image, concepts):
        return Segmentation(source_size=size, tiles=tiles, concepts={c: [] for c in concepts})

    return path, render, segmenter


@pytest.mark.parametrize("light", ["even", "shadow", "glare"])
@pytest.mark.parametrize(
    ("tile", "seed", "side"),
    [(300, 84, "left"), (600, 82, "bottom"), (150, 83, "left"), (300, 85, "lower right")],
)
def test_one_sided_miss_is_not_measured_low(tmp_path, tile, seed, side, light):
    """SAM misses one column, the cut bottom row or half a column: never `measured` low."""
    wall = SyntheticWall(tile_w_mm=300 if tile == 600 else tile, tile_h_mm=tile, seed=seed)
    tiles = {(t.i, t.j) for t in render_wall(wall).tiles}
    rows, columns = max(j for _, j in tiles), max(i for i, _ in tiles)
    missed = {
        "left": {(i, j) for i, j in tiles if i == 0},
        "bottom": {(i, j) for i, j in tiles if j == rows},
        "lower right": {(i, j) for i, j in tiles if i == columns - 1 and j > rows // 2},
    }[side]
    path, render, segmenter = lit_photo(tmp_path, f"m{seed}", wall, missed, light)
    spec = TILE.model_copy(update={"width_mm": wall.tile_w_mm, "height_mm": wall.tile_h_mm})
    result = measure.measure_wall(str(path), spec, "m", output_dir=tmp_path, segmenter=segmenter)
    if result.status == "measured":  # then it must be within the bound compare.py applies
        bound = 2 * (result.sigma_random_m2 + result.sigma_system_m2)
        assert abs(result.tiled_area_m2 - render.tiled_area_m2) <= bound, result.warnings


def test_thin_missed_sliver_stays_measured(tmp_path):
    """SAM missed a cut sliver a few millimetres wide along one wall end: inside the bound, so
    the probe must not make the wall partial (sweep wall 2)."""
    from validation.synthetic_eval import _mask_segmenter, random_walls

    wall = random_walls(40)[2]
    render = render_wall(wall)
    path = tmp_path / "sliver.png"
    Image.fromarray(render.image).save(path)
    spec = TileSpec(width_mm=wall.tile_w_mm, height_mm=wall.tile_h_mm, grout_mm=wall.grout_mm,
                    source="box_label")  # fmt: skip
    result = measure.measure_wall(
        str(path), spec, "s", output_dir=tmp_path, segmenter=_mask_segmenter(render)
    )
    assert result.status == "measured", result.warnings
    bound = 2 * (result.sigma_random_m2 + result.sigma_system_m2)
    assert abs(result.tiled_area_m2 - render.visible_tiled_area_m2) <= bound
