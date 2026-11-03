"""Shared SAM client: benchmark-compatible cache keys and key-free cached segmentation."""

import asyncio
import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest
from PIL import Image, ImageOps

from measure import sam_client as sam

PHOTO_01 = sam.ROOT / "bathroom_tiles_20/photos/01_mosaic_closeup.jpg"
JOB_01_CROP04 = sam.ROOT / "outputs/tile_crops/jobs/01_crop04.json"


def keyless_settings():
    return sam.Settings(_env_file=None, meta_api_key=None)


def oriented(path):
    with Image.open(path) as original:
        return ImageOps.exif_transpose(original).convert("RGB")


@pytest.mark.skipif(not PHOTO_01.exists() or not JOB_01_CROP04.exists(), reason="local photo")
def test_prepare_matches_benchmark_cache_key():
    image = oriented(PHOTO_01)
    crop = list(sam.crops_for(image.size))[4]
    size, data = sam.prepare(image, crop)
    job = json.loads(JOB_01_CROP04.read_text())
    assert list(size) == job["input_size"]
    assert sam.cache_key(sam.request_spec(data, "tile", keyless_settings())) == job["cache_key"]


@pytest.mark.skipif(not PHOTO_01.exists(), reason="local photo and cache")
def test_segment_uses_cache_without_client():
    result = sam.segment(oriented(PHOTO_01), settings=keyless_settings())
    assert result.requests == 10
    assert result.cached == 10
    assert result.source_size == (7296, 5472)
    assert len(result.tiles) >= 100
    assert all(detection["candidate"] for detection in result.tiles)


def test_cache_miss_without_key_raises(tmp_path):
    pixels = np.random.default_rng(0).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    with pytest.raises(sam.SegmentationError, match="META_API_KEY"):
        sam.segment(Image.fromarray(pixels), settings=keyless_settings(), cache_dir=tmp_path)


def test_unofficial_endpoint_is_refused_before_sending_key(tmp_path):
    settings = sam.Settings(
        _env_file=None, meta_api_key="unit-test-not-a-real-key", meta_api_base_url="https://x.test"
    )
    with pytest.raises(sam.SegmentationError, match="endpoint"):
        sam.segment(Image.new("RGB", (64, 64)), settings=settings, cache_dir=tmp_path)


@pytest.mark.skipif(not PHOTO_01.exists(), reason="local photo and cache")
def test_second_segment_reuses_converted_masks():
    image = oriented(PHOTO_01)
    first = sam.segment(image, settings=keyless_settings())
    started = time.monotonic()
    second = sam.segment(image, settings=keyless_settings())
    assert time.monotonic() - started < 5
    assert second.tiles == first.tiles


def test_conversion_falls_back_when_process_pool_fails(monkeypatch):
    class BrokenPool:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def map(self, *args):
            from concurrent.futures.process import BrokenProcessPool

            raise BrokenProcessPool("unguarded __main__")

    monkeypatch.setattr(sam, "ProcessPoolExecutor", BrokenPool)
    converted = sam._convert_all([("missing-response", (0, 0, 1, 1), (1, 1), (1, 1), "r")] * 0)
    assert converted == []
    calls = []
    monkeypatch.setattr(sam, "_convert_response", lambda args: calls.append(args) or [])
    assert sam._convert_all([("a",), ("b",)]) == [[], []]
    assert calls == [("a",), ("b",)]


def test_single_worker_setting_converts_inline(monkeypatch):
    monkeypatch.setenv("ACTCHECK_SAM_WORKERS", "1")
    monkeypatch.setattr(sam, "ProcessPoolExecutor", None)  # would fail if used
    monkeypatch.setattr(sam, "_convert_response", lambda args: [args])
    assert sam._convert_all([("a",), ("b",)]) == [[("a",)], [("b",)]]


def _jobs(n=1):
    return [{"data": b"x", "prompt": "tile"} for _ in range(n)]


def test_stalled_request_is_retried(monkeypatch):
    calls = []

    async def fetch(client, settings, data, prompt, *, cache_dir):
        calls.append(prompt)
        if len(calls) == 1:
            await asyncio.sleep(10)  # stalled connection

    monkeypatch.setattr(sam, "fetch", fetch)
    monkeypatch.setattr(sam, "ATTEMPT_TIMEOUT", 0.05)
    asyncio.run(sam._fetch_all(_jobs(), object(), keyless_settings(), "unused"))
    assert len(calls) == 2


def test_persistent_failure_gives_up(monkeypatch):
    calls = []

    async def fetch(client, settings, data, prompt, *, cache_dir):
        calls.append(prompt)
        raise RuntimeError("Stream did not complete")

    monkeypatch.setattr(sam, "fetch", fetch)
    monkeypatch.setattr(sam, "ATTEMPTS", 2)
    with pytest.raises(sam.SegmentationError, match="after 2 attempts"):
        asyncio.run(sam._fetch_all(_jobs(), object(), keyless_settings(), "unused"))
    assert len(calls) == 2


SPAWN_SCRIPT = """
import multiprocessing, os, sys
sys.path.insert(0, os.environ["REPO"])
from PIL import Image
from measure import sam_client as sam

def log(text):
    with open(os.environ["MARK"], "a") as handle:
        handle.write(text + "\\n")

# Deliberately unguarded: a spawned worker re-imports this module as __mp_main__.
if multiprocessing.current_process().name != "MainProcess":
    log(f"reimport:{sam._in_spawn_bootstrap()}")

def child():
    settings = sam.Settings(_env_file=None, meta_api_key=None)
    try:
        sam.segment(Image.new("RGB", (64, 64)), settings=settings, cache_dir=os.environ["CACHE"])
    except Exception as error:  # a started child (uvicorn --reload) must reach the real checks
        log(f"run:{type(error).__name__}")

if __name__ == "__main__":
    process = multiprocessing.get_context("spawn").Process(target=child)
    process.start()
    process.join()
"""


def test_worker_guard_fires_only_while_a_spawned_child_reimports(tmp_path):
    script = tmp_path / "unguarded.py"
    script.write_text(SPAWN_SCRIPT)
    mark = tmp_path / "mark.txt"
    env = {**os.environ, "MARK": str(mark), "REPO": str(sam.ROOT), "CACHE": str(tmp_path)}
    subprocess.run([sys.executable, str(script)], env=env, check=True, timeout=180)
    assert mark.read_text().split() == ["reimport:True", "run:SegmentationError"]


def test_default_workers_are_capped(monkeypatch):
    monkeypatch.delenv("ACTCHECK_SAM_WORKERS", raising=False)
    monkeypatch.setattr(sam.os, "cpu_count", lambda: 64)
    assert sam._workers(20) == 4


def test_concurrent_cache_writes_do_not_collide(tmp_path):
    import threading

    target = tmp_path / "same.json"
    errors = []

    def write():
        try:
            for _ in range(30):
                sam._write_json(target, [1, 2, 3])
        except OSError as error:
            errors.append(error)

    threads = [threading.Thread(target=write) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and json.loads(target.read_text()) == [1, 2, 3]
