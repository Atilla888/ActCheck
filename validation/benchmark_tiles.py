"""Cached SAM segmentation benchmark; candidate counts are NOT validated tile counts."""

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import time
from pathlib import Path

import cv2
import meta_sam_parser as msp
import numpy as np
from openai import APIStatusError, AsyncOpenAI
from PIL import Image, ImageDraw, ImageOps
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/tile_benchmark"
CACHE = ROOT / "data/cache/sam_benchmark"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    meta_api_key: SecretStr
    meta_api_base_url: str = "https://api.meta.ai/v1"
    meta_sam_model: str = "sam-3.1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(folder):
    rows = list(csv.DictReader((folder / "sources.csv").open(encoding="utf-8-sig")))
    seen = set()
    for row in rows:
        path = folder / row["file"]
        data = path.read_bytes()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
        sha = digest(data)
        row["audit"] = {
            "decodes": True,
            "sha256_matches": sha == row["sha256"],
            "dimensions_match": (width, height) == (int(row["width_px"]), int(row["height_px"])),
            "unique": sha not in seen,
            "bytes": len(data),
        }
        seen.add(sha)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "input_audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    return rows


def input_image(path, crop=None, max_side=0):
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        if crop:
            image = image.crop(crop)
        if max_side:
            image.thumbnail((max_side, max_side))
        if (
            not max_side
            and crop is None
            and original.getexif().get(274, 1) == 1
            and original.format == "JPEG"
        ):
            data = path.read_bytes()
        else:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=95)
            data = buffer.getvalue()
    return image, data


async def infer(client, settings, data, prompt):
    spec = {
        "image_sha256": digest(data),
        "model": settings.meta_sam_model,
        "base_url": settings.meta_api_base_url,
        "prompt": prompt,
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }
    key = digest(json.dumps(spec, sort_keys=True).encode())
    cache = CACHE / f"{key}.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("spec") != spec:
            raise ValueError("Cached request spec mismatch")
        cached = True
    else:
        start = time.monotonic()
        stream = await client.responses.create(
            model=settings.meta_sam_model,
            stream=True,
            metadata=spec["metadata"],
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": "data:image/jpeg;base64,"
                            + base64.b64encode(data).decode(),
                        },
                    ],
                }
            ],
        )
        events = []
        try:
            async for event in stream:
                events.append(event.model_dump())
        finally:
            await stream.close()
        if not any(e["type"] == "response.completed" for e in events):
            raise RuntimeError("Stream did not complete; response not cached")
        saved = {"spec": spec, "seconds": time.monotonic() - start, "events": events}
        CACHE.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix(".tmp")
        temp.write_text(json.dumps(saved))
        temp.replace(cache)
        cached = False

    async def replay():
        for event in saved["events"]:
            yield event

    parsed = await msp.parse_responses_stream(
        replay(), msp.image_segmentation_format()
    ).final_result()
    return parsed, saved["seconds"], cached, key


def summarize(parsed, image, output):
    width, height = image.size
    scale = min(1, 1400 / max(width, height))
    preview = image.resize((round(width * scale), round(height * scale)))
    draw = ImageDraw.Draw(preview)
    records = []
    for record in parsed.records:
        if not isinstance(record, msp.SegmentationMaskRecord):
            continue
        mask = np.frombuffer(msp.decode_mask_to_raster(record.mask), np.uint8).reshape(
            record.mask.height, record.mask.width
        )
        area = int(np.count_nonzero(mask))
        bounds = record.bounds
        box = [bounds.left, bounds.top, bounds.right, bounds.bottom]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rect_area = 0
        if contours:
            rectangle = cv2.minAreaRect(max(contours, key=cv2.contourArea))
            rect_area = rectangle[1][0] * rectangle[1][1]
        rectangularity = min(1, area / max(1, rect_area))
        candidate = bool(
            area >= 25
            and area <= width * height * 0.1
            and rectangularity >= 0.65
            and (record.confidence or 0) >= 0.5
        )
        records.append(
            {
                "id": record.object_id,
                "box": box,
                "confidence": record.confidence,
                "mask_size": [record.mask.width, record.mask.height],
                "area_px": area,
                "rectangularity": rectangularity,
                "candidate": candidate,
            }
        )
        color = "#37d980" if candidate else "#f5a142"
        # Mask contour uses local raster coordinates plus the official source-space bounds.
        for contour in contours:
            points = [
                (
                    round((float(p[0][0]) + bounds.left) * scale),
                    round((float(p[0][1]) + bounds.top) * scale),
                )
                for p in contour
            ]
            if len(points) >= 2:
                draw.line(points + [points[0]], fill=color, width=1)
    preview.save(output)
    return records


