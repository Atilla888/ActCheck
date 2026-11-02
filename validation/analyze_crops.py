"""Offline source-coordinate merge, wall screening, and crop experiment report."""

import argparse
import asyncio
import csv
import html
import io
import json
import re
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import cv2
import meta_sam_parser as msp
import numpy as np
from PIL import Image, ImageDraw, ImageOps

import measure.crop_merge as merge_module
from measure.crop_merge import convert_record, merge_detections
from validation.benchmark_tiles import CACHE, ROOT, crops_for, digest

OUT = ROOT / "outputs/tile_crops"
FOLDER = ROOT / "bathroom_tiles_20"


def read_cache(key, expected_size, expected_spec=None):
    saved = json.loads((CACHE / f"{key}.json").read_text())
    if expected_spec is not None:
        if saved["spec"] != expected_spec or key != digest(
            json.dumps(expected_spec, sort_keys=True).encode()
        ):
            raise ValueError("Unexpected cached request provenance")
    final_text = next(
        (e.get("text", "") for e in saved["events"] if e["type"] == "response.output_text.done"), ""
    )
    sizes = {(int(w), int(h)) for w, h in re.findall(r";w=(\d+);h=(\d+)", final_text)}
    if sizes and sizes != {tuple(expected_size)}:
        raise ValueError(f"Returned coordinate frame mismatch: {sizes} vs {expected_size}")
    if not any(e["type"] == "response.completed" for e in saved["events"]):
        raise ValueError("Cached request did not complete")
    return saved


async def parse_cache(key, expected_size, expected_spec=None):
    saved = read_cache(key, expected_size, expected_spec)

    async def replay():
        for event in saved["events"]:
            yield event

    parsed = await msp.parse_responses_stream(
        replay(), msp.image_segmentation_format()
    ).final_result()
    return parsed, saved["spec"]


def prepared_input(image, crop):
    prepared = image.crop(crop)
    prepared.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    prepared.save(buffer, format="JPEG", quality=95)
    image_hash = digest(buffer.getvalue())
    spec = {
        "image_sha256": image_hash,
        "model": "sam-3.1",
        "base_url": "https://api.meta.ai/v1",
        "prompt": "tile",
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }
    return prepared.size, image_hash, spec


def provenance_for(row, source_size, inputs):
    value = {
        "source_sha256": row["sha256"],
        "source_size": list(source_size),
        "model": "sam-3.1",
        "max_side": 1600,
        "prompt": "tile",
        "merge_code_sha256": digest(Path(merge_module.__file__).read_bytes()),
        "inputs": [
            {k: item[k] for k in ("run_id", "cache_key", "crop", "input_size", "input_sha256")}
            for item in inputs
        ],
    }
    return {"fingerprint": digest(json.dumps(value, sort_keys=True).encode()), **value}


def can_rescreen(existing, provenance, inputs, merged_path, input_paths):
    """Explicit-only reuse; validate even legacy artifacts against current input provenance."""
    summary = existing.get("summary", {})
    if summary.get("jobs_ok") != 9 or summary.get("errors"):
        return False
    stored = existing.get("provenance")
    if stored is not None and stored.get("fingerprint") != provenance["fingerprint"]:
        return False
    if stored is None and merged_path.stat().st_mtime_ns < max(
        p.stat().st_mtime_ns for p in input_paths
    ):
        return False
    known = {item["run_id"]: item for item in inputs}
    full = next((item for item in inputs if item["run_id"].endswith("_full")), None)
    if full is None or summary.get("baseline_raw_masks") != full["masks"]:
        return False
    crop_raw = sum(item["masks"] for item in inputs if not item["run_id"].endswith("_full"))
    if summary.get("crop_raw_masks") != crop_raw:
        return False
    seen = set()
    for detection in existing.get("detections", []):
        item = known.get(detection.get("run_id"))
        if item is None or detection.get("id") in seen:
            return False
        seen.add(detection["id"])
        if (
            detection.get("source_size") != provenance["source_size"]
            or list(detection.get("crop_box", [])) != item["crop"]
            or list(detection.get("input_size", [])) != item["input_size"]
        ):
            return False
    return True


