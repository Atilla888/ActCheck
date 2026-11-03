"""Synthetic accuracy sweep: rows carry exact truth and are labelled synthetic."""

import json

from validation.synthetic import SyntheticWall
from validation.synthetic_eval import random_walls, summarize, sweep


def test_sweep_offline_small(tmp_path):
    walls = [
        SyntheticWall(tile_w_mm=200, tile_h_mm=200, seed=1),
        SyntheticWall(tile_w_mm=300, tile_h_mm=150, bond="running", yaw_deg=20, seed=2),
        SyntheticWall(tile_w_mm=150, tile_h_mm=150, door=(900, 200, 700, 1900), seed=3),
    ]
    rows = sweep(walls, "masks", out_dir=tmp_path)
    assert len(rows) == 3
    for row in rows:
        assert row["kind"] == "synthetic-masks"
        assert {"truth_m2", "visible_m2", "measured_m2", "sigma_m2", "hidden_m2"} <= set(row)
        assert abs(row["error_pct"]) < 3
        assert row["within_2sigma"] in (True, False)
    summary = summarize(rows)
    assert summary["n"] == 3 and summary["label"].startswith("synthetic")
    roc_rows = json.loads((tmp_path / "roc_input_masks.json").read_text())
    assert len(roc_rows) == 3 and roc_rows[0]["kind"] == "synthetic-masks"


def test_random_walls_are_reproducible():
    assert random_walls(5, seed=3) == random_walls(5, seed=3)
    assert random_walls(5, seed=3) != random_walls(5, seed=4)
