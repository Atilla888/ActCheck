"""Synthetic walls: exact ground truth, tile layout, rendering and SAM-like fake masks."""

import json
from dataclasses import replace

import numpy as np
import pytest

from measure import crop_merge as cm
from validation.synthetic import SyntheticWall, fake_concept, fake_detections, render_wall

DOOR = (800, 100, 800, 2000)
KEYS = {
    "id",
    "run_id",
    "object_id",
    "box",
    "contours",
    "confidence",
    "area_px",
    "rectangularity",
    "edge_truncated",
    "crop_boundary",
    "image_boundary",
    "candidate",
    "input_size",
    "crop_box",
    "source_size",
    "truth",
}
# Frontal 2400×2100 mm wall at fill 0.8 in a 1600×1200 frame: height-limited, 960 px per 2100 mm.
SCALE = 0.8 * 1200 / 2100


def shoelace(points):
    x, y = np.asarray(points, float).T
    return abs(x @ np.roll(y, -1) - y @ np.roll(x, -1)) / 2


def project(matrix, points):
    points = np.asarray(points, float)
    mapped = np.column_stack([points, np.ones(len(points))]) @ np.asarray(matrix).T
    return mapped[:, :2] / mapped[:, 2:]


def truths(detections):
    return [(d["truth"]["i"], d["truth"]["j"]) for d in detections if d["truth"]]


def test_ground_truth_areas():
    render = render_wall(SyntheticWall(door=DOOR))
    assert render.tiled_area_m2 == pytest.approx(5.04 - 1.6)
    assert render.opening_area_m2 == pytest.approx(1.6)
    assert render.visible_tiled_area_m2 == pytest.approx(5.04 - 1.6)
    assert render.hidden_area_m2 == 0
    assert render.occluder_polygon is None
    assert shoelace(render.door_polygon) == pytest.approx(1.6e6 * SCALE**2)
    # Tile faces inside the door, by hand: x 105+300+300+89 = 794 mm, y 501+600+600+293 = 1994 mm.
    faces = sum(shoelace(t.plane_polygon) for t in render.tiles)
    assert faces == pytest.approx(2385 * 2093 - 794 * 1994)
    # A 600 mm bottom band hides 2400×600 mm, of which the door takes 800×600 mm.
    render = render_wall(SyntheticWall(door=DOOR, occluder_h_mm=600))
    assert render.tiled_area_m2 == pytest.approx(3.44)
    assert render.hidden_area_m2 == pytest.approx(1.44 - 0.48)
    assert render.visible_tiled_area_m2 == pytest.approx(3.44 - 0.96)
    assert shoelace(render.occluder_polygon) == pytest.approx(2400 * 600 * SCALE**2)


# Tile faces by hand: stack rows are 7×300+285 mm wide; running odd rows 150+7×300+134 mm;
# rows are 3×600 mm plus a 293 mm cut row.
@pytest.mark.parametrize(
    ("bond", "count", "full", "faces"),
    [("stack", 32, 21, 2385 * 2093), ("running", 34, 21, 2385 * 1200 + 2384 * 893)],
)
def test_tiles_cover_wall(bond, count, full, faces):
    tiles = render_wall(SyntheticWall(bond=bond)).tiles
    cells = np.clip([t.cell_mm for t in tiles], 0, [2400, 2100, 2400, 2100])
    assert np.prod(cells[:, 2:] - cells[:, :2], axis=1).sum() == pytest.approx(2400 * 2100)
    assert len(tiles) == count
    assert sum(t.full for t in tiles) == full
    assert sum(shoelace(t.plane_polygon) for t in tiles) == pytest.approx(faces)


def test_running_bond_offsets():
    def offsets(bond):
        found = {}
        for tile in render_wall(SyntheticWall(bond=bond)).tiles:
            if tile.full:
                # A full tile starts half a joint (1 mm) after its cell, on a 302 mm pitch.
                offset = round((tile.plane_polygon[:, 0].min() - 1) % 302, 6)
                found.setdefault(tile.j, set()).add(offset)
        return found

    assert offsets("running") == {0: {0}, 1: {151}, 2: {0}}
    assert offsets("stack") == {0: {0}, 1: {0}, 2: {0}}


def test_fake_detections_dropout_and_merge():
    render = render_wall(SyntheticWall(tile_w_mm=100, tile_h_mm=100))
    full = {(t.i, t.j) for t in render.tiles if t.full}
    assert len(full) == 23 * 20
    seen = [key for key in truths(fake_detections(render)) if key in full]
    assert sorted(seen) == sorted(full)

    kept = [key for key in truths(fake_detections(render, dropout=0.3)) if key in full]
    assert len(kept) / len(full) == pytest.approx(0.7, abs=0.05)

    merged = fake_detections(render, merge_rate=0.1)
    median = np.median([d["area_px"] for d in merged])
    big = [d for d in merged if d["area_px"] > 1.5 * median]
    assert 0.05 * len(full) <= len(big) <= 0.15 * len(full)
    assert all(d["area_px"] / median == pytest.approx(2, rel=0.12) for d in big)
    # One mask per merged pair: the right neighbour has no mask of its own.
    keys = set(truths(merged))
    assert all((d["truth"]["i"] + 1, d["truth"]["j"]) not in keys for d in big)


