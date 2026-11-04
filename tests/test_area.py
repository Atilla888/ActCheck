"""Tiled area, exclusions and uncertainty on synthetic walls with exact ground truth."""

import math

import cv2
import numpy as np
import pytest
from PIL import Image

from measure.area import GROUT_TOLERANCE_MM, measure_area, tile_tolerance_mm
from measure.lattice import fit_lattice
from schemas.measure import TileSpec
from validation.synthetic import (
    SyntheticWall,
    extra_plane,
    fake_concept,
    fake_detections,
    render_wall,
)


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


def test_floor_mask_blocks_tiles_of_a_real_floor():
    wall = SyntheticWall(tile_w_mm=150, tile_h_mm=150, pitch_deg=-10, fill=0.65, seed=18)
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    floor, outline = extra_plane(render, "floor", 1500, seed=18)
    concepts = {"floor": [fake_concept(outline, "floor", size)]}
    detections = fake_detections(render, seed=18) + floor
    _, area = run(wall, detections=detections, concepts=concepts)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.02)
    assert not any(i.startswith("floor") for i in area.partial_ids)
    assert all(region.label != "floor" for region in area.excluded)


def wall_block(render, x0, y0, x1, y1, label):
    size = (render.image.shape[1], render.image.shape[0])
    polygon = cv2.perspectiveTransform(
        np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], float), render.plane_to_image
    )[0]
    return fake_concept(polygon, label, size)


def test_door_mask_over_visible_tiles_keeps_them():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, seed=61)
    render = render_wall(wall)
    concepts = {"door": [wall_block(render, 1400, 200, 2200, 2100, "door")]}  # glass screen
    _, area = run(wall, concepts=concepts)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)
    assert area.conflict_tiles > 0


def test_floor_mask_over_bottom_rows_keeps_lattice():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, seed=61)
    render = render_wall(wall)
    concepts = {"floor": [wall_block(render, -50, 1690, 2450, 2300, "floor")]}
    _, area = run(wall, concepts=concepts)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.01)


def test_acceptance_reaches_tiles_beyond_the_door():
    wall = SyntheticWall(
        wall_w_mm=2118, wall_h_mm=2548, tile_w_mm=300, tile_h_mm=600, yaw_deg=33.6,
        pitch_deg=1.8, roll_deg=2.9, fill=0.86, door=(1152.8, 548, 788, 2000), seed=37,
    )  # fmt: skip
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    concepts = {"door": [fake_concept(render.door_polygon, "door", size)]}
    _, area = run(wall, concepts=concepts)
    assert area.tiled_area_m2 == pytest.approx(render.visible_tiled_area_m2, rel=0.03)
    door = next(r for r in area.excluded if r.label == "door")
    assert door.area_m2 == pytest.approx(render.opening_area_m2, rel=0.05)


def test_grid_aligned_tiles_count_without_a_connecting_chain():
    wall = SyntheticWall(
        wall_w_mm=2118, wall_h_mm=2548, tile_w_mm=300, tile_h_mm=600, yaw_deg=33.6,
        pitch_deg=1.8, roll_deg=2.9, fill=0.86, door=(1152.8, 548, 788, 2000), seed=37,
    )  # fmt: skip
    render = render_wall(wall)
    size = (render.image.shape[1], render.image.shape[0])
    detections = fake_detections(render, seed=37)
    # Every tile above the door is missed, so nothing links the strip beyond the door.
    detections = [d for d in detections if not (d["truth"] and d["truth"]["i"] in (4, 5, 6)
                                                and d["truth"]["j"] == 0)]  # fmt: skip
    concepts = {"door": [fake_concept(render.door_polygon, "door", size)]}
    _, area = run(wall, detections=detections, concepts=concepts)
    above_door = 3 * 0.6 * 0.302  # three missed tiles, ~14 % of the visible wall
    visible = render.visible_tiled_area_m2
    assert 0.97 * (visible - above_door) <= area.tiled_area_m2 <= 1.03 * visible
    # Never confidently wrong: within 2 sigma (inferred tiles widen sigma) or flagged partial.
    sigma = math.hypot(area.sigma_random_m2, area.sigma_system_m2)
    honest = abs(area.tiled_area_m2 - visible) <= 2 * sigma
    assert honest or area.undetected_m2 > 0.05 * area.tiled_area_m2


def test_missed_edge_tiles_follow_neighbouring_rows():
    wall = SyntheticWall(tile_w_mm=300, tile_h_mm=150, bond="running", yaw_deg=20, seed=33)
    render = render_wall(wall)
    detections = fake_detections(render, seed=33)
    last_i = max(d["truth"]["i"] for d in detections if d["truth"])
    corners = {(0, 0), (1, 0), (last_i, 0), (0, 5), (last_i, 9)}  # corner and edge tiles missed
    detections = [
        d for d in detections if not d["truth"] or (d["truth"]["i"], d["truth"]["j"]) not in corners
    ]
    _, area = run(wall, detections=detections)
    assert area.tiled_area_m2 == pytest.approx(render.visible_tiled_area_m2, rel=0.015)