def draw_contours(draw, detection, scale, color, width=1):
    for contour in detection["contours"]:
        points = [(p[0] * scale, p[1] * scale) for p in contour["points"]]
        if len(points) > 1:
            draw.line(points + [points[0]], fill=color, width=width)


def region_mask(region, size):
    width, height = size
    mask = np.zeros((height, width), np.uint8)
    for polygon in region.get("include", []):
        points = np.round(np.array(polygon) * [width, height]).astype(np.int32)
        cv2.fillPoly(mask, [points], 1)
    for polygon in region.get("exclude", []):
        points = np.round(np.array(polygon) * [width, height]).astype(np.int32)
        cv2.fillPoly(mask, [points], 0)
    return mask


def screen(detections, region, source_size):
    scale = min(1, 2000 / max(source_size))
    size = (round(source_size[0] * scale), round(source_size[1] * scale))
    region_raster = region_mask(region, size)
    for detection in detections:
        left, top, right, bottom = detection["box"]
        x0, y0 = max(0, int(left * scale)), max(0, int(top * scale))
        x1 = min(size[0], int(np.ceil(right * scale)) + 1)
        y1 = min(size[1], int(np.ceil(bottom * scale)) + 1)
        raster = np.zeros((max(0, y1 - y0), max(0, x1 - x0)), np.uint8)
        if raster.size:
            for contour in sorted(
                detection["contours"], key=lambda c: c.get("depth", int(c["hole"]))
            ):
                points = np.round(np.array(contour["points"]) * scale - [x0, y0]).astype(np.int32)
                cv2.fillPoly(raster, [points], 0 if contour["hole"] else 1)
            area = int(raster.sum())
            overlap = int((raster * region_raster[y0:y1, x0:x1]).sum())
            fraction = overlap / area if area else 0
        else:
            fraction = 0
        detection["wall_fraction"] = round(fraction, 4)
        detection["wall_candidate"] = bool(fraction >= 0.95 and region.get("status") == "planar")
        detection["complete_wall_candidate"] = bool(
            detection["wall_candidate"] and not detection["edge_truncated"]
        )
    return detections


def overlay(path, detections, region, output):
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((2200, 2200))
    source_size = detections[0]["source_size"] if detections else Image.open(path).size
    scale = image.width / source_size[0]
    draw = ImageDraw.Draw(image)
    for polygon in region.get("include", []):
        points = [(x * image.width, y * image.height) for x, y in polygon]
        draw.line(points + [points[0]], fill="#59b9ff", width=3)
    for detection in detections:
        color = "#37e997" if detection.get("complete_wall_candidate") else "#a6a6a6"
        draw_contours(
            draw, detection, scale, color, 2 if detection.get("complete_wall_candidate") else 1
        )
        if detection.get("complete_wall_candidate"):
            x, y, _, _ = detection["box"]
            label = str(detection["review_id"])
            draw.text(
                (x * scale + 2, y * scale + 2),
                label,
                fill="#ffffff",
                stroke_width=1,
                stroke_fill="#15251d",
            )
    image.save(output, quality=92)