def test_render_deterministic():
    wall = SyntheticWall(
        bond="running",
        yaw_deg=20,
        pitch_deg=-5,
        roll_deg=2,
        door=(1500, 300, 700, 1800),
        occluder_h_mm=400,
        gloss=0.7,
        seed=5,
    )
    first, second = render_wall(wall), render_wall(wall)
    assert first.image.shape == (1200, 1600, 3) and first.image.dtype == np.uint8
    assert first.image.tobytes() == second.image.tobytes()
    assert render_wall(replace(wall, seed=6)).image.tobytes() != first.image.tobytes()
    options = {"seed": 3, "dropout": 0.2, "merge_rate": 0.1, "false_positives": 4}
    assert fake_detections(first, **options) == fake_detections(second, **options)


def test_fake_detection_format():
    render = render_wall(SyntheticWall(door=DOOR, occluder_h_mm=300))
    detections = fake_detections(render, false_positives=3)
    json.dumps(detections)
    assert len({d["id"] for d in detections}) == len(detections)
    for d in detections:
        assert set(d) == KEYS
        assert d["run_id"] == "synthetic" and d["id"] == f"synthetic:{d['object_id']}"
        assert d["input_size"] == d["source_size"] == [1600, 1200]
        assert d["crop_box"] == [0, 0, 1600, 1200]
        assert d["candidate"] is True and d["crop_boundary"] is False
        assert d["image_boundary"] == d["edge_truncated"]
        assert 0 < d["rectangularity"] <= 1 and d["area_px"] >= 25
        left, top, right, bottom = d["box"]
        assert 0 <= left < right <= 1600 and 0 <= top < bottom <= 1200
        for contour in d["contours"]:
            assert contour["hole"] is False and contour["depth"] == 0
            assert len(contour["points"]) >= 3
    tiles = [d for d in detections if d["truth"] is not None]
    noise = [d for d in detections if d["truth"] is None]
    assert all(0.6 <= d["confidence"] <= 0.95 for d in tiles)
    assert len(noise) == 3 and all(0.5 <= d["confidence"] <= 0.7 for d in noise)
    kept, _ = cm.merge_detections(tiles)
    assert len(kept) == len(tiles)

    door = fake_concept(render.door_polygon, "door", (1600, 1200))
    assert set(door) == KEYS
    assert (door["id"], door["run_id"], door["confidence"]) == ("door:0", "door", 0.9)
    assert door["area_px"] == pytest.approx(1.6e6 * SCALE**2, rel=0.01)


def test_masks_avoid_door_and_occluder():
    render = render_wall(SyntheticWall(door=DOOR, occluder_h_mm=600))
    detections = fake_detections(render, jitter_px=0)
    points = np.concatenate([np.array(c["points"]) for d in detections for c in d["contours"]])
    # Frontal view: the band top and the door are axis-aligned in the image.
    assert points[:, 1].max() < render.occluder_polygon[:, 1].min()
    (left, top), (right, bottom) = render.door_polygon.min(0), render.door_polygon.max(0)
    inside = (points[:, 0] > left) & (points[:, 0] < right)
    assert not (inside & (points[:, 1] > top) & (points[:, 1] < bottom)).any()
    # Row 3 (y ≥ 1807 mm) lies entirely behind the band from y = 1500 mm.
    assert {j for _, j in truths(detections)} == {0, 1, 2}


def test_cut_by_frame():
    inside = render_wall(SyntheticWall(yaw_deg=30))
    corners = project(inside.plane_to_image, [[0, 0], [2400, 0], [2400, 2100], [0, 2100]])
    low, high = corners.min(0), corners.max(0)
    assert max((high - low) / [1600, 1200]) == pytest.approx(0.8, abs=1e-3)
    assert (low + high) / 2 == pytest.approx([800, 600], abs=1e-3)
    assert not any(d["edge_truncated"] for d in fake_detections(inside))

    cut = fake_detections(render_wall(SyntheticWall(fill=1.3)))
    assert any(d["edge_truncated"] for d in cut)


def test_image_matches_tile_geometry():
    # Wide (8 mm) joints: the pixel at a joint's centre line is pure grout when registered.
    for seed in (0, 1, 2):
        render = render_wall(
            SyntheticWall(grout_mm=8, bond="running", yaw_deg=25, pitch_deg=8, seed=seed)
        )
        grey = render.image.mean(axis=2)
        full = {(t.i, t.j): t for t in render.tiles if t.full}
        rows = {j for _, j in full}

        def sample(x, y, grey=grey, render=render):
            u, v = project(render.plane_to_image, [[x, y]])[0]
            return grey[int(v), int(u)]

        contrast = []
        for (i, j), tile in full.items():
            (x0, y0), (x1, y1) = tile.plane_polygon.min(0), tile.plane_polygon.max(0)
            centre = sample((x0 + x1) / 2, (y0 + y1) / 2)
            if (i + 1, j) in full:
                contrast.append(abs(sample(x1 + 4, (y0 + y1) / 2) - centre))
            if j + 1 in rows:
                contrast.append(abs(sample((x0 + x1) / 2, y1 + 4) - centre))
        assert len(contrast) > 20
        assert np.mean(np.array(contrast) > 10) > 0.9
