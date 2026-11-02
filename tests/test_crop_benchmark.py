"""Offline request-accounting checks; never open an API connection."""

import asyncio
import csv
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError
from PIL import Image
from pydantic import SecretStr

from validation import crop_benchmark as runner


def setup_run(tmp_path, monkeypatch, infer, base_url="https://api.meta.ai/v1"):
    folder = tmp_path / "bathroom_tiles_20"
    (folder / "photos").mkdir(parents=True)
    path = folder / "photos" / "wall.jpg"
    Image.new("RGB", (120, 90), "white").save(path)
    with (folder / "sources.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=["number", "file", "sha256"])
        writer.writeheader()
        writer.writerow(
            {"number": "1", "file": "photos/wall.jpg", "sha256": runner.digest(path.read_bytes())}
        )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "OUT", tmp_path / "out")
    monkeypatch.setattr(sys, "argv", ["crop_benchmark", "--images", "1", "--concurrency", "1"])
    monkeypatch.setattr(
        runner,
        "Settings",
        lambda: SimpleNamespace(
            meta_api_base_url=base_url,
            meta_sam_model="sam-3.1",
            meta_api_key=SecretStr("offline-test-key"),
        ),
    )

    class LocalClient:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["base_url"] == "https://api.meta.ai/v1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(runner, "AsyncOpenAI", LocalClient)
    monkeypatch.setattr(runner, "infer", infer)
    monkeypatch.setattr(runner, "summarize", lambda *_: [])
    return tmp_path / "out"


def read_jobs(output):
    return [json.loads(path.read_text()) for path in sorted((output / "jobs").glob("*.json"))]


def test_successful_zero_matches_are_nine_complete_jobs(tmp_path, monkeypatch):
    calls = []

    async def infer(client, settings, data, prompt):
        calls.append((data, prompt))
        return SimpleNamespace(records=[]), 1.2, True, "fake-cache-key"

    output = setup_run(tmp_path, monkeypatch, infer)
    asyncio.run(runner.main())
    jobs = read_jobs(output)
    assert len(calls) == len(jobs) == 9
    assert all(job["status"] == "ok" and job["masks"] == 0 for job in jobs)
    assert all(job["cached"] and job["prompt"] == "tile" for job in jobs)
    assert len({tuple(job["crop"]) for job in jobs}) == 9
    assert all(job["source_size"] == [120, 90] for job in jobs)
    assert all("offline-test-key" not in json.dumps(job) for job in jobs)
    manifest = json.loads((output / "manifest.json").read_text())
    summary = json.loads((output / "batch_summary.json").read_text())
    assert summary["status"] == "complete" and summary["successful"] == 9
    assert all(
        runner.job_matches_manifest(record, expected, manifest)
        for record, expected in zip(jobs, manifest["jobs"], strict=True)
    )
    assert manifest["config"]["model"] == "sam-3.1"
    assert manifest["config"]["max_side"] == 1600
    assert "offline-test-key" not in json.dumps(manifest)


def test_authentication_failure_stops_remaining_queue(tmp_path, monkeypatch):
    calls = []

    async def infer(*_):
        calls.append(1)
        response = httpx.Response(
            401, request=httpx.Request("POST", "https://api.meta.ai/v1/responses")
        )
        raise AuthenticationError("authentication rejected", response=response, body={})

    output = setup_run(tmp_path, monkeypatch, infer)
    with pytest.raises(SystemExit, match="Stopped new jobs"):
        asyncio.run(runner.main())
    jobs = read_jobs(output)
    assert len(calls) == len(jobs) == 1
    assert jobs[0]["status"] == "http_error" and jobs[0]["http_status"] == 401
    assert "masks" not in jobs[0]
    assert "candidates" not in jobs[0]


def test_timeout_is_not_reported_as_zero_detections(tmp_path, monkeypatch):
    async def infer(*_):
        raise TimeoutError("network timeout")

    output = setup_run(tmp_path, monkeypatch, infer)
    with pytest.raises(SystemExit, match="Incomplete crop run"):
        asyncio.run(runner.main())
    jobs = read_jobs(output)
    assert len(jobs) == 9
    assert all(job["status"] == "error" and job["error_type"] == "TimeoutError" for job in jobs)
    assert all("masks" not in job and "candidates" not in job for job in jobs)
    summary = json.loads((output / "batch_summary.json").read_text())
    assert summary["successful"] == 0 and len(summary["failed"]) == 9


def test_unapproved_host_is_rejected_before_client_construction(tmp_path, monkeypatch):
    async def infer(*_):
        pytest.fail("No inference allowed for an unexpected host")

    setup_run(tmp_path, monkeypatch, infer, base_url="https://example.org/v1")
    with pytest.raises(SystemExit, match="Unexpected API host"):
        asyncio.run(runner.main())
    assert not (tmp_path / "out").exists()


