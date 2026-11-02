"""Field check (small N): laser/tape-measured walls against measure_wall, per wall and per room.

Inputs follow validation/FIELD_PROTOCOL.md: data/private/rooms/rooms.csv (validation/rooms.csv
columns plus optional grout_mm and tile_source) and one photo per wall at
data/private/rooms/<room_id>/<wall_id>.jpg. Writes field_results.csv, field_results.md and
roc_input.json (rows for validation.roc, kind "field") to outputs/validation.
"""

import argparse
import csv
import io
import json
import math
import statistics
import sys
from pathlib import Path

from measure.wall import measure_wall
from schemas.measure import TileSpec

PRIVATE = Path("data/private/rooms")
OUT = Path("outputs/validation")
SUFFIXES = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
GATE_PCT = 3.0  # team plan: room area within 3 % of the laser
WALL_COLUMNS = [
    "room_id",
    "wall_id",
    "status",
    "laser_m2",
    "measured_m2",
    "sigma_m2",
    "sigma_random_m2",
    "sigma_system_m2",
    "hidden_m2",
    "error_pct",
    "abs_error_pct",
    "within_2sigma",
    "tile",
    "tile_source",
    "grout_mm",
    "finish",
    "grout",
    "warnings",
    "photo",
    "overlay_png",
]


def read_rows(path) -> list[dict]:
    """CSV rows with trimmed cells; `;`-separated spreadsheet exports work too."""
    text = Path(path).read_text(encoding="utf-8-sig")
    header = text.partition("\n")[0]
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if ";" in header else ",")
    rows = []
    for row in reader:
        if None in row:
            raise ValueError(
                f"{path} line {reader.line_num}: more cells than columns; "
                "quote text containing commas and write decimals with '.'"
            )
        cells = {key.strip(): (value or "").strip() for key, value in row.items()}
        if any(cells.values()):
            rows.append(cells)
    return rows


def field_table(
    rows: list[dict],
    measure=measure_wall,
    photo_dir=PRIVATE,
    output_dir=OUT,
) -> dict:
    walls = [_wall(row, measure, Path(photo_dir)) for row in rows]
    rooms = [
        _room(room_id, [w for w in walls if w["room_id"] == room_id])
        for room_id in dict.fromkeys(w["room_id"] for w in walls)
    ]
    result = {
        "label": f"field check, small N: {len(walls)} walls, laser/tape truth",
        "walls": walls,
        "rooms": rooms,
        "summary": _summary(walls, rooms),
    }
    _write(result, Path(output_dir))
    return result


def _wall(row, measure, photo_dir):
    room_id, wall_id = row["room_id"], row["wall_id"]
    grout = _number(row.get("grout_mm"))
    tile = TileSpec(
        width_mm=_number(row["tile_w_mm"]),
        height_mm=_number(row["tile_h_mm"]),
        grout_mm=2.0 if grout is None else grout,
        source=row.get("tile_source") or "tape",
    )
    laser = _number(row.get("laser_area_m2"))
    photo = next(
        (p for s in SUFFIXES if (p := photo_dir / room_id / f"{wall_id}{s}").is_file()), None
    )
    wall = dict.fromkeys(WALL_COLUMNS)
    wall.update(
        room_id=room_id,
        wall_id=wall_id,
        status="missing_photo",
        laser_m2=laser,
        tile=f"{tile.width_mm:g}x{tile.height_mm:g}",
        tile_source=tile.source,
        grout_mm=tile.grout_mm,
        finish=row.get("finish", ""),
        grout=row.get("grout", ""),
        warnings=["missing_photo"],
        photo=str(photo or ""),
    )
    if photo is None:
        return wall
    result = measure(str(photo), tile, wall_id)
    hidden = sum((r.area_m2 for r in result.excluded if r.reason == "not_visible"), 0.0)
    wall.update(
        status=result.status,
        measured_m2=result.tiled_area_m2,
        hidden_m2=round(hidden, 3),
        warnings=list(result.warnings),
        overlay_png=result.overlay_png,
    )
    if result.tiled_area_m2 is None:
        return wall
    sigma_random, sigma_system = result.sigma_random_m2 or 0.0, result.sigma_system_m2 or 0.0
    sigma = math.hypot(sigma_random, sigma_system)
    wall.update(
        sigma_m2=round(sigma, 4), sigma_random_m2=sigma_random, sigma_system_m2=sigma_system
    )
    if laser:
        error = result.tiled_area_m2 - laser
        wall.update(
            error_pct=round(100 * error / laser, 2),
            abs_error_pct=round(100 * abs(error) / laser, 2),
            within_2sigma=abs(error) <= 2 * sigma,
        )
    return wall


