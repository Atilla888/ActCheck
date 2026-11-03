"""Cached SAM 3.1 segmentation shared by measurement and the validation benchmarks.

A request is identified by the prepared image bytes, model, endpoint, prompt and metadata.
Completed responses are stored on disk, so repeating a measurement never spends credits and
replays the same masks. Tile masks come from one full frame plus nine overlapping crops.
Decoding lossless masks is slow pure Python, so converted detections are cached as well and
first-time conversions run in parallel processes.
"""

import asyncio
import base64
import hashlib
import io
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path

import meta_sam_parser as msp
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, Timeout
from PIL import Image, ImageOps
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

import measure.crop_merge as crop_merge
from measure.crop_merge import convert_record, merge_detections

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/cache/sam_benchmark"  # shared with the benchmark runs
OFFICIAL_BASE_URL = "https://api.meta.ai/v1"
TILE_PROMPT = "tile"
MAX_SIDE = 1600
CONCURRENCY = 6
# A healthy request streams back in 1-6 s; a stalled connection used to hang until the 240 s
# timeout and fail the whole wall. Fail fast on connect, bound each attempt, retry transient errors.
CONNECT_TIMEOUT = 10
ATTEMPT_TIMEOUT = 60
ATTEMPTS = 3
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
METADATA = {"include_confidence": "true", "mask_encoding": "lossless"}
CONVERT_VERSION = hashlib.sha256(Path(crop_merge.__file__).read_bytes()).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    meta_api_key: SecretStr | None = None
    meta_api_base_url: str = OFFICIAL_BASE_URL
    meta_sam_model: str = "sam-3.1"


class SegmentationError(RuntimeError):
    """No usable segmentation: uncached request without a key, API rejection or broken stream."""


@dataclass
class Segmentation:
    source_size: tuple[int, int]
    tiles: list[dict]
    concepts: dict[str, list[dict]] = field(default_factory=dict)
    requests: int = 0
    cached: int = 0
    seconds: float = 0.0


def digest(data):
    return hashlib.sha256(data).hexdigest()


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


def prepare(image, crop=None, max_side=MAX_SIDE):
    """Encode an EXIF-oriented RGB image (optionally cropped) exactly as the benchmarks did."""
    prepared = image.crop(crop) if crop else image.copy()
    prepared.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    prepared.save(buffer, format="JPEG", quality=95)
    return prepared.size, buffer.getvalue()


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


def request_spec(data, prompt, settings):
    return {
        "image_sha256": digest(data),
        "model": settings.meta_sam_model,
        "base_url": settings.meta_api_base_url,
        "prompt": prompt,
        "metadata": METADATA,
    }


def cache_key(spec):
    return digest(json.dumps(spec, sort_keys=True).encode())


async def fetch(client, settings, data, prompt, *, cache_dir=CACHE):
    """Return (stored response, cache key, was cached); SAM is called only on a cache miss."""
    spec = request_spec(data, prompt, settings)
    key = cache_key(spec)
    cache = Path(cache_dir) / f"{key}.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("spec") != spec:
            raise ValueError("Cached request spec mismatch")
        return saved, key, True
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
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(data).decode(),
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
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_suffix(".tmp")
    temp.write_text(json.dumps(saved))
    temp.replace(cache)
    return saved, key, False


async def parse_saved(saved):
    async def replay():
        for event in saved["events"]:
            yield event

    return await msp.parse_responses_stream(
        replay(), msp.image_segmentation_format()
    ).final_result()


async def infer(client, settings, data, prompt, *, cache_dir=CACHE):
    saved, key, cached = await fetch(client, settings, data, prompt, cache_dir=cache_dir)
    return await parse_saved(saved), saved["seconds"], cached, key


