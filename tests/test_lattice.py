"""Lattice homography on synthetic walls with exact ground truth."""

import cv2
import numpy as np

from measure.lattice import MIN_TILES, extract_quads, fit_lattice
from schemas.measure import TileSpec
from validation.synthetic import SyntheticWall, fake_detections, render_wall


def polygon_area(points):
    x, y = np.asarray(points, float).T
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


def wall_area_error(render, fit, offset=(0.0, 0.0)):
    """Relative error of the wall rectangle's area recovered through the fitted homography."""
    w, h = render.wall.wall_w_mm, render.wall.wall_h_mm
    plane = np.array([[[0, 0], [w, 0], [w, h], [0, h]]], float)
    image = cv2.perspectiveTransform(plane, render.plane_to_image)[0] + offset
    return polygon_area(fit.to_plane(image)) / (w * h) - 1


def spec(wall, **changes):
    values = {"width_mm": wall.tile_w_mm, "height_mm": wall.tile_h_mm}
    values.update(changes)
    return TileSpec(grout_mm=wall.grout_mm, source="box_label", **values)


def test_frontal_stack_bond():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200)
    render = render_wall(wall)
    fit = fit_lattice(fake_detections(render), spec(wall))
    assert fit is not None
    assert abs(wall_area_error(render, fit)) <= 0.003
    assert fit.residual_px < 0.02 * fit.tile_px
    assert len(fit.tiles) >= MIN_TILES


def test_oblique_running_bond():
    wall = SyntheticWall(
        tile_w_mm=150, tile_h_mm=75, bond="running", yaw_deg=30, pitch_deg=10, seed=3
    )
    render = render_wall(wall)
    fit = fit_lattice(fake_detections(render, seed=3), spec(wall))
    assert fit is not None
    assert abs(wall_area_error(render, fit)) <= 0.005


def test_dropout_merges_false_positives():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, yaw_deg=-20, seed=5)
    render = render_wall(wall)
    detections = fake_detections(render, seed=5, dropout=0.3, merge_rate=0.08, false_positives=15)
    fit = fit_lattice(detections, spec(wall))
    assert fit is not None
    assert abs(wall_area_error(render, fit)) <= 0.007
    assert fit.n_merged_suspected >= 1


def test_orientation_swap_preserves_area():
    wall = SyntheticWall(tile_w_mm=300, tile_h_mm=600, wall_w_mm=3000, wall_h_mm=2400, seed=2)
    render = render_wall(wall)
    detections = fake_detections(render, seed=2)
    as_given = fit_lattice(detections, spec(wall))
    swapped = fit_lattice(detections, spec(wall, width_mm=600, height_mm=300))
    assert as_given is not None and swapped is not None
    assert abs(wall_area_error(render, swapped) - wall_area_error(render, as_given)) <= 0.001


def test_corner_picks_one_plane():
    left = render_wall(
        SyntheticWall(tile_w_mm=100, tile_h_mm=100, yaw_deg=25, image_size=(800, 1200), seed=7)
    )
    right = render_wall(
        SyntheticWall(tile_w_mm=200, tile_h_mm=200, yaw_deg=-25, image_size=(800, 1200), seed=8)
    )
    detections = [{**d, "id": "left:" + d["id"]} for d in fake_detections(left, seed=7)]
    for d in fake_detections(right, seed=8):
        shifted = [{**c, "points": [[x + 800, y] for x, y in c["points"]]} for c in d["contours"]]
        box = [d["box"][0] + 800, d["box"][1], d["box"][2] + 800, d["box"][3]]
        detections.append({**d, "id": "right:" + d["id"], "contours": shifted, "box": box})
    fit = fit_lattice(detections, TileSpec(width_mm=100, height_mm=100, source="box_label"))
    assert fit is not None
    assert all(tile.det_id.startswith("left:") for tile in fit.tiles)
    assert abs(wall_area_error(left, fit)) <= 0.01


def test_too_few_tiles_returns_none():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200)
    detections = fake_detections(render_wall(wall))[:8]
    assert fit_lattice(detections, spec(wall)) is None


def test_vertical_running_bond():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=75, bond="running", roll_deg=90, seed=4)
    render = render_wall(wall)
    fit = fit_lattice(fake_detections(render, seed=4), spec(wall))
    assert fit is not None
    assert fit.transposed is True
    assert abs(wall_area_error(render, fit)) <= 0.005


def test_merged_masks_are_counted_not_used():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, seed=9)
    detections = fake_detections(render_wall(wall), seed=9, merge_rate=0.1)
    quads, merged = extract_quads(detections)
    assert merged >= 1
    areas = np.array([q.area_px for q in quads])
    assert areas.max() < 1.7 * np.median(areas)


def test_cut_edge_tiles_are_not_lattice_cells():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, seed=11)
    detections = fake_detections(render_wall(wall), seed=11)
    truth = {d["id"]: d["truth"] for d in detections}
    fit = fit_lattice(detections, spec(wall))
    columns = {truth[t.det_id]["i"] for t in fit.tiles}
    rows = {truth[t.det_id]["j"] for t in fit.tiles}
    assert max(columns) == 10 and max(rows) == 9  # column 11 is 176 mm wide, row 10 is 78 mm