def _room(room_id, walls):
    """Sums over walls with a number; random sigmas add in quadrature, systematic linearly."""
    scored = [w for w in walls if w["error_pct"] is not None]
    complete = all(w["status"] == "measured" and w["laser_m2"] for w in walls)
    room = {
        "room_id": room_id,
        "n_walls": len(walls),
        "n_with_number": len(scored),
        "laser_m2": None,
        "measured_m2": None,
        "sigma_m2": None,
        "error_pct": None,
        "abs_error_pct": None,
        "within_2sigma": None,
        "complete": complete,
        "meets_3pct_gate": False,
    }
    if not scored:
        return room
    laser = sum(w["laser_m2"] for w in scored)
    measured = sum(w["measured_m2"] for w in scored)
    sigma = math.sqrt(sum(w["sigma_random_m2"] ** 2 for w in scored)) + sum(
        w["sigma_system_m2"] for w in scored
    )
    error = 100 * (measured - laser) / laser
    room.update(
        laser_m2=round(laser, 3),
        measured_m2=round(measured, 3),
        sigma_m2=round(sigma, 4),
        error_pct=round(error, 2),
        abs_error_pct=round(abs(error), 2),
        within_2sigma=abs(measured - laser) <= 2 * sigma,
        meets_3pct_gate=complete and abs(error) <= GATE_PCT,
    )
    return room


def _summary(walls, rooms):
    """Accuracy over `measured` walls only; partial walls are listed but not scored."""
    statuses = [w["status"] for w in walls]
    scored = [w for w in walls if w["status"] == "measured" and w["abs_error_pct"] is not None]
    errors = [w["abs_error_pct"] for w in scored]
    return {
        "n_walls": len(walls),
        "n_measured": statuses.count("measured"),
        "n_partial": statuses.count("partial"),
        "n_unavailable": statuses.count("unavailable"),
        "n_missing_photo": statuses.count("missing_photo"),
        "n_scored": len(scored),
        "mape_pct": round(statistics.fmean(errors), 2) if errors else None,
        "median_abs_error_pct": round(statistics.median(errors), 2) if errors else None,
        "within_2sigma_share": (
            round(sum(w["within_2sigma"] for w in scored) / len(scored), 3) if scored else None
        ),
        "room_abs_error_pct": {r["room_id"]: r["abs_error_pct"] for r in rooms},
        "meets_3pct_gate": {r["room_id"]: r["meets_3pct_gate"] for r in rooms},
    }