def segment(
    image, concepts=(), *, tiles=True, crops=True, client=None, settings=None, cache_dir=CACHE
):
    """Tile masks (merged, source pixels) plus one full-frame detection list per concept."""
    started = time.monotonic()
    settings = settings or Settings()
    cache_dir = Path(cache_dir)
    jobs = [("full", None, TILE_PROMPT)] if tiles else []
    if tiles and crops:
        jobs += [(f"crop{i:02d}", box, TILE_PROMPT) for i, box in enumerate(crops_for(image.size))]
    jobs += [(f"concept:{concept}", None, concept) for concept in concepts]
    prepared = []
    for run_id, crop, prompt in jobs:
        size, data = prepare(image, crop)
        key = cache_key(request_spec(data, prompt, settings))
        box = crop or (0, 0, *image.size)
        converted = _converted_key(key, box, size, image.size, run_id)
        prepared.append(
            {
                "run_id": run_id,
                "prompt": prompt,
                "box": box,
                "size": size,
                "data": data,
                "response": cache_dir / f"{key}.json",
                "converted": cache_dir / "converted" / f"{converted}.json",
            }
        )
    missing = [job for job in prepared if not job["response"].exists()]
    if missing:
        asyncio.run(_fetch_missing(missing, client, settings, cache_dir))
    pending = [job for job in prepared if not job["converted"].exists()]
    args = [(j["response"], j["box"], j["size"], image.size, j["run_id"]) for j in pending]
    for job, detections in zip(pending, _convert_all(args), strict=True):
        _write_json(job["converted"], detections)
    tiles, found = [], {concept: [] for concept in concepts}
    for job in prepared:
        detections = json.loads(job["converted"].read_text())
        if job["run_id"].startswith("concept:"):
            found[job["prompt"]] += [
                d for d in detections if (d["confidence"] or 0) >= 0.5 and d["contours"]
            ]
        else:
            tiles += [d for d in detections if d["candidate"]]
    merged, _ = merge_detections(tiles)
    return Segmentation(
        source_size=image.size,
        tiles=merged,
        concepts=found,
        requests=len(prepared),
        cached=len(prepared) - len(missing),
        seconds=round(time.monotonic() - started, 3),
    )


def _converted_key(response_key, box, size, source_size, run_id):
    identity = [response_key, list(box), list(size), list(source_size), run_id, CONVERT_VERSION]
    return digest(json.dumps(identity).encode())


def _convert_all(args):
    """Convert responses in worker processes, or here when workers are unavailable.

    Workers use the spawn start method, which re-imports the caller's __main__; a script that
    calls segment() without an `if __name__ == "__main__":` guard breaks the pool, and the
    conversion then runs in this process, only slower. ACTCHECK_SAM_WORKERS=1 never spawns.
    """
    workers = min(len(args), int(os.environ.get("ACTCHECK_SAM_WORKERS", os.cpu_count() or 1)))
    if workers > 1:
        try:
            with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as pool:
                return list(pool.map(_convert_response, args))
        except (BrokenProcessPool, RuntimeError, OSError):
            pass
    return [_convert_response(arg) for arg in args]


def _convert_response(args):
    response, box, size, source_size, run_id = args
    parsed = asyncio.run(parse_saved(json.loads(Path(response).read_text())))
    return [
        convert_record(record, size, box, source_size, run_id)
        for record in parsed.records
        if isinstance(record, msp.SegmentationMaskRecord)
    ]


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


async def _fetch_missing(missing, client, settings, cache_dir):
    if client is not None:
        return await _fetch_all(missing, client, settings, cache_dir)
    if settings.meta_api_key is None or not settings.meta_api_key.get_secret_value():
        raise SegmentationError(f"{len(missing)} request(s) not cached and META_API_KEY is not set")
    if settings.meta_api_base_url.rstrip("/") != OFFICIAL_BASE_URL:
        raise SegmentationError("Unexpected SAM endpoint; credential not sent")
    async with AsyncOpenAI(
        api_key=settings.meta_api_key.get_secret_value(),
        base_url=settings.meta_api_base_url,
        timeout=Timeout(ATTEMPT_TIMEOUT, connect=CONNECT_TIMEOUT),
        max_retries=0,
    ) as owned:
        return await _fetch_all(missing, owned, settings, cache_dir)


async def _fetch_all(missing, client, settings, cache_dir):
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(job):
        async with limit:
            for attempt in range(ATTEMPTS):
                last = attempt == ATTEMPTS - 1
                try:
                    await asyncio.wait_for(
                        fetch(client, settings, job["data"], job["prompt"], cache_dir=cache_dir),
                        timeout=ATTEMPT_TIMEOUT,
                    )
                    return
                except APIStatusError as error:
                    status = error.status_code
                    if status not in RETRY_STATUS or last:
                        raise SegmentationError(f"SAM request rejected (HTTP {status})") from None
                except (APIConnectionError, TimeoutError, RuntimeError) as error:
                    if last:
                        name = type(error).__name__
                        raise SegmentationError(
                            f"SAM request failed after {ATTEMPTS} attempts ({name})"
                        ) from None
                await asyncio.sleep(2**attempt)

    await asyncio.gather(*(one(job) for job in missing))
