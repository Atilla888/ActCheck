"""Offline regression checks for benchmark coordinates and cache safety."""

import asyncio
import hashlib
import json
from pathlib import Path

from PIL import Image

from validation import benchmark_tiles as benchmark


def test_original_bytes_preserved_and_resize_does_not_modify_source(tmp_path):
    path = tmp_path / "wall.jpg"
    Image.new("RGB", (400, 200), "white").save(path)
    original = path.read_bytes()
    image, data = benchmark.input_image(path)
    assert image.size == (400, 200)
    assert data == original
    image, data = benchmark.input_image(path, max_side=100)
    assert image.size == (100, 50)
    assert data != original
    assert path.read_bytes() == original


def test_exif_rotation_precedes_crop_coordinates(tmp_path):
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (120, 60))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    oriented, _ = benchmark.input_image(path)
    assert oriented.size == (60, 120)
    cropped, _ = benchmark.input_image(path, crop=(0, 60, 60, 120))
    assert cropped.size == (60, 60)


def test_crop_grid_covers_image_and_has_overlap():
    width, height = 107, 73
    crops = list(benchmark.crops_for((width, height)))
    assert len(crops) == 9
    coverage = Image.new("L", (width, height))
    for left, top, right, bottom in crops:
        assert 0 <= left < right <= width
        assert 0 <= top < bottom <= height
        coverage.paste(255, (left, top, right, bottom))
    assert coverage.getextrema() == (255, 255)
    assert crops[0][2] > crops[1][0]
    assert crops[0][3] > crops[3][1]


def test_completed_zero_match_cache_requires_no_client_or_key_transmission(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "CACHE", tmp_path)
    settings = benchmark.Settings(_env_file=None, meta_api_key="unit-test-not-a-real-key")
    data = b"test-image-bytes"
    spec = {
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "model": settings.meta_sam_model,
        "base_url": settings.meta_api_base_url,
        "prompt": "tile",
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }
    key = benchmark.digest(json.dumps(spec, sort_keys=True).encode())
    Path(tmp_path / f"{key}.json").write_text(
        json.dumps(
            {
                "spec": spec,
                "seconds": 1.25,
                "events": [
                    {
                        "type": "response.output_text.done",
                        "item_id": "test-message",
                        "output_index": 0,
                        "content_index": 0,
                        "text": "",
                    },
                    {"type": "response.completed", "response": {"output": []}},
                ],
            }
        )
    )
    result, seconds, cached, actual_key = asyncio.run(benchmark.infer(None, settings, data, "tile"))
    assert len(result.records) == 0
    assert seconds == 1.25 and cached and actual_key == key
    assert "unit-test-not-a-real-key" not in Path(tmp_path / f"{key}.json").read_text()


def test_mismatched_cached_request_is_rejected_before_parser_or_client(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(benchmark, "CACHE", tmp_path)
    settings = benchmark.Settings(_env_file=None, meta_api_key="unit-test-not-a-real-key")
    data = b"test-image-bytes"
    spec = {
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "model": settings.meta_sam_model,
        "base_url": settings.meta_api_base_url,
        "prompt": "tile",
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }
    key = benchmark.digest(json.dumps(spec, sort_keys=True).encode())
    Path(tmp_path / f"{key}.json").write_text(
        json.dumps({"spec": {**spec, "model": "another-model"}, "events": [], "seconds": 0})
    )
    with pytest.raises(ValueError, match="Cached request spec mismatch"):
        asyncio.run(benchmark.infer(None, settings, data, "tile"))
