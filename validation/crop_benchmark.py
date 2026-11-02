"""Run all twenty tile images through a fixed 3x3 SAM crop strategy, with cached requests."""

import argparse
import asyncio
import csv
import json
from datetime import datetime
from math import isfinite
from uuid import uuid4
from zoneinfo import ZoneInfo

from openai import APIStatusError, AsyncOpenAI
from PIL import Image, ImageOps

from validation.benchmark_tiles import (
    CACHE,
    ROOT,
    Settings,
    crops_for,
    digest,
    infer,
    input_image,
    summarize,
)

OUT = ROOT / "outputs/tile_crops"
SCHEMA_VERSION = 1


def experiment_config(settings, max_side):
    """Public request/transform settings only; no key material enters fingerprints."""
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": "original-space-grid3x3-overlap0.04-v1",
        "model": settings.meta_sam_model,
        "base_url": settings.meta_api_base_url.rstrip("/"),
        "prompt": "tile",
        "max_side": max_side,
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
        "image_preparation": "exif-transpose-rgb-pillow-thumbnail-jpeg95-v1",
    }


def job_matches_manifest(record, expected, manifest):
    """Reject stale on-disk jobs from earlier runs or different transform settings."""
    return (
        record.get("run_id") == manifest["run_id"]
        and record.get("config_fingerprint") == manifest["config_fingerprint"]
        and all(record.get(key) == expected[key] for key in expected)
    )


