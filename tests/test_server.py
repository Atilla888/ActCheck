import time

import pytest
from fastapi.testclient import TestClient

from app.server import main
from app.server.files import JOBS_DIR

client = TestClient(main.app)


def test_health():
    assert client.get("/api/health").json()["ok"] is True


@pytest.mark.parametrize("lang", ["ru", "kk", "en"])
def test_sample_runs_the_agent(lang):
    view = client.get("/api/sample", params={"lang": lang}).json()
    lines = {c["line_no"]: c for c in view["protocol"]["comparisons"]}
    tile = lines[3]
    assert tile["verdict"] == "over_billed"
    assert tile["overbilling_min"] > 0
    assert tile["question"] and tile["explanation"]
    assert lines[4]["question"]  # grout line: 6.2 × 800 ≠ 5 960
    assert lines[2]["verdict"] == "not_verifiable"
    assert view["sample"] is True
    overlay = view["room"]["walls"][0]["overlay_png"]
    assert overlay == "/api/files/sample/wall_1_overlay.jpg"
    assert client.get(overlay).status_code == 200
    assert client.get(view["act_pages"][0]).status_code == 200


def test_sample_files_do_not_escape():
    assert client.get("/api/files/sample/../act.json").status_code == 404
    assert client.get("/api/files/sample/%2e%2e/measure_example.json").status_code == 404


def test_rejects_wrong_type():
    r = client.post("/api/inspections", files={"act": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_inspection_job(monkeypatch):
    from app.server import sample

    calls = {}

    def fake_inspect(pages, walls, tile, **kw):
        calls.update(pages=pages, walls=walls, tile=tile)
        kw["on_step"]("parsing")
        return sample_inspection

    sample_inspection = _sample_inspection(sample)
    monkeypatch.setattr(main, "inspect", fake_inspect)
    r = client.post(
        "/api/inspections",
        files=[
            ("act", ("act.jpg", b"\xff\xd8fake", "image/jpeg")),
            ("walls", ("w1.png", b"\x89PNGfake", "image/png")),
        ],
        data={"tile_width_mm": "300", "tile_height_mm": "150"},
    )
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(50):
        job = client.get(f"/api/inspections/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job["error"]
    assert job["result"]["act_pages"] == [f"/api/files/jobs/{job_id}/act/00.jpg"]
    assert calls["walls"] == [("wall_1", str(JOBS_DIR / job_id / "walls/00.png"))]
    assert (calls["tile"].width_mm, calls["tile"].height_mm) == (300, 150)


def test_unknown_job():
    assert client.get("/api/inspections/nope").status_code == 404


def _sample_inspection(sample):
    import json

    from agent.pipeline import inspect
    from schemas.act import ActDocument

    wall = sample._stored_wall()
    act = ActDocument.model_validate(json.loads((sample.DIR / "act.json").read_text()))
    return inspect(
        act,
        [(wall.wall_id, wall.image_path)],
        wall.tile,
        measure_room=lambda w, t: sample._room([wall]),
        count_objects=None,
    )