def crops_for(size):
    width, height = size
    for y in range(3):
        for x in range(3):
            yield (
                max(0, int((x / 3 - 0.04) * width)),
                max(0, int((y / 3 - 0.04) * height)),
                min(width, int(((x + 1) / 3 + 0.04) * width)),
                min(height, int(((y + 1) / 3 + 0.04) * height)),
            )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "bathroom_tiles_20")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--prompts", nargs="+", default=["tile", "wall tile", "ceramic tile"])
    parser.add_argument(
        "--crops", action="store_true", help="Also compare nine overlapping crops on image 01"
    )
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-side", type=int, default=0)
    args = parser.parse_args()
    rows = audit(args.folder)
    if not all(
        all(r["audit"][k] for k in ["decodes", "sha256_matches", "dimensions_match", "unique"])
        for r in rows
    ):
        raise SystemExit("Input audit failed; inspect input_audit.json")
    print(f"Input audit: {len(rows)} valid unique images; hashes and dimensions match.", flush=True)
    if args.audit_only:
        return
    settings = Settings()
    if settings.meta_api_base_url.rstrip("/") != "https://api.meta.ai/v1":
        raise SystemExit("Unexpected API host; refusing to send credential")
    if not settings.meta_api_key.get_secret_value():
        raise SystemExit("META_API_KEY is empty")
    results_path = OUT / "runs.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else []
    async with AsyncOpenAI(
        api_key=settings.meta_api_key.get_secret_value(),
        base_url=settings.meta_api_base_url,
        timeout=180,
        max_retries=0,
    ) as client:
        jobs = [(r, prompt, None) for r in rows[: args.limit] for prompt in args.prompts]
        if args.crops:
            with Image.open(args.folder / rows[0]["file"]) as first:
                jobs += [
                    (rows[0], "tile", c) for c in crops_for(ImageOps.exif_transpose(first).size)
                ]
        if len(jobs) > 69:
            raise SystemExit("Request budget exceeded (maximum 69 jobs per run)")

        async def run_job(row, prompt, crop):
            nonlocal results
            tag = f"{int(row['number']):02d}_{prompt.replace(' ', '_')}" + (
                f"_crop_{crop[0]}_{crop[1]}" if crop else "_full"
            )
            if args.max_side:
                tag += f"_max{args.max_side}"
            image, data = input_image(args.folder / row["file"], crop, args.max_side)
            try:
                parsed, seconds, cached, key = await infer(client, settings, data, prompt)
                records = summarize(parsed, image, OUT / f"{tag}.jpg")
                (OUT / f"{tag}_masks.json").write_text(json.dumps(records, indent=2))
                result = {
                    "tag": tag,
                    "file": row["file"],
                    "prompt": prompt,
                    "crop": crop,
                    "image_size": list(image.size),
                    "masks": len(records),
                    "candidates": sum(r["candidate"] for r in records),
                    "seconds": round(seconds, 3),
                    "cached": cached,
                    "cache_key": key,
                    "status": "ok",
                    "gate_status": "manual_wall_review_required",
                }
            except APIStatusError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                error = body.get("error", body)
                message = str(error.get("message", "")) if isinstance(error, dict) else ""
                message = message.replace(settings.meta_api_key.get_secret_value(), "[REDACTED]")
                if "base64," in message:
                    message = "Error includes image data; withheld"
                result = {
                    "tag": tag,
                    "status": "http_error",
                    "http_status": exc.status_code,
                    "message": message[:500],
                    "image_size": list(image.size),
                }
                results.append(result)
                results_path.write_text(json.dumps(results, indent=2))
                print(json.dumps(result), flush=True)
                raise SystemExit("Stopped on API error; no further requests sent") from None
            except Exception as exc:
                result = {"tag": tag, "status": "error", "error_type": type(exc).__name__}
                results.append(result)
                results_path.write_text(json.dumps(results, indent=2))
                print(json.dumps(result), flush=True)
                raise SystemExit(
                    "Stopped; inspect runner and cached response before retrying"
                ) from None
            results = [r for r in results if r["tag"] != tag] + [result]
            results_path.write_text(json.dumps(results, indent=2))
            print(
                json.dumps(
                    {k: result[k] for k in ["tag", "masks", "candidates", "seconds", "cached"]}
                ),
                flush=True,
            )

        for start in range(0, len(jobs), 6):
            await asyncio.gather(*(run_job(*job) for job in jobs[start : start + 6]))


if __name__ == "__main__":
    asyncio.run(main())
