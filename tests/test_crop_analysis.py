"""Offline checks for source-space wall screening and incomplete-run reporting."""

import asyncio
import csv
import json
import os

import pytest
from PIL import Image

from validation import analyze_crops as analysis
from validation.benchmark_tiles import crops_for, digest, input_image


def rectangle(left, top, right, bottom, *, edge=False):
    return {
        "box": [left, top, right, bottom],
        "contours": [
            {
                "points": [[left, top], [right, top], [right, bottom], [left, bottom]],
                "hole": False,
                "depth": 0,
            }
        ],
        "edge_truncated": edge,
    }


def empty_response_cache(cache, image_bytes):
    spec = {
        "image_sha256": digest(image_bytes),
        "model": "sam-3.1",
        "prompt": "tile",
        "base_url": "https://api.meta.ai/v1",
        "metadata": {"include_confidence": "true", "mask_encoding": "lossless"},
    }
    key = digest(json.dumps(spec, sort_keys=True).encode())
    (cache / f"{key}.json").write_text(
        json.dumps(
            {
                "spec": spec,
                "seconds": 1,
                "events": [
                    {
                        "type": "response.output_text.done",
                        "item_id": "fixture",
                        "output_index": 0,
                        "content_index": 0,
                        "text": "",
                    },
                    {"type": "response.completed", "response": {"output": []}},
                ],
            }
        )
    )
    return key


def test_wall_polygon_and_mirror_exclusion_control_candidate_count():
    region = {
        "status": "planar",
        "include": [[[0, 0], [0.5, 0], [0.5, 1], [0, 1]]],
        "exclude": [[[0.2, 0.1], [0.3, 0.1], [0.3, 0.3], [0.2, 0.3]]],
    }
    detections = [
        rectangle(5, 40, 15, 50),
        rectangle(70, 40, 85, 55),
        rectangle(22, 12, 28, 28),
        rectangle(5, 60, 15, 70, edge=True),
    ]
    screened = analysis.screen(detections, region, (100, 100))
    assert [d["wall_candidate"] for d in screened] == [True, False, False, True]
    assert [d["complete_wall_candidate"] for d in screened] == [True, False, False, False]


def test_curved_or_unknown_region_does_not_establish_planar_wall_candidates():
    for status in ["curved", "uncertain"]:
        region = {"status": status, "include": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
        detection = analysis.screen([rectangle(20, 20, 40, 40)], region, (100, 100))[0]
        assert detection["wall_fraction"] == 1
        assert not detection["wall_candidate"]
        assert not detection["complete_wall_candidate"]


def test_nested_mask_island_is_restored_after_its_parent_hole():
    detection = rectangle(0, 0, 100, 100)
    hole = rectangle(10, 10, 90, 90)["contours"][0]
    hole.update(hole=True, depth=1)
    island = rectangle(30, 30, 70, 70)["contours"][0]
    island.update(depth=2)
    detection["contours"] += [hole, island]
    region = {"status": "planar", "include": [[[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]]]}
    result = analysis.screen([detection], region, (100, 100))[0]
    assert result["wall_fraction"] > 0.3


def test_returned_coordinate_frame_mismatch_is_rejected_before_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "CACHE", tmp_path)
    (tmp_path / "wrong-frame.json").write_text(
        json.dumps(
            {
                "events": [{"type": "response.output_text.done", "text": "<|box;w=800;h=400|>"}],
                "spec": {},
            }
        )
    )
    with pytest.raises(ValueError, match="coordinate frame mismatch"):
        asyncio.run(analysis.parse_cache("wrong-frame", (1600, 800)))


def prepare_analysis(tmp_path, monkeypatch):
    folder = tmp_path / "bathroom_tiles_20"
    (folder / "photos").mkdir(parents=True)
    source = folder / "photos" / "wall.jpg"
    Image.new("RGB", (200, 100), "white").save(source)
    source_hash = digest(source.read_bytes())
    with (folder / "sources.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=["number", "file", "sha256"])
        writer.writeheader()
        writer.writerow({"number": "1", "file": "photos/wall.jpg", "sha256": source_hash})
    out = tmp_path / "outputs/tile_crops"
    (out / "jobs").mkdir(parents=True)
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    monkeypatch.setattr(analysis, "FOLDER", folder)
    monkeypatch.setattr(analysis, "OUT", out)
    monkeypatch.setattr(analysis, "CACHE", cache)
    baseline_folder = tmp_path / "outputs/tile_benchmark"
    baseline_folder.mkdir()
    image, data = input_image(source, max_side=1600)
    full_key = empty_response_cache(cache, data)
    (baseline_folder / "runs.json").write_text(
        json.dumps(
            [
                {
                    "tag": "01_tile_full_max1600",
                    "status": "ok",
                    "file": "photos/wall.jpg",
                    "cache_key": full_key,
                    "image_size": list(image.size),
                    "masks": 0,
                }
            ]
        )
    )
    for index, crop in enumerate(list(crops_for((200, 100)))[:8]):
        image, data = input_image(source, crop, 1600)
        key = empty_response_cache(cache, data)
        (out / "jobs" / f"01_crop{index:02d}.json").write_text(
            json.dumps(
                {
                    "tag": f"01_crop{index:02d}",
                    "status": "ok",
                    "source_sha256": source_hash,
                    "source_size": [200, 100],
                    "crop": list(crop),
                    "input_size": list(image.size),
                    "input_sha256": digest(data),
                    "cache_key": key,
                }
            )
        )
    return out, cache, full_key


def test_missing_crop_keeps_image_incomplete(tmp_path, monkeypatch):
    out, _, _ = prepare_analysis(tmp_path, monkeypatch)
    asyncio.run(analysis.main())
    summaries = json.loads((out / "summary.json").read_text())
    assert summaries[0]["jobs_ok"] == 8
    assert summaries[0]["errors"]
    assert summaries[0]["complete"] is False


def test_full_frame_cache_from_another_model_is_rejected(tmp_path, monkeypatch):
    _, cache, key = prepare_analysis(tmp_path, monkeypatch)
    path = cache / f"{key}.json"
    saved = json.loads(path.read_text())
    saved["spec"]["model"] = "different-model"
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError):
        asyncio.run(analysis.main())


