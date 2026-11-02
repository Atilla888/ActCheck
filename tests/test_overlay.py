"""Overlay and animation files for measured and failed walls."""

import numpy as np
import pytest
from PIL import Image

from measure.area import measure_area
from measure.lattice import fit_lattice
from measure.overlay import render_animation, render_failure, render_overlay
from schemas.measure import TileSpec
from validation.synthetic import SyntheticWall, fake_detections, render_wall


def measured_wall():
    wall = SyntheticWall(tile_w_mm=200, tile_h_mm=200, yaw_deg=15, seed=21)
    render = render_wall(wall)
    detections = fake_detections(render, seed=21)
    tile = TileSpec(width_mm=200, height_mm=200, grout_mm=2, source="box_label")
    fit = fit_lattice(detections, tile)
    size = (render.image.shape[1], render.image.shape[0])
    return Image.fromarray(render.image), fit, measure_area(fit, detections, size, tile)


def test_overlay_written(tmp_path):
    image, fit, area = measured_wall()
    path = render_overlay(
        image, fit, area, wall_id="w1", status="measured", warnings=[], out_path=tmp_path / "w.png"
    )
    with Image.open(path) as overlay:
        overlay.load()
        assert max(overlay.size) <= 2000
        assert overlay.size == image.size
        difference = np.abs(np.asarray(overlay.convert("RGB"), int) - np.asarray(image, int))
    assert difference.mean() > 5


def test_failure_without_image(tmp_path):
    path = render_failure(
        None, wall_id="w1", reasons=["unreadable_image"], out_path=tmp_path / "f.png"
    )
    with Image.open(path) as overlay:
        assert overlay.size == (1200, 800)


def test_animation_frames(tmp_path):
    image, fit, area = measured_wall()
    gif = render_animation(
        image, fit, area, wall_id="w1", out_path=tmp_path / "a.gif", fps=10, seconds=2.0
    )
    still = render_overlay(
        image,
        fit,
        area,
        wall_id="w1",
        status="measured",
        warnings=[],
        out_path=tmp_path / "s.png",
        max_side=1280,
    )
    with Image.open(gif) as animation, Image.open(still) as static:
        durations = []
        for index in range(animation.n_frames):
            animation.seek(index)
            durations.append(animation.info["duration"])
        assert sum(durations) == pytest.approx(2000, rel=0.1)  # identical held frames merge
        assert animation.n_frames >= 15
        assert animation.size == static.size
