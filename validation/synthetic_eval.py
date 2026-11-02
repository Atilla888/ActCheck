"""Accuracy on synthetic walls with exact ground truth. Every row and summary says synthetic.

Both modes run the full measure_wall pipeline on rendered photos whose tiled area is known:
`masks` injects SAM-like masks from the renderer (no API, many random walls); `sam` sends the
renders to SAM 3.1 (cached) for a fixed set of sixteen walls. Errors are against the visible
tiled area, which is what one photo can show; billing truth also includes hidden areas.
"""

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from measure.sam_client import ROOT, Segmentation
from measure.wall import measure_wall
from schemas.measure import TileSpec
from validation.synthetic import SyntheticWall, fake_concept, fake_detections, render_wall

OUT = ROOT / "outputs/synthetic_eval"
KIND = {"masks": "synthetic-masks", "sam": "synthetic-sam"}
LABEL = "synthetic renders with exact ground truth — not field measurements"
SAM_WALLS = [
    SyntheticWall(tile_w_mm=300, tile_h_mm=600, seed=101),
    SyntheticWall(tile_w_mm=200, tile_h_mm=200, yaw_deg=20, seed=102),
    SyntheticWall(tile_w_mm=100, tile_h_mm=300, bond="running", yaw_deg=-25, seed=103),
    SyntheticWall(tile_w_mm=300, tile_h_mm=150, bond="running", pitch_deg=10, seed=104),
    SyntheticWall(tile_w_mm=150, tile_h_mm=150, yaw_deg=30, pitch_deg=-8, seed=105),
    SyntheticWall(tile_w_mm=200, tile_h_mm=200, gloss=0.6, seed=106),
    SyntheticWall(tile_w_mm=300, tile_h_mm=150, bond="running", gloss=0.5, yaw_deg=15, seed=107),
    SyntheticWall(tile_w_mm=150, tile_h_mm=150, door=(1200, 300, 800, 1800), seed=108),
    SyntheticWall(tile_w_mm=200, tile_h_mm=200, door=(300, 200, 800, 1900), yaw_deg=-20, seed=109),
    SyntheticWall(tile_w_mm=150, tile_h_mm=150, occluder_h_mm=500, seed=110),
    SyntheticWall(tile_w_mm=300, tile_h_mm=600, wall_w_mm=3000, wall_h_mm=2500, seed=111),
    SyntheticWall(tile_w_mm=100, tile_h_mm=100, yaw_deg=10, seed=112),
    SyntheticWall(wall_w_mm=600, wall_h_mm=600, tile_w_mm=25, tile_h_mm=25, seed=113),
    SyntheticWall(tile_w_mm=200, tile_h_mm=100, bond="running", roll_deg=2, seed=114),
    SyntheticWall(tile_w_mm=300, tile_h_mm=300, yaw_deg=-35, seed=115),
    SyntheticWall(tile_w_mm=150, tile_h_mm=150, fill=1.25, seed=116),
]
TILES = [(300, 600), (200, 200), (100, 300), (300, 150), (150, 150), (600, 300), (25, 25)]


def random_walls(n, seed=0):
    rng = np.random.default_rng(seed)
    walls = []
    for k in range(n):
        tw, th = TILES[int(rng.integers(len(TILES)))]
        mosaic = tw < 50
        w = round(float(rng.uniform(500, 900) if mosaic else rng.uniform(1800, 3000)))
        h = round(float(rng.uniform(500, 900) if mosaic else rng.uniform(1800, 2700)))
        door = None
        if not mosaic and rng.random() < 0.25:
            door_w, door_h = float(rng.uniform(700, 850)), min(2000.0, 0.9 * h)
            door = (float(rng.uniform(0.1, 0.9) * (w - door_w)), h - door_h, door_w, door_h)
        walls.append(
            SyntheticWall(
                wall_w_mm=w,
                wall_h_mm=h,
                tile_w_mm=tw,
                tile_h_mm=th,
                bond="running" if tw != th and rng.random() < 0.5 else "stack",
                yaw_deg=round(float(rng.uniform(-35, 35)), 1),
                pitch_deg=round(float(rng.uniform(-12, 12)), 1),
                roll_deg=round(float(rng.uniform(-3, 3)), 1),
                fill=round(float(rng.uniform(0.65, 0.9)), 2),
                door=door,
                occluder_h_mm=float(rng.uniform(400, 600))
                if not mosaic and rng.random() < 0.3
                else 0,
                gloss=round(float(rng.uniform(0, 0.7)), 2) if rng.random() < 0.5 else 0.0,
                seed=1000 * seed + k,
            )
        )
    return walls


def _mask_segmenter(render):
    """SAM-like masks of moderate difficulty, fixed per wall seed; concepts from geometry."""
    rng = np.random.default_rng(render.wall.seed)
    size = (render.image.shape[1], render.image.shape[0])
    tiles = fake_detections(
        render,
        seed=render.wall.seed,
        dropout=float(rng.uniform(0, 0.15)),
        merge_rate=float(rng.uniform(0, 0.05)),
        false_positives=int(rng.integers(0, 9)),
    )

    def segment(image, concepts):
        found = {concept: [] for concept in concepts}
        if "door" in found and render.door_polygon is not None:
            found["door"] = [fake_concept(render.door_polygon, "door", size)]
        if "bathtub" in found and render.occluder_polygon is not None:
            found["bathtub"] = [fake_concept(render.occluder_polygon, "bathtub", size)]
        return Segmentation(source_size=size, tiles=tiles, concepts=found)

    return segment