@pytest.mark.parametrize("depth", [400, 1000])
@pytest.mark.parametrize("side", ["left", "right"])
def test_adjacent_wall_tiles_not_counted(depth, side):
    # Camera inside the room, turned towards the neighbouring wall; equal tiles on both walls.
    wall = SyntheticWall(tile_w_mm=300, tile_h_mm=300, yaw_deg=-8 if side == "left" else 8,
                         fill=0.8, seed=71)  # fmt: skip
    render = render_wall(wall)
    neighbour, _ = extra_plane(render, "side", depth, side=side, seed=71)
    detections = fake_detections(render, seed=71) + neighbour
    _, area = run(wall, detections=detections)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.03)


@pytest.mark.parametrize("seed", [81, 82, 83])
def test_tiled_floor_not_counted_without_floor_mask(seed):
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, pitch_deg=-10, fill=0.7, seed=seed)
    render = render_wall(wall)
    floor, _ = extra_plane(render, "floor", 1500, seed=seed)
    _, area = run(wall, detections=fake_detections(render, seed=seed) + floor)
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.03)


def test_completed_area_widens_sigma_and_is_capped():
    # Large-format tiles; a missing patch may be an untiled niche, not missed tiles.
    wall = SyntheticWall(wall_w_mm=3600, wall_h_mm=3000, tile_w_mm=600, tile_h_mm=600, seed=91)
    render = render_wall(wall)
    detections = fake_detections(render, seed=91)
    cell = 0.602 * 0.602

    def without(block):
        return [
            d
            for d in detections
            if not d["truth"] or (d["truth"]["i"], d["truth"]["j"]) not in block
        ]

    _, full = run(wall, detections=detections)
    _, one = run(wall, detections=without({(2, 2)}))  # filled in, but it might be a niche
    assert one.tiled_area_m2 == pytest.approx(full.tiled_area_m2, abs=0.05 * cell)
    assert one.sigma_random_m2 >= math.hypot(full.sigma_random_m2, 0.45 * cell)  # quadrature
    _, two = run(wall, detections=without({(2, 2), (3, 2)}))  # 0.72 m2: never filled in
    assert two.tiled_area_m2 == pytest.approx(render.visible_tiled_area_m2 - 2 * cell, rel=0.02)
    assert two.undetected_m2 == pytest.approx(2 * cell, rel=0.1)


@pytest.mark.parametrize(("tile", "spill"), [(200, 80), (150, 90)])
def test_door_mask_spilling_over_tiles_keeps_them(tile, spill):
    # A door outline drawn over the casing and the first strip of tiles around the door.
    wall = SyntheticWall(tile_w_mm=tile, tile_h_mm=tile, door=(800, 100, 800, 2000), yaw_deg=12,
                         seed=95)  # fmt: skip
    render = render_wall(wall)
    door = wall_block(render, 800 - spill, 100 - spill, 1600 + spill, 2100, "door")
    _, area = run(wall, concepts={"door": [door]})
    assert area.tiled_area_m2 == pytest.approx(render.tiled_area_m2, rel=0.02)


def _surface_beside_wall(wall, color):
    """A wall with a tile-sized mask of `color` on the lattice just past its last column."""
    render = render_wall(wall)
    detections = fake_detections(render, seed=wall.seed)
    fit = fit_lattice(detections, spec(wall))
    last = max(fit.tiles, key=lambda t: t.i)
    x0, y0, x1, y1 = fit.cell_rect(last.i + 1, last.j)
    polygon = fit.to_image([[x0 + 5, y0 + 5], [x1 - 5, y0 + 5], [x1 - 5, y1 - 5], [x0 + 5, y1 - 5]])
    size = (render.image.shape[1], render.image.shape[0])
    image = render.image.copy()
    cv2.fillPoly(image, [np.round(polygon).astype(np.int32)], color)
    return fit, [*detections, fake_concept(polygon, "tile", size)], size, Image.fromarray(image)


def test_other_surface_is_allowed_for_not_counted():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, fill=0.7, seed=31)
    fit, detections, size, image = _surface_beside_wall(wall, (20, 60, 200))
    counted = measure_area(fit, detections, size, spec(wall))
    area = measure_area(fit, detections, size, spec(wall), image=image)
    assert counted.tiled_area_m2 - area.tiled_area_m2 == pytest.approx(0.04, abs=0.01)
    other = [r for r in area.excluded if r.label == "other_surface"]
    assert len(other) == 1
    assert other[0].reason == "not_visible"
    assert other[0].area_m2 == pytest.approx(0.04, abs=0.01)


def test_same_coloured_tile_stays_counted():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, fill=0.7, seed=31)
    render = render_wall(wall)
    fit = fit_lattice(fake_detections(render, seed=wall.seed), spec(wall))
    x, y = fit.tiles[0].center.astype(int)
    colour = tuple(int(c) for c in render.image[y, x])
    fit, detections, size, image = _surface_beside_wall(wall, colour)
    area = measure_area(fit, detections, size, spec(wall), image=image)
    assert not [r for r in area.excluded if r.label == "other_surface"]