def test_smaller_stale_crop_resolution_is_rejected(tmp_path, monkeypatch):
    out, _, _ = prepare_analysis(tmp_path, monkeypatch)
    path = out / "jobs/01_crop00.json"
    job = json.loads(path.read_text())
    job["input_size"] = [32, 16]
    path.write_text(json.dumps(job))
    with pytest.raises(ValueError):
        asyncio.run(analysis.main())


def complete_analysis_fixture(tmp_path, monkeypatch):
    out, cache, _ = prepare_analysis(tmp_path, monkeypatch)
    source = tmp_path / "bathroom_tiles_20/photos/wall.jpg"
    crop = list(crops_for((200, 100)))[8]
    image, data = input_image(source, crop, 1600)
    key = empty_response_cache(cache, data)
    (out / "jobs/01_crop08.json").write_text(
        json.dumps(
            {
                "tag": "01_crop08",
                "status": "ok",
                "source_sha256": digest(source.read_bytes()),
                "source_size": [200, 100],
                "crop": list(crop),
                "input_size": list(image.size),
                "input_sha256": digest(data),
                "cache_key": key,
            }
        )
    )
    return out


def test_rescreen_reuses_complete_validated_merge_without_parsing(tmp_path, monkeypatch):
    out = complete_analysis_fixture(tmp_path, monkeypatch)
    asyncio.run(analysis.main())

    async def no_parse(*_):
        pytest.fail("A complete validated rescreen should not decode masks again")

    def no_merge(*_):
        pytest.fail("A complete validated rescreen should not merge again")

    monkeypatch.setattr(analysis, "parse_cache", no_parse)
    monkeypatch.setattr(analysis, "merge_detections", no_merge)
    asyncio.run(analysis.main(rescreen_existing=True))
    summary = json.loads((out / "summary.json").read_text())[0]
    assert summary["complete"] is True
    assert summary["eligible"] is False  # Missing wall annotation is never eligible.
    assert summary["reused_merge"] is True


def test_rescreen_rebuilds_mismatched_provenance(tmp_path, monkeypatch):
    out = complete_analysis_fixture(tmp_path, monkeypatch)
    asyncio.run(analysis.main())
    path = out / "01_merged.json"
    existing = json.loads(path.read_text())
    existing["provenance"]["fingerprint"] = "stale-fingerprint"
    path.write_text(json.dumps(existing))
    asyncio.run(analysis.main(rescreen_existing=True))
    summary = json.loads((out / "summary.json").read_text())[0]
    assert summary["complete"] is True and summary["reused_merge"] is False


@pytest.mark.parametrize("changed_file,expected_reuse", [("job", True), ("cache", False)])
def test_legacy_rescreen_tracks_inference_cache_not_resume_metadata(
    tmp_path, monkeypatch, changed_file, expected_reuse
):
    out = complete_analysis_fixture(tmp_path, monkeypatch)
    asyncio.run(analysis.main())
    merged_path = out / "01_merged.json"
    existing = json.loads(merged_path.read_text())
    existing.pop("provenance")
    merged_path.write_text(json.dumps(existing))
    job_path = out / "jobs/01_crop00.json"
    changed_path = job_path
    if changed_file == "cache":
        key = json.loads(job_path.read_text())["cache_key"]
        changed_path = analysis.CACHE / f"{key}.json"
    future = merged_path.stat().st_mtime_ns + 2_000_000_000
    os.utime(changed_path, ns=(future, future))

    asyncio.run(analysis.main(rescreen_existing=True))

    summary = json.loads((out / "summary.json").read_text())[0]
    assert summary["complete"] is True
    assert summary["reused_merge"] is expected_reuse


def test_spawned_workers_write_individual_artifacts_and_ordered_summary(tmp_path, monkeypatch):
    out = complete_analysis_fixture(tmp_path, monkeypatch)
    source_csv = analysis.FOLDER / "sources.csv"
    rows = list(csv.DictReader(source_csv.open()))
    rows.append({**rows[0], "number": "2"})
    with source_csv.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    baseline_path = analysis.ROOT / "outputs/tile_benchmark/runs.json"
    baseline = json.loads(baseline_path.read_text())
    baseline.append({**baseline[0], "tag": "02_tile_full_max1600"})
    baseline_path.write_text(json.dumps(baseline))
    for index in range(9):
        job = json.loads((out / f"jobs/01_crop{index:02d}.json").read_text())
        job["tag"] = f"02_crop{index:02d}"
        (out / f"jobs/02_crop{index:02d}.json").write_text(json.dumps(job))

    asyncio.run(analysis.main(workers=2))

    summaries = json.loads((out / "summary.json").read_text())
    assert [summary["image"] for summary in summaries] == [1, 2]
    assert all(summary["complete"] for summary in summaries)
    for number in [1, 2]:
        assert (out / f"{number:02d}_merged.json").exists()
        assert (out / f"{number:02d}_merged.jpg").exists()
    assert len(list(csv.DictReader((out / "results.csv").open()))) == 2
    assert (out / "report.html").exists()
