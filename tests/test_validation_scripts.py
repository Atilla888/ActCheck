"""Field validation and planted-inflation ROC on hand-checked numbers; no SAM requests."""

import csv
import json
from pathlib import Path

import pytest

from schemas.measure import ExcludedRegion, MeasureQuality, TileSpec, WallMeasurement
from validation import roc, run_validation

TEMPLATE = Path(__file__).resolve().parents[1] / "validation/rooms.csv"
HEADER = TEMPLATE.read_text().splitlines()[0]  # room_id,wall_id,laser_area_m2,...,notes


def roc_row(row_id, truth, measured, sigma, *, hidden=0.0, kind="synthetic-masks"):
    return {
        "id": row_id,
        "truth_m2": truth,
        "measured_m2": measured,
        "sigma_m2": sigma,
        "hidden_m2": hidden,
        "kind": kind,
    }


def wall(wall_id, area, sigma_random, sigma_system, *, excluded=()):
    """What measure_wall returns for a measured wall."""
    return WallMeasurement(
        wall_id=wall_id,
        image_path=f"/photos/{wall_id}.jpg",
        tile=TileSpec(width_mm=300, height_mm=600, source="tape"),
        status="measured",
        full_tiles=38,
        partial_tiles_equiv=4.5,
        tiled_area_m2=area,
        sigma_random_m2=sigma_random,
        sigma_system_m2=sigma_system,
        excluded=list(excluded),
        overlay_png=f"outputs/measure/{wall_id}-0123abcd.png",
        quality=MeasureQuality(
            method="sam_lattice",
            n_confident_tiles=38,
            n_merged_suspected=0,
            lattice_residual_px=0.8,
        ),
    )


def test_roc_perfect_measurement():
    rows = [roc_row(f"w{i}", t, t, 0.002 * t) for i, t in enumerate([3.2, 4.75, 6.1, 9.0])]
    rows.append(roc_row("tub", 5.0, 4.25, 0.01, hidden=0.75))  # exact bathtub allowance
    result = roc.roc_table(rows)
    assert result["auc"] == 1.0
    assert result["false_alarm_rate_at_k2"] == 0.0
    assert result["min_detectable_inflation_at_k2"] <= 0.05


