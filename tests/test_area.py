"""Tiled area, exclusions and uncertainty on synthetic walls with exact ground truth."""

import math

import cv2
import numpy as np
import pytest

from measure.area import GROUT_TOLERANCE_MM, measure_area, tile_tolerance_mm
from measure.lattice import fit_lattice
from schemas.measure import TileSpec
from validation.synthetic import SyntheticWall, fake_concept, fake_detections, render_wall


def spec(wall, source="box_label"):
    return TileSpec(
        width_mm=wall.tile_w_mm, height_mm=wall.tile_h_mm, grout_mm=wall.grout_mm, source=source
    )


def run(wall, detections=None, concepts=None, **fake):
    render = render_wall(wall)
    detections = (
        fake_detections(render, seed=wall.seed, **fake) if detections is None else detections
    )
    fit = fit_lattice(detections, spec(wall))
    assert fit is not None
    size = (render.image.shape[1], render.image.shape[0])
    return render, measure_area(fit, detections, size, spec(wall), concepts)


@pytest.mark.parametrize("yaw", [0, 25])
def test_full_wall_in_frame(yaw):
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, yaw_deg=yaw, seed=11)
    render, area = run(wall)
    error = area.tiled_area_m2 - render.tiled_area_m2
    assert abs(error) <= 0.01 * render.tiled_area_m2
    assert abs(error) <= 2 * math.hypot(area.sigma_random_m2, area.sigma_system_m2)
    assert area.border_fraction == 0
    assert area.full_tiles >= 100


def test_wall_cut_by_frame():
    _, area = run(SyntheticWall(tile_w_mm=200, tile_h_mm=200, fill=1.3, seed=12))
    assert area.border_fraction > 0.02


def test_door_opening():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, door=(800, 100, 800, 2000), seed=13)
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    concepts = {"door": [fake_concept(render.door_polygon, "door", size)]}
    _, area = run(wall, concepts=concepts)
    openings = [region for region in area.excluded if region.reason == "opening"]
    assert len(openings) == 1 and openings[0].label == "door"
    assert openings[0].area_m2 == pytest.approx(1.6, rel=0.05)
    assert len(area.excluded_px["door"]) >= 1
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)


def test_occluder_allowance():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, occluder_h_mm=600, seed=14)
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    concepts = {"bathtub": [fake_concept(render.occluder_polygon, "bathtub", size)]}
    _, area = run(wall, concepts=concepts)
    hidden = sum(r.area_m2 for r in area.excluded if r.reason == "not_visible")
    assert hidden >= 0.95 * render.hidden_area_m2
    assert area.tiled_area_m2 == pytest.approx(render.visible_tiled_area_m2, rel=0.015)


def test_hole_filling_and_allowance():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, seed=15)
    render = render_wall(wall)
    detections = fake_detections(render, seed=15)
    cell_m2 = (wall.tile_w_mm + wall.grout_mm) * (wall.tile_h_mm + wall.grout_mm) / 1e6

    def without(block):
        return [
            d
            for d in detections
            if not d["truth"] or (d["truth"]["i"], d["truth"]["j"]) not in block
        ]

    small = {(i, j) for i in (6, 7) for j in (6, 7)}
    _, area = run(wall, detections=without(small))
    assert area.completed_cells == 4
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)
    large = {(i, j) for i in range(5, 9) for j in range(5, 9)}
    _, area = run(wall, detections=without(large))
    assert area.undetected_m2 == pytest.approx(16 * cell_m2, rel=0.1)
    assert any(r.label == "undetected" and r.reason == "not_visible" for r in area.excluded)


def test_mosaic_area():
    wall = SyntheticWall(
        wall_w_mm=600, wall_h_mm=600, tile_w_mm=25, tile_h_mm=25, grout_mm=2, seed=16
    )
    render, area = run(wall)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.02)


def test_sigma_system_formula():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=100, seed=17)
    _, area = run(wall)
    delta = math.hypot(tile_tolerance_mm("box_label"), GROUT_TOLERANCE_MM)
    expected = area.tiled_area_m2 * (delta / 202 + delta / 102)
    assert area.sigma_system_m2 == pytest.approx(expected, rel=1e-6)
    assert tile_tolerance_mm("tape") == 1.0 and tile_tolerance_mm("user") == 1.5


def test_strip_beside_door_and_row_gaps_are_counted():
    wall = SyntheticWall(
        tile_w_mm=300, tile_h_mm=150, bond="running", yaw_deg=25, pitch_deg=8,
        door=(1500, 300, 700, 1800), occluder_h_mm=500, gloss=0.6, seed=31,
    )  # fmt: skip
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    concepts = {
        "door": [fake_concept(render.door_polygon, "door", size)],
        "bathtub": [fake_concept(render.occluder_polygon, "bathtub", size)],
    }
    _, area = run(wall, concepts=concepts, dropout=0.1)
    assert area.tiled_area_m2 == pytest.approx(render.visible_tiled_area_m2, rel=0.03)


def test_floor_masks_block_acceptance():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, fill=0.6, seed=18)
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    detections = fake_detections(render, seed=18)
    # Floor tiles continue below the wall; in the image they look like more aligned tiles.
    h = wall.wall_h_mm
    floor = []
    for k, x in enumerate(range(0, 2400, 152)):
        for row, y in enumerate((h + 2, h + 154)):
            rect = np.array([[x, y], [x + 150, y], [x + 150, y + 150], [x, y + 150]], float)
            polygon = cv2.perspectiveTransform(rect[None], render.plane_to_image)[0]
            floor.append({**fake_concept(polygon, "tile", size), "id": f"floor:{k}:{row}"})
    band = np.array([[0, h], [2400, h], [2400, h + 400], [0, h + 400]], float)
    floor_mask = cv2.perspectiveTransform(band[None], render.plane_to_image)[0]
    concepts = {"floor": [fake_concept(floor_mask, "floor", size)]}
    _, area = run(wall, detections=detections + floor, concepts=concepts)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)
    assert all(region.label != "floor" for region in area.excluded)