async def process_image(row, regions, baseline, rescreen_existing=False):
    number, stem = int(row["number"]), f"{int(row['number']):02d}"
    path = FOLDER / row["file"]
    if digest(path.read_bytes()) != row["sha256"]:
        raise ValueError(f"Source hash mismatch: {stem}")
    with Image.open(path) as original:
        source_image = ImageOps.exif_transpose(original).convert("RGB")
    source_size = source_image.size
    valid_jobs, errors, inputs, input_paths = 0, [], [], [path, Path(merge_module.__file__)]
    for index, expected_box in enumerate(crops_for(source_size)):
        job_path = OUT / "jobs" / f"{stem}_crop{index:02d}.json"
        if not job_path.exists():
            errors.append(f"crop {index}: pending")
            continue
        job = json.loads(job_path.read_text())
        if job["status"] != "ok":
            errors.append(f"crop {index}: {job['status']}")
            continue
        expected_size, expected_hash, spec = prepared_input(source_image, expected_box)
        if (
            job["source_sha256"] != row["sha256"]
            or tuple(job["crop"]) != expected_box
            or tuple(job["source_size"]) != source_size
            or tuple(job["input_size"]) != expected_size
            or job["input_sha256"] != expected_hash
            or job.get("model", "sam-3.1") != "sam-3.1"
            or job.get("max_side", 1600) != 1600
        ):
            raise ValueError(f"Stale job configuration: {job_path.name}")
        read_cache(job["cache_key"], expected_size, spec)
        inputs.append(
            {
                "run_id": job["tag"],
                "cache_key": job["cache_key"],
                "crop": list(expected_box),
                "input_size": list(expected_size),
                "input_sha256": expected_hash,
                "spec": spec,
                "masks": job.get("masks", 0),
            }
        )
        input_paths.append(CACHE / f"{job['cache_key']}.json")
        valid_jobs += 1
    full = next(
        (
            r
            for r in baseline
            if r.get("tag") == f"{stem}_tile_full_max1600" and r.get("status") == "ok"
        ),
        None,
    )
    baseline_masks = 0
    if full:
        crop = (0, 0, *source_size)
        size, image_hash, spec = prepared_input(source_image, crop)
        if tuple(full["image_size"]) != size:
            raise ValueError(f"Stale full-frame input dimensions: {stem}")
        read_cache(full["cache_key"], size, spec)
        baseline_masks = full["masks"]
        input_paths.append(CACHE / f"{full['cache_key']}.json")
        inputs.append(
            {
                "run_id": f"{stem}_full",
                "cache_key": full["cache_key"],
                "crop": list(crop),
                "input_size": list(size),
                "input_sha256": image_hash,
                "spec": spec,
                "masks": baseline_masks,
            }
        )
    else:
        errors.append("baseline: missing")
    source_image.close()
    provenance = provenance_for(row, source_size, inputs)
    merged_path = OUT / f"{stem}_merged.json"
    existing = (
        json.loads(merged_path.read_text()) if rescreen_existing and merged_path.exists() else None
    )
    reused = bool(
        valid_jobs == 9
        and not errors
        and existing
        and can_rescreen(existing, provenance, inputs, merged_path, input_paths)
    )
    if reused:
        kept = existing["detections"]
        diag, crop_diag = existing["deduplication"], existing["crop_deduplication"]
        previous = existing["summary"]
        crop_count = previous["crop_candidates_before_merge"]
        crop_unique = previous["crop_unique"]
        combined_count = previous["combined_candidates_before_merge"]
        crop_raw = previous["crop_raw_masks"]
        baseline_kept = existing.get("baseline_detections")
    else:
        detections = []
        for item in inputs:
            parsed, _ = await parse_cache(item["cache_key"], item["input_size"], item["spec"])
            records = [r for r in parsed.records if isinstance(r, msp.SegmentationMaskRecord)]
            if len(records) != item["masks"]:
                raise ValueError(f"Cached mask count mismatch: {item['run_id']}")
            for record in records:
                detections.append(
                    convert_record(
                        record,
                        tuple(item["input_size"]),
                        tuple(item["crop"]),
                        source_size,
                        item["run_id"],
                    )
                )
        crop_raw = sum(d["run_id"] != f"{stem}_full" for d in detections)
        crop_candidates = [
            d for d in detections if d["candidate"] and d["run_id"] != f"{stem}_full"
        ]
        crop_kept, crop_diag = merge_detections(crop_candidates)
        crop_count, crop_unique = len(crop_candidates), len(crop_kept)
        candidates = [d for d in detections if d["candidate"]]
        kept, diag = merge_detections(candidates)
        combined_count = len(candidates)
        baseline_kept, _ = merge_detections(
            [d for d in candidates if d["run_id"] == f"{stem}_full"]
        )
    if baseline_kept is None:
        baseline_kept = []
        for item in inputs:
            if item["run_id"] == f"{stem}_full":
                parsed, _ = await parse_cache(item["cache_key"], item["input_size"], item["spec"])
                converted = [
                    convert_record(
                        record,
                        tuple(item["input_size"]),
                        tuple(item["crop"]),
                        source_size,
                        item["run_id"],
                    )
                    for record in parsed.records
                    if isinstance(record, msp.SegmentationMaskRecord)
                ]
                baseline_kept, _ = merge_detections([d for d in converted if d["candidate"]])
    region = regions.get(stem, {"status": "uncertain", "include": [], "exclude": []})
    if region.get("source_sha256") and region["source_sha256"] != row["sha256"]:
        raise ValueError(f"Region source mismatch: {stem}")
    kept = screen(kept, region, source_size)
    baseline_kept = screen(baseline_kept, region, source_size)
    for index, detection in enumerate(kept):
        detection["review_id"] = index + 1
    complete = valid_jobs == 9 and not errors
    eligible = complete and region["status"] == "planar"
    summary = {
        "image": number,
        "file": row["file"],
        "jobs_ok": valid_jobs,
        "errors": errors,
        "complete": complete,
        "eligible": eligible,
        "reused_merge": reused,
        "baseline_raw_masks": baseline_masks,
        "baseline_complete_wall_candidates": sum(
            d["complete_wall_candidate"] for d in baseline_kept
        ),
        "crop_raw_masks": crop_raw,
        "crop_candidates_before_merge": crop_count,
        "crop_unique": crop_unique,
        "combined_candidates_before_merge": combined_count,
        "combined_unique": len(kept),
        "wall_candidates": sum(d["wall_candidate"] for d in kept),
        "complete_wall_candidates": sum(d["complete_wall_candidate"] for d in kept),
        "region_status": region["status"],
        "manual_tile_verification": "not completed",
        "area_accuracy": "not testable without physical reference measurements",
    }
    merged_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "provenance": provenance,
                "region": region,
                "detections": kept,
                "baseline_detections": baseline_kept,
                "deduplication": diag,
                "crop_deduplication": crop_diag,
            },
            indent=2,
        )
    )
    overlay(path, kept, region, OUT / f"{stem}_merged.jpg")
    return summary