def test_stale_successes_do_not_complete_a_failed_rerun(tmp_path, monkeypatch):
    async def successful(*_):
        return SimpleNamespace(records=[]), 1.2, True, "fake-cache-key"

    output = setup_run(tmp_path, monkeypatch, successful)
    asyncio.run(runner.main())
    previous_run = json.loads((output / "manifest.json").read_text())["run_id"]

    async def authentication_failure(*_):
        response = httpx.Response(
            401, request=httpx.Request("POST", "https://api.meta.ai/v1/responses")
        )
        raise AuthenticationError("authentication rejected", response=response, body={})

    monkeypatch.setattr(runner, "infer", authentication_failure)
    with pytest.raises(SystemExit, match="Stopped new jobs"):
        asyncio.run(runner.main())
    manifest = json.loads((output / "manifest.json").read_text())
    summary = json.loads((output / "batch_summary.json").read_text())
    assert manifest["run_id"] != previous_run
    assert summary["completed"] == 1 and summary["successful"] == 0
    assert len(summary["missing"]) == 8
    jobs = read_jobs(output)
    assert len(jobs) == 9  # Eight older files remain, but must not count for this run.
    assert not runner.job_matches_manifest(jobs[1], manifest["jobs"][1], manifest)


def test_config_fingerprint_changes_with_model_or_resolution_not_secret():
    settings = SimpleNamespace(
        meta_api_base_url="https://api.meta.ai/v1",
        meta_sam_model="sam-3.1",
        meta_api_key=SecretStr("unused"),
    )
    original = runner.experiment_config(settings, 1600)
    assert original != runner.experiment_config(settings, 800)
    settings.meta_api_key = SecretStr("different-unused")
    assert original == runner.experiment_config(settings, 1600)
    settings.meta_sam_model = "different-model"
    assert original != runner.experiment_config(settings, 1600)


def resume_fixture(tmp_path, monkeypatch):
    cache_folder = tmp_path / "cache"
    cache_folder.mkdir()
    monkeypatch.setattr(runner, "CACHE", cache_folder)
    settings = SimpleNamespace(meta_api_base_url="https://api.meta.ai/v1", meta_sam_model="sam-3.1")
    config = runner.experiment_config(settings, 1600)
    fingerprint = runner.digest(json.dumps(config, sort_keys=True).encode())
    expected = {
        "tag": "01_crop00",
        "file": "photos/wall.jpg",
        "source_sha256": "source-hash",
        "source_size": [4000, 3000],
        "crop": [0, 0, 1400, 1100],
        "input_size": [1400, 1100],
        "prompt": "tile",
        "input_sha256": "input-hash",
        "model": "sam-3.1",
        "max_side": 1600,
        "config_fingerprint": fingerprint,
    }
    spec = {
        "image_sha256": expected["input_sha256"],
        "model": "sam-3.1",
        "base_url": "https://api.meta.ai/v1",
        "prompt": "tile",
        "metadata": config["metadata"],
    }
    key = runner.digest(json.dumps(spec, sort_keys=True).encode())
    cache_path = cache_folder / f"{key}.json"
    cache_path.write_text(
        json.dumps(
            {
                "spec": spec,
                "events": [{"type": "response.completed"}],
            }
        )
    )
    previous = {
        **expected,
        "status": "ok",
        "masks": 50,
        "candidates": 45,
        "seconds": 2.3,
        "cache_key": key,
        "run_id": "previous-run",
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(previous))
    overlay = tmp_path / "overlay.jpg"
    Image.new("RGB", (20, 20), "white").save(overlay)
    return path, expected, config, overlay, cache_path


def test_fast_resume_reuses_validated_counts_without_client(tmp_path, monkeypatch):
    path, expected, config, overlay, _ = resume_fixture(tmp_path, monkeypatch)
    result = runner.resume_completed_job(path, expected, config, overlay)
    assert result["resumed"] is True and result["cached"] is True
    assert result["masks"] == 50 and result["candidates"] == 45
    assert "run_id" not in result  # Current invocation supplies its own identity.


@pytest.mark.parametrize("change", ["model", "source", "resolution", "cache_spec", "incomplete"])
def test_fast_resume_rejects_mismatched_or_incomplete_artifacts(tmp_path, monkeypatch, change):
    path, expected, config, overlay, cache_path = resume_fixture(tmp_path, monkeypatch)
    previous = json.loads(path.read_text())
    cache = json.loads(cache_path.read_text())
    if change == "model":
        previous["model"] = "wrong-model"
    elif change == "source":
        previous["source_sha256"] = "changed-source"
    elif change == "resolution":
        previous["input_size"] = [800, 629]
    elif change == "cache_spec":
        cache["spec"]["prompt"] = "wrong-prompt"
    elif change == "incomplete":
        cache["events"] = []
    path.write_text(json.dumps(previous))
    cache_path.write_text(json.dumps(cache))
    assert runner.resume_completed_job(path, expected, config, overlay) is None
