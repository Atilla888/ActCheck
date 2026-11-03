"""Summarize observed SAM results without treating candidate masks as ground truth."""

import csv
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/tile_benchmark"


def main():
    runs = json.loads((OUT / "runs.json").read_text())
    rows = list(csv.DictReader((ROOT / "bathroom_tiles_20/sources.csv").open(encoding="utf-8-sig")))
    good = [r for r in runs if r.get("status") == "ok" and not r.get("crop")]
    matrix = []
    tiles = []
    links = []
    for source in rows:
        found = [r for r in good if r["file"] == source["file"]]
        best = max(found, key=lambda r: r["candidates"]) if found else None
        result = {
            "number": source["number"],
            "file": source["file"],
            "best_prompt": "",
            "masks": "",
            "candidate_masks": "",
            "candidate_threshold_met": "",
            "reliable_masks": "not annotated",
            "gate": "not validated",
        }
        if best:
            result.update(
                best_prompt=best["prompt"],
                masks=best["masks"],
                candidate_masks=best["candidates"],
                candidate_threshold_met=best["candidates"] >= 30,
            )
        for prompt in ["tile", "wall tile", "ceramic tile"]:
            trial = next((r for r in found if r["prompt"] == prompt), None)
            result[prompt] = trial["candidates"] if trial else ""
        matrix.append(result)
        if best:
            tile = Image.new("RGB", (400, 355), "#f3f3ef")
            with Image.open(OUT / (best["tag"] + ".jpg")) as image:
                image = ImageOps.contain(image, (400, 310))
                tile.paste(image, ((400 - image.width) // 2, 0))
            ImageDraw.Draw(tile).text(
                (8, 315),
                f"{int(source['number']):02d} | {best['prompt']} | masks {best['masks']} "
                f"| candidates {best['candidates']}",
                fill="black",
            )
            tiles.append(tile)
            links.append(
                f'<li><a href="{best["tag"]}.jpg">{html.escape(source["file"])}: '
                f"{best['candidates']} candidates</a></li>"
            )
    with (OUT / "results.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)
    if tiles:
        sheet = Image.new("RGB", (1600, ((len(tiles) + 3) // 4) * 355), "white")
        for i, tile in enumerate(tiles):
            sheet.paste(tile, ((i % 4) * 400, (i // 4) * 355))
        sheet.save(OUT / "overlays_contact.jpg")
    count = sum(r["candidate_threshold_met"] is True for r in matrix)
    complete = sum(r["candidate_threshold_met"] != "" for r in matrix)
    prompts = {
        p: {
            "tested": sum(p in r and r[p] != "" for r in matrix),
            "at_least_30_candidates": sum(isinstance(r[p], int) and r[p] >= 30 for r in matrix),
        }
        for p in ["tile", "wall tile", "ceramic tile"]
    }
    raw_threshold = len({r["file"] for r in good if r["masks"] >= 30})
    baseline_complete = all(p["tested"] == len(rows) for p in prompts.values())
    summary = {
        "images_tested": complete,
        "images_with_30_candidates_best_of_prompts": count,
        "prompts": prompts,
        "gate_16_of_20_reliable_walls": "NOT_ESTABLISHED",
        "full_frame_baseline": (
            f"FAILED: {raw_threshold}/{len(rows)} images have at least 30 raw masks"
            if baseline_complete and raw_threshold < 16
            else "Manual review required or baseline incomplete"
        ),
        "area_accuracy": "NOT_TESTABLE: physical dimensions and reference areas unknown",
        "successful_unique_requests": len([r for r in runs if r.get("status") == "ok"]),
        "errors": [r for r in runs if r.get("status") != "ok"],
        "crop_trials": [r for r in runs if r.get("crop")],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>ActCheck tile
benchmark</title>
<style>body{{font:16px/1.6 system-ui;max-width:1100px;margin:40px
auto;padding:20px}}img{{max-width:100%}}pre{{white-space:pre-wrap}}td,th{{padding:8px;border-bottom:1px
solid #ccc}}table{{border-collapse:collapse}}</style>
<h1>Tile segmentation benchmark — 29 October 2026</h1>
<p>{complete}/20 images tested. Best-of-prompt candidate threshold: {count}/20. This is
exploratory prompt tuning, not a held-out evaluation.</p>
<p><strong>Gate not validated.</strong> Green outlines are heuristic candidates, not manually
verified tiles. Reflections, multiple walls, partial tiles and curved surfaces must be reviewed
separately. No area accuracy claim is possible.</p>
<p>Candidate filter: confidence ≥0.5, nonempty area ≥25 pixels and ≤10% of image,
minimum-area-rectangle occupancy ≥0.65. These thresholds are uncalibrated diagnostics. Counts do
not establish precision or recall.</p>
<p>Images are EXIF-oriented and resized only when specified in runs.json; originals are
preserved. The original 7296×5472 request for image 01 returned HTTP 400. Later trials
explicitly record their input dimensions. Raw events are cached under data/cache/sam_benchmark,
outside Git.</p>
<table><thead><tr><th>Photo</th><th>tile</th><th>wall tile</th><th>ceramic tile</th><th>Best
candidates</th></tr></thead><tbody>"""
    for r in matrix:
        document += (
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(r[k]))}</td>"
                for k in ["number", "tile", "wall tile", "ceramic tile", "candidate_masks"]
            )
            + "</tr>"
        )
    document += (
        "</tbody></table><h2>Overlays</h2>"
        '<img src="overlays_contact.jpg" alt="Candidate mask overlays"><ul>'
        + "".join(links)
        + "</ul><h2>Run details</h2><pre>"
        + html.escape(json.dumps(summary, indent=2))
        + "</pre></html>"
    )
    crop_rows = sorted(summary["crop_trials"], key=lambda r: (r["crop"][1], r["crop"][0]))
    crop_html = "<h2>Overlapping crop experiment: image 01</h2><ul>"
    for crop in crop_rows:
        crop_html += (
            f'<li><a href="{crop["tag"]}.jpg">Source bounds {crop["crop"]}</a>: '
            f"{crop['masks']} masks, {crop['candidates']} candidates</li>"
        )
    crop_html += "</ul><p>Overlapping detections are not deduplicated. Do not sum these counts.</p>"
    document = document.replace("<h2>Run details</h2>", crop_html + "<h2>Run details</h2>")
    (OUT / "report.html").write_text(document)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ["images_tested", "images_with_30_candidates_best_of_prompts", "prompts"]
            }
        )
    )


if __name__ == "__main__":
    main()