def process_image_worker(task):
    """Process-pool entry point: offline decoding only, never API construction."""
    global ROOT, CACHE, OUT, FOLDER
    row, regions, baseline, rescreen_existing, paths = task
    ROOT, CACHE, OUT, FOLDER = (Path(value) for value in paths)
    return asyncio.run(process_image(row, regions, baseline, rescreen_existing))


async def main(rescreen_existing=False, workers=1):
    if not 1 <= workers <= 4:
        raise ValueError("Use one to four offline analysis workers")
    OUT.mkdir(exist_ok=True, parents=True)
    rows = list(csv.DictReader((FOLDER / "sources.csv").open(encoding="utf-8-sig")))
    if not rows:
        raise ValueError("No source images to analyze")
    if len({int(row["number"]) for row in rows}) != len(rows):
        raise ValueError("Duplicate image numbers would overwrite worker artifacts")
    regions_path = ROOT / "validation/tile_wall_regions.json"
    regions = json.loads(regions_path.read_text())["images"] if regions_path.exists() else {}
    baseline = json.loads((ROOT / "outputs/tile_benchmark/runs.json").read_text())
    summaries = []
    if workers == 1:
        for row in rows:
            summary = await process_image(row, regions, baseline, rescreen_existing)
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
    else:
        paths = [str(path) for path in (ROOT, CACHE, OUT, FOLDER)]
        tasks = [(row, regions, baseline, rescreen_existing, paths) for row in rows]
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            for summary in pool.map(process_image_worker, tasks):
                summaries.append(summary)
                print(json.dumps(summary), flush=True)
    # Workers write only their own NN_merged artifacts. Parent owns all aggregate files.
    (OUT / "summary.json").write_text(json.dumps(summaries, indent=2))
    write_reports(summaries)