def resume_completed_job(path, expected, config, overlay_path):
    """Reuse verified completed measurements; never trust old status or filenames alone."""
    if not path.exists() or not overlay_path.exists():
        return None
    try:
        previous = json.loads(path.read_text())
        if previous.get("status") != "ok":
            return None
        for key in (
            "tag",
            "file",
            "source_sha256",
            "source_size",
            "crop",
            "input_size",
            "prompt",
            "input_sha256",
        ):
            if previous.get(key) != expected[key]:
                return None
        for key in ("model", "max_side", "config_fingerprint"):
            if key in previous and previous[key] != expected[key]:
                return None
        masks, candidates, seconds = previous["masks"], previous["candidates"], previous["seconds"]
        if (
            type(masks) is not int
            or type(candidates) is not int
            or not 0 <= candidates <= masks
            or not isfinite(seconds)
            or seconds < 0
        ):
            return None
        spec = {
            "image_sha256": expected["input_sha256"],
            "model": config["model"],
            "base_url": config["base_url"],
            "prompt": config["prompt"],
            "metadata": config["metadata"],
        }
        cache_key = digest(json.dumps(spec, sort_keys=True).encode())
        if previous["cache_key"] != cache_key:
            return None
        cache = json.loads((CACHE / f"{cache_key}.json").read_text())
        if cache["spec"] != spec or not any(
            event.get("type") == "response.completed" for event in cache["events"]
        ):
            return None
        return {
            "status": "ok",
            "cache_key": cache_key,
            "cached": True,
            "resumed": True,
            "seconds": seconds,
            "masks": masks,
            "candidates": candidates,
        }
    except (OSError, ValueError, KeyError, TypeError):
        # Missing/corrupt/mismatching local artifacts fall back to the normal cached/API path.
        return None


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", nargs="+", type=int, default=list(range(1, 21)))
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--max-side", type=int, default=1600)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 6 or not 1 <= args.max_side <= 1600:
        raise SystemExit("Use concurrency 1–6 and long side 1–1600")
    settings = Settings()
    if settings.meta_api_base_url.rstrip("/") != "https://api.meta.ai/v1":
        raise SystemExit("Unexpected API host; credential not sent")
    if not settings.meta_api_key.get_secret_value():
        raise SystemExit("META_API_KEY is empty")
    config = experiment_config(settings, args.max_side)
    config_fingerprint = digest(json.dumps(config, sort_keys=True).encode())
    run_id = uuid4().hex
    folder = ROOT / "bathroom_tiles_20"
    sources = list(csv.DictReader((folder / "sources.csv").open(encoding="utf-8-sig")))
    jobs = []
    for row in sources:
        if int(row["number"]) not in args.images:
            continue
        path = folder / row["file"]
        if digest(path.read_bytes()) != row["sha256"]:
            raise SystemExit(f"Source changed: {path.name}")
        with Image.open(path) as original:
            source_size = ImageOps.exif_transpose(original).size
        for index, box in enumerate(crops_for(source_size)):
            jobs.append((row, index, box, source_size))
    if not jobs or len(jobs) > 180:
        raise SystemExit("Expected 1–180 crop jobs")
    expected = [
        {
            "tag": f"{int(row['number']):02d}_crop{index:02d}",
            "image_number": int(row["number"]),
            "file": row["file"],
            "source_sha256": row["sha256"],
            "source_size": list(source_size),
            "crop": list(crop),
        }
        for row, index, crop, source_size in jobs
    ]
    manifest = {
        "run_id": run_id,
        "started_at": datetime.now(ZoneInfo("Asia/Almaty")).isoformat(),
        "config": config,
        "config_fingerprint": config_fingerprint,
        "jobs": expected,
    }
    write_json(OUT / "manifest.json", manifest)
    outcomes = {}
    (OUT / "overlays").mkdir(parents=True, exist_ok=True)
    queue = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)
    fatal = asyncio.Event()
    async with AsyncOpenAI(
        api_key=settings.meta_api_key.get_secret_value(),
        base_url=settings.meta_api_base_url,
        timeout=180,
        max_retries=0,
    ) as client:

        async def worker():
            while not queue.empty() and not fatal.is_set():
                row, index, crop, source_size = queue.get_nowait()
                tag = f"{int(row['number']):02d}_crop{index:02d}"
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    "config_fingerprint": config_fingerprint,
                    "model": settings.meta_sam_model,
                    "max_side": args.max_side,
                    "tag": tag,
                    "image_number": int(row["number"]),
                    "file": row["file"],
                    "source_sha256": row["sha256"],
                    "source_size": list(source_size),
                    "crop": list(crop),
                    "prompt": "tile",
                    "timestamp": datetime.now(ZoneInfo("Asia/Almaty")).isoformat(),
                }
                try:
                    image, data = input_image(folder / row["file"], crop, args.max_side)
                    record.update(input_size=list(image.size), input_sha256=digest(data))
                    overlay_path = OUT / "overlays" / f"{tag}.jpg"
                    resumed = resume_completed_job(
                        OUT / "jobs" / f"{tag}.json", record, config, overlay_path
                    )
                    if resumed is not None:
                        record.update(resumed)
                    else:
                        parsed, seconds, cached, key = await asyncio.wait_for(
                            infer(client, settings, data, "tile"),
                            timeout=240,
                        )
                        masks = summarize(parsed, image, overlay_path)
                        record.update(
                            status="ok",
                            cache_key=key,
                            cached=cached,
                            seconds=round(seconds, 3),
                            masks=len(masks),
                            candidates=sum(m["candidate"] for m in masks),
                        )
                except APIStatusError as error:
                    record.update(status="http_error", http_status=error.status_code)
                    if error.status_code in (400, 401, 403, 404, 429):
                        fatal.set()
                except Exception as error:
                    record.update(status="error", error_type=type(error).__name__)
                    # Failed jobs are visible and never silently treated as zero detections.
                write_json(OUT / "jobs" / f"{tag}.json", record)
                outcomes[tag] = record
                print(
                    json.dumps(
                        {
                            k: record[k]
                            for k in ["tag", "status", "masks", "candidates", "cached"]
                            if k in record
                        }
                    ),
                    flush=True,
                )
                queue.task_done()

        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    missing = [job["tag"] for job in expected if job["tag"] not in outcomes]
    failed = [tag for tag, record in outcomes.items() if record["status"] != "ok"]
    write_json(
        OUT / "batch_summary.json",
        {
            "run_id": run_id,
            "config_fingerprint": config_fingerprint,
            "planned": len(jobs),
            "completed": len(outcomes),
            "successful": len(outcomes) - len(failed),
            "failed": failed,
            "missing": missing,
            "status": "complete" if not failed and not missing else "incomplete",
        },
    )
    if fatal.is_set():
        raise SystemExit("Stopped new jobs after API rejection/throttling; see recorded job status")
    if failed or missing:
        raise SystemExit("Incomplete crop run; inspect batch_summary.json and job error statuses")


if __name__ == "__main__":
    asyncio.run(main())