def sweep(walls, mode, *, out_dir=OUT, measure=measure_wall):
    out_dir = Path(out_dir)
    (out_dir / "renders").mkdir(parents=True, exist_ok=True)
    rows = []
    for index, wall in enumerate(walls):
        render = render_wall(wall)
        wall_id = f"{mode}-{index:02d}-s{wall.seed}"
        path = out_dir / "renders" / f"{wall_id}.png"
        Image.fromarray(render.image).save(path)
        tile = TileSpec(
            width_mm=wall.tile_w_mm,
            height_mm=wall.tile_h_mm,
            grout_mm=wall.grout_mm,
            source="box_label",
        )
        segmenter = _mask_segmenter(render) if mode == "masks" else None
        result = measure(
            str(path), tile, wall_id, output_dir=out_dir / f"overlays_{mode}", segmenter=segmenter
        )
        rows.append(_row(wall, wall_id, render, result, KIND[mode]))
    _write(rows, mode, out_dir)
    return rows


def _row(wall, wall_id, render, result, kind):
    measured = result.tiled_area_m2
    sigma = None if measured is None else math.hypot(result.sigma_random_m2, result.sigma_system_m2)
    visible = render.visible_tiled_area_m2
    error = None if measured is None else measured - visible
    return {
        "id": wall_id,
        "kind": kind,
        "status": result.status,
        "warnings": ";".join(result.warnings),
        "truth_m2": round(render.tiled_area_m2, 4),
        "visible_m2": round(visible, 4),
        "measured_m2": measured,
        "sigma_m2": None if sigma is None else round(sigma, 4),
        "hidden_m2": round(sum(r.area_m2 for r in result.excluded if r.reason == "not_visible"), 4),
        "error_pct": None if error is None else round(100 * error / visible, 3),
        "within_2sigma": None if error is None else bool(abs(error) <= 2 * sigma),
        "tile": f"{wall.tile_w_mm:g}x{wall.tile_h_mm:g}",
        "bond": wall.bond,
        "yaw_deg": wall.yaw_deg,
        "pitch_deg": wall.pitch_deg,
        "gloss": wall.gloss,
        "door": wall.door is not None,
        "occluder": wall.occluder_h_mm > 0,
        "overlay": result.overlay_png,
    }


def summarize(rows):
    numbers = [r for r in rows if r["error_pct"] is not None]
    measured = [r for r in numbers if r["status"] == "measured"]

    def stats(group):
        errors = np.abs([r["error_pct"] for r in group]) if group else np.array([])
        return {
            "n": len(group),
            "mape_pct": round(float(errors.mean()), 3) if len(errors) else None,
            "median_abs_pct": round(float(np.median(errors)), 3) if len(errors) else None,
            "max_abs_pct": round(float(errors.max()), 3) if len(errors) else None,
            "within_2sigma": round(sum(r["within_2sigma"] for r in group) / len(group), 3)
            if group
            else None,
        }

    return {
        "label": LABEL,
        "n": len(rows),
        "status": {
            s: sum(r["status"] == s for r in rows) for s in ("measured", "partial", "unavailable")
        },
        "all_with_number": stats(numbers),
        "measured_only": stats(measured),
    }


def _write(rows, mode, out_dir):
    with (out_dir / f"results_{mode}.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    keys = ("id", "kind", "truth_m2", "measured_m2", "sigma_m2", "hidden_m2")
    (out_dir / f"roc_input_{mode}.json").write_text(
        json.dumps([{k: r[k] for k in keys} for r in rows], indent=2)
    )
    summary = summarize(rows)
    (out_dir / f"summary_{mode}.json").write_text(json.dumps(summary, indent=2))
    lines = [
        f"# Synthetic accuracy — {KIND[mode]}",
        "",
        f"**{LABEL}.** Errors are against the visible tiled area (tiles + joints).",
        "",
        f"Walls: {summary['n']} · statuses: {summary['status']}",
        "",
        "| Group | n | MAPE % | median abs % | max abs % | within 2σ |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("measured_only", "all_with_number"):
        s = summary[name]
        lines.append(
            f"| {name.replace('_', ' ')} | {s['n']} | {s['mape_pct']} | {s['median_abs_pct']} | "
            f"{s['max_abs_pct']} | {s['within_2sigma']} |"
        )
    (out_dir / f"summary_{mode}.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["masks", "sam"], default="masks")
    parser.add_argument("--n", type=int, default=40, help="random walls in masks mode")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    walls = random_walls(args.n, args.seed) if args.mode == "masks" else SAM_WALLS
    rows = sweep(walls, args.mode, out_dir=args.out)
    print(json.dumps(summarize(rows), indent=2))


if __name__ == "__main__":
    main()