def write_reports(summaries):
    keys = [k for k in summaries[0] if k not in ("errors", "area_accuracy")]
    with (OUT / "results.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)
    complete_count = sum(s["complete"] for s in summaries)
    baseline_threshold = sum(
        s["eligible"] and s["baseline_complete_wall_candidates"] >= 30 for s in summaries
    )
    combined_threshold = sum(
        s["eligible"] and s["complete_wall_candidates"] >= 30 for s in summaries
    )
    outcome = (
        f"<p><strong>Completed: {complete_count}/{len(summaries)} photos. "
        f"At least 30 screened wall candidates: {baseline_threshold}/{len(summaries)} "
        f"with the full frame, {combined_threshold}/{len(summaries)} with full frame plus "
        "crops.</strong></p>"
        "<p>The plan requires at least 30 reliable masks on 16 of 20 walls. "
        "Candidate counts do not establish that gate or measurement accuracy. "
        "The combined method uses ten inputs per photo versus one for the baseline; "
        "this compares candidate yield, not equal-cost performance.</p>"
    )
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Tile crop
experiment</title>
<style>body{font:16px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:20px}
img{max-width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}
table{border-collapse:collapse}a{color:#175c46}</style><h1>Crop detection and duplicate
removal</h1>""" + outcome + """
<p>Fixed tile prompt, 3×3 overlapping crops, 1600-pixel maximum long side per crop.
Detections are transformed to source coordinates, deduplicated, and combined with cached
full-frame tile results.</p>
<p>Green numbered contours: shape/confidence-screened, untruncated candidates within the chosen
wall.
Grey: other retained candidates. Blue: chosen wall region. These are not verified ground-truth
masks.</p>
<table><tr><th>Photo</th><th>Jobs</th><th>Baseline raw</th><th>Baseline same wall</th>
<th>Crop raw</th><th>Crop unique</th>
<th>Combined unique</th><th>Complete wall candidates</th><th>Region</th><th>Complete</th></tr>"""
    contact = Image.new("RGB", (1600, 5 * 360), "#f7f7f4")
    for index, summary in enumerate(summaries):
        stem = f"{summary['image']:02d}"
        document += f'<tr><td><a href="{stem}_merged.jpg">{stem}</a></td>'
        for key in [
            "jobs_ok",
            "baseline_raw_masks",
            "baseline_complete_wall_candidates",
            "crop_raw_masks",
            "crop_unique",
            "combined_unique",
            "complete_wall_candidates",
            "region_status",
            "complete",
        ]:
            document += f"<td>{html.escape(str(summary[key]))}</td>"
        document += "</tr>"
        with Image.open(OUT / f"{stem}_merged.jpg") as source:
            thumb = ImageOps.contain(source, (400, 320))
            x, y = (index % 4) * 400, (index // 4) * 360
            contact.paste(thumb, (x + (400 - thumb.width) // 2, y))
            ImageDraw.Draw(contact).text(
                (x + 8, y + 326),
                f"{stem}: {summary['complete_wall_candidates']} wall candidates; "
                f"{summary['region_status']}",
                fill="black",
            )
    contact.save(OUT / "contact.jpg")
    document += (
        '</table><h2>Overlays</h2><img src="contact.jpg" alt="Merged wall candidate overlays">'
    )
    document += (
        "<p>Open each photo number for full-size numbered contours. "
        "No area-accuracy claim is possible.</p></html>"
    )
    (OUT / "report.html").write_text(document)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rescreen-existing",
        action="store_true",
        help="Reuse strictly validated complete merges, recomputing wall screening",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, 5),
        default=1,
        help="Offline image decoder processes (1–4); never makes API calls",
    )
    args = parser.parse_args()
    asyncio.run(main(rescreen_existing=args.rescreen_existing, workers=args.workers))