def test_roc_labels_planted(tmp_path):
    synthetic = [
        roc_row("s1", 4.0, 4.03, 0.05, kind="synthetic-sam"),
        roc_row("s2", 6.0, None, None, kind="synthetic-sam"),  # refused photo: no number
        roc_row("s3", 2.5, 2.48, 0.04, kind="synthetic-sam"),
    ]
    field = [roc_row("r1/w1", 4.62, 4.55, 0.07, kind="field")]
    (tmp_path / "synthetic.json").write_text(json.dumps(synthetic))
    (tmp_path / "field.json").write_text(json.dumps(field))
    out = tmp_path / "roc" / "roc.json"
    inputs = [str(tmp_path / "synthetic.json"), str(tmp_path / "field.json")]
    assert roc.main([*inputs, "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    assert result["planted"] is True
    assert result["kinds"] == {"synthetic-sam": 2, "field": 1}
    assert result["n_rows"] == 3 and result["skipped"] == 1
    assert "planted inflation" in (tmp_path / "roc" / "roc.md").read_text()


def test_roc_noisy_measurement_trades_off():
    # truth 10 m², σ 0.5 m²: every error is within ±σ and ≥ 0.025 m² from a decision boundary
    measured = [9.6, 9.7, 9.8, 9.9, 9.95, 10.05, 10.1, 10.2, 10.3, 10.4]
    result = roc.roc_table([roc_row(f"w{i}", 10.0, m, 0.5) for i, m in enumerate(measured)])
    at_k2 = {round(p["inflation"], 3): p["detection_rate"] for p in result["by_inflation_at_k2"]}
    assert at_k2[0.025] == 0.0  # 10.25 never exceeds measured + 2σ ≥ 10.6
    assert at_k2[0.1] == 0.5  # 11.0 exceeds measured + 2σ only for the five low walls
    assert at_k2[0.3] == 1.0
    assert result["min_detectable_inflation_at_k2"] == pytest.approx(0.15)  # 12.5 % → 8 of 10
    assert result["false_alarm_rate_at_k2"] == 0.0
    k0 = next(p for p in result["curve"] if p["k"] == 0)
    k2 = next(p for p in result["curve"] if p["k"] == 2)
    assert k0["fpr"] == 0.5  # without the σ margin half the honest bills are flagged
    assert k0["tpr"] > k2["tpr"]
    assert result["auc"] < 1.0


def test_field_table(tmp_path):
    photos = tmp_path / "rooms"
    (photos / "r1").mkdir(parents=True)
    (photos / "r1" / "w1.jpg").write_bytes(b"\xff\xd8 jpeg")
    (photos / "r1" / "w2.png").write_bytes(b"\x89PNG")
    csv_path = tmp_path / "rooms.csv"
    csv_path.write_text(
        f"{HEADER},grout_mm,tile_source\n"
        "r1,w1,4.00,300,600,gloss,light,2.00x2.00,1.5,box_label\n"
        "r1,w2,5.00,300,600,gloss,light,2.50x2.00 plus bathtub,,\n"
    )
    tub_and_door = [
        ExcludedRegion(label="bathtub", area_m2=0.9, reason="not_visible"),
        ExcludedRegion(label="door", area_m2=1.6, reason="opening"),
    ]
    results = {
        "w1": wall("w1", 4.12, 0.03, 0.04),
        "w2": wall("w2", 4.90, 0.06, 0.08, excluded=tub_and_door),
    }
    calls = []

    def measure(image_path, tile, wall_id):
        calls.append((Path(image_path), tile, wall_id))
        return results[wall_id]

    out = tmp_path / "out"
    rows = run_validation.read_rows(csv_path)
    table = run_validation.field_table(rows, measure=measure, photo_dir=photos, output_dir=out)

    box = TileSpec(width_mm=300, height_mm=600, grout_mm=1.5, source="box_label")
    defaults = TileSpec(width_mm=300, height_mm=600, grout_mm=2, source="tape")
    assert calls == [(photos / "r1/w1.jpg", box, "w1"), (photos / "r1/w2.png", defaults, "w2")]
    w1, w2 = table["walls"]
    assert w1["error_pct"] == pytest.approx(3.0) and w1["abs_error_pct"] == pytest.approx(3.0)
    assert w2["error_pct"] == pytest.approx(-2.0) and w2["abs_error_pct"] == pytest.approx(2.0)
    assert w1["within_2sigma"] is False  # 0.12 > 2·hypot(0.03, 0.04) = 0.10
    assert w2["within_2sigma"] is True  # 0.10 ≤ 2·hypot(0.06, 0.08) = 0.20
    (room,) = table["rooms"]
    assert room["laser_m2"] == pytest.approx(9.0) and room["measured_m2"] == pytest.approx(9.02)
    assert room["abs_error_pct"] == pytest.approx(0.22, abs=0.01)
    assert room["sigma_m2"] == pytest.approx(0.187, abs=1e-3)  # sqrt(.03² + .06²) + .04 + .08
    assert room["complete"] is True and room["meets_3pct_gate"] is True
    summary = table["summary"]
    assert summary["n_walls"] == 2 and summary["n_measured"] == 2
    assert summary["mape_pct"] == pytest.approx(2.5) and summary["within_2sigma_share"] == 0.5

    roc_rows = json.loads((out / "roc_input.json").read_text())
    assert [(r["kind"], r["truth_m2"], r["measured_m2"], r["hidden_m2"]) for r in roc_rows] == [
        ("field", 4.0, 4.12, 0.0),
        ("field", 5.0, 4.9, 0.9),
    ]
    assert roc_rows[0]["sigma_m2"] == pytest.approx(0.05)
    with (out / "field_results.csv").open() as f:
        assert [float(r["abs_error_pct"]) for r in csv.DictReader(f)] == [3.0, 2.0]
    assert "N = 2" in (out / "field_results.md").read_text()


def test_field_missing_photo(tmp_path):
    photos = tmp_path / "rooms"
    (photos / "r2").mkdir(parents=True)
    (photos / "r2" / "w1.jpeg").write_bytes(b"\xff\xd8 jpeg")
    csv_path = tmp_path / "rooms.csv"
    csv_path.write_text(
        f"{HEADER}\nr2,w1,3.10,200,200,matte,dark,\nr2,w2,2.75,200,200,matte,dark,\n"
    )
    measured_walls = []

    def measure(image_path, tile, wall_id):
        measured_walls.append(wall_id)
        return wall(wall_id, 3.05, 0.02, 0.03)

    rows = run_validation.read_rows(csv_path)
    table = run_validation.field_table(
        rows, measure=measure, photo_dir=photos, output_dir=tmp_path / "out"
    )
    assert measured_walls == ["w1"]
    w1, w2 = table["walls"]
    assert w2["status"] == "missing_photo" and w2["measured_m2"] is None
    assert w2["abs_error_pct"] is None
    (room,) = table["rooms"]
    # w1 alone is within 3 %, but a room with an unphotographed wall cannot pass the gate
    assert room["complete"] is False and room["meets_3pct_gate"] is False
    assert table["summary"]["n_missing_photo"] == 1 and table["summary"]["n_measured"] == 1
    roc_rows = json.loads((tmp_path / "out" / "roc_input.json").read_text())
    assert [r["measured_m2"] for r in roc_rows] == [3.05, None]


def test_field_cli(tmp_path, capsys):
    out = tmp_path / "out"
    assert run_validation.main(["--csv", str(tmp_path / "absent.csv"), "--out", str(out)]) == 0
    assert "FIELD_PROTOCOL.md" in capsys.readouterr().out
    assert not out.exists()

    photos = tmp_path / "rooms"
    (photos / "r1").mkdir(parents=True)
    (photos / "r1" / "w1.jpg").write_bytes(b"\xff\xd8 jpeg")
    export = tmp_path / "export.csv"  # spreadsheet in a comma-decimal locale: BOM, ';', '2,35'
    export.write_text(
        HEADER.replace(",", ";") + "\nr1;w1;2,35;300;600;gloss;light;1,20x1,96\n",
        encoding="utf-8-sig",
    )
    seen = []

    def measure(image_path, tile, wall_id):
        seen.append(Path(image_path))
        return wall(wall_id, 2.30, 0.02, 0.02)

    args = ["--csv", str(export), "--photos", str(photos), "--out", str(out)]
    assert run_validation.main(args, measure=measure) == 0
    assert seen == [photos / "r1/w1.jpg"]
    with (out / "field_results.csv").open() as f:
        (row,) = csv.DictReader(f)
    assert float(row["laser_m2"]) == 2.35

    shifted = tmp_path / "shifted.csv"  # unquoted decimal comma would shift every later column
    shifted.write_text(f"{HEADER}\nr1,w1,2,35,300,600,gloss,light,\n")
    with pytest.raises(SystemExit) as refused:
        run_validation.main(["--csv", str(shifted), "--out", str(out)], measure=measure)
    assert refused.value.code == 2


def test_roc_non_measured_walls_never_flag():
    rows = [
        {"id": "p", "kind": "synthetic-sam", "status": "partial", "truth_m2": 5.0,
         "measured_m2": 2.0, "sigma_m2": 0.05, "hidden_m2": 0.0},
        {"id": "m", "kind": "synthetic-sam", "status": "measured", "truth_m2": 5.0,
         "measured_m2": 5.0, "sigma_m2": 0.05, "hidden_m2": 0.0},
    ]  # fmt: skip
    table = roc.roc_table(rows)
    assert table["false_alarm_rate_at_k2"] == 0.0  # the partial wall reads "incomplete"
    at_30 = next(p for p in table["by_inflation_at_k2"] if abs(p["inflation"] - 0.3) < 1e-9)
    assert at_30["detection_rate"] == 0.5
