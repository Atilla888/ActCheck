"""Measurement behaviour on the 20 collected reference photos: fits, refusals and overlays.

These Pexels photos have no physical scale, so the tile sizes below are visual aspect guesses
and no area is reported. The run shows which walls the pipeline measures, marks partial or
refuses, and why. Tile masks are cached; exclusion prompts cost about five requests a photo.
"""

import argparse
import csv
import json

from PIL import Image, ImageDraw

from measure.sam_client import ROOT
from measure.wall import measure_wall
from schemas.measure import TileSpec

FOLDER = ROOT / "bathroom_tiles_20"
OUT = ROOT / "outputs/reference_run"
ASPECT_GUESSES = {  # width x height in mm, chosen by eye for the tile shape only
    1: (50, 50), 2: (200, 400), 3: (100, 300), 4: (100, 100), 5: (100, 400),
    6: (100, 450), 7: (100, 300), 8: (100, 300), 9: (100, 300), 10: (100, 100),
    11: (100, 400), 12: (75, 150), 13: (200, 200), 14: (200, 200), 15: (25, 25),
    16: (25, 25), 17: (75, 300), 18: (75, 150), 19: (75, 150), 20: (200, 400),
}  # fmt: skip


def run(numbers, out_dir=OUT):
    sources = list(csv.DictReader((FOLDER / "sources.csv").open(encoding="utf-8-sig")))
    rows = []
    for source in sources:
        number = int(source["number"])
        if number not in numbers:
            continue
        width, height = ASPECT_GUESSES[number]
        tile = TileSpec(width_mm=width, height_mm=height, grout_mm=2, source="user")
        result = measure_wall(
            str(FOLDER / source["file"]), tile, f"ref{number:02d}", output_dir=out_dir / "overlays"
        )
        quality = result.quality
        rows.append(
            {
                "photo": f"{number:02d}",
                "conditions": source["conditions_ru"],
                "status": result.status,
                "warnings": ";".join(result.warnings),
                "lattice_tiles": quality.n_confident_tiles if quality else 0,
                "merged_suspected": quality.n_merged_suspected if quality else 0,
                "residual_px": quality.lattice_residual_px if quality else None,
                "straightness_px": quality.lens_straightness_px if quality else None,
                "exclusions": ";".join(f"{e.label}:{e.reason}" for e in result.excluded),
                "overlay": result.overlay_png,
            }
        )
        print(json.dumps({k: rows[-1][k] for k in ("photo", "status", "warnings")}), flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    contact_sheet(rows, out_dir / "contact.jpg")
    counts = {
        s: sum(r["status"] == s for r in rows) for s in ("measured", "partial", "unavailable")
    }
    (out_dir / "summary.json").write_text(json.dumps({"photos": len(rows), **counts}, indent=2))
    return rows


def contact_sheet(rows, path, columns=5, cell=(400, 300)):
    sheet = Image.new(
        "RGB", (columns * cell[0], -(-len(rows) // columns) * (cell[1] + 24)), "white"
    )
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        x, y = (index % columns) * cell[0], (index // columns) * (cell[1] + 24)
        with Image.open(row["overlay"]) as overlay:
            overlay.thumbnail(cell)
            sheet.paste(overlay, (x + (cell[0] - overlay.width) // 2, y))
        label = f"{row['photo']}: {row['status']} - {row['lattice_tiles']} lattice tiles"
        draw.text((x + 6, y + cell[1] + 4), label, fill="black")
    sheet.save(path, quality=88)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", nargs="+", type=int, default=list(range(1, 21)))
    args = parser.parse_args()
    rows = run(set(args.photos))
    print(
        json.dumps(
            {s: sum(r["status"] == s for r in rows) for s in ("measured", "partial", "unavailable")}
        )
    )


if __name__ == "__main__":
    main()