def _write(result, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "field_results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WALL_COLUMNS)
        writer.writeheader()
        writer.writerows({**w, "warnings": ";".join(w["warnings"])} for w in result["walls"])
    (output_dir / "field_results.md").write_text(_markdown(result))
    roc_rows = [
        {
            "id": f"{w['room_id']}/{w['wall_id']}",
            "truth_m2": w["laser_m2"],
            "measured_m2": w["measured_m2"],
            "sigma_m2": w["sigma_m2"],
            "hidden_m2": w["hidden_m2"] or 0.0,
            "kind": "field",
            "status": w["status"],
        }
        for w in result["walls"]
        if w["laser_m2"]
    ]
    (output_dir / "roc_input.json").write_text(json.dumps(roc_rows, indent=2) + "\n")


def _markdown(result):
    s = result["summary"]
    within = round((s["within_2sigma_share"] or 0) * s["n_scored"])
    lines = [
        "# Field check (small N)",
        "",
        f"**N = {s['n_walls']} wall(s) in {len(result['rooms'])} room(s)**, ActCheck against "
        "laser/tape measurements. Too few walls for an accuracy estimate: this checks the ≤ 3 % "
        "room target on these rooms only. Synthetic and planted-inflation results are separate.",
        "",
        f"- Status: {s['n_measured']} measured, {s['n_partial']} partial, "
        f"{s['n_unavailable']} unavailable, {s['n_missing_photo']} missing photo",
        f"- Measured walls with a laser value: {s['n_scored']}; MAPE {_pct(s['mape_pct'])}, "
        f"median |error| {_pct(s['median_abs_error_pct'])}, laser within 2σ: "
        f"{within} of {s['n_scored']}",
        "",
        "| room | walls with a number | laser m² | ActCheck m² | error | all walls measured "
        "| ≤ 3 % gate |",
        "|---|---:|---:|---:|---:|---|---|",
        *(
            f"| {r['room_id']} | {r['n_with_number']} of {r['n_walls']} | {_area(r['laser_m2'])} "
            f"| {_area(r['measured_m2'])} | {_pct(r['error_pct'], signed=True)} "
            f"| {'yes' if r['complete'] else 'no'} | {'pass' if r['meets_3pct_gate'] else 'fail'} |"
            for r in result["rooms"]
        ),
        "",
        "| room | wall | status | laser m² | ActCheck m² ± 2σ | error | laser within 2σ "
        "| warnings |",
        "|---|---|---|---:|---:|---:|---|---|",
        *(
            f"| {w['room_id']} | {w['wall_id']} | {w['status']} | {_area(w['laser_m2'])} "
            f"| {_interval(w['measured_m2'], w['sigma_m2'])} "
            f"| {_pct(w['error_pct'], signed=True)} | {_yes_no(w['within_2sigma'])} "
            f"| {', '.join(w['warnings'])} |"
            for w in result["walls"]
        ),
        "",
        "Partial walls are listed but left out of MAPE; the gate needs every wall `measured`. "
        "Missing photos belong at data/private/rooms/<room_id>/<wall_id>.jpg "
        "(see validation/FIELD_PROTOCOL.md).",
    ]
    return "\n".join(lines) + "\n"


def _number(value):
    text = "" if value is None else str(value).strip().replace(",", ".")
    return float(text) if text else None


def _area(value):
    return "—" if value is None else f"{value:.3f}"


def _interval(value, sigma):
    return "—" if value is None else f"{value:.3f} ± {2 * (sigma or 0.0):.3f}"


def _pct(value, signed=False):
    return "—" if value is None else f"{value:+.2f} %" if signed else f"{value:.2f} %"


def _yes_no(value):
    return "—" if value is None else "yes" if value else "no"


def main(argv=None, *, measure=measure_wall):
    parser = argparse.ArgumentParser(
        prog="python -m validation.run_validation", description=__doc__
    )
    parser.add_argument("--csv", type=Path, default=PRIVATE / "rooms.csv")
    parser.add_argument("--photos", type=Path, default=PRIVATE, help="<room_id>/<wall_id>.jpg")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if not args.csv.is_file():
        print(
            f"No field measurements at {args.csv}. Record walls and photos as described in "
            "validation/FIELD_PROTOCOL.md, then rerun."
        )
        return 0
    try:
        rows = read_rows(args.csv)
    except ValueError as error:
        parser.error(str(error))
    field_table(rows, measure=measure, photo_dir=args.photos, output_dir=args.out)
    print((args.out / "field_results.md").read_text())
    print(f"Wrote field_results.csv, field_results.md and roc_input.json to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
