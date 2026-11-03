"""HTTP API for the frontend: run an inspection on uploaded files, poll it, fetch the sample.

    uv run uvicorn app.server.main:app --reload   # API on :8000; the Vite dev server proxies /api

Inspections run in a background thread (SAM takes 30–60 s per wall); the client polls
GET /api/inspections/{id}. Jobs live in memory: a restart forgets them. Files are served only from
the job folders and the bundled sample. Model keys stay on the server (.env)."""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from agent.config import get_settings
from agent.pipeline import inspect
from agent.planner import Lang
from app.server import sample
from app.server.files import JOBS_DIR, act_pages, save_upload, to_view

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "app/frontend/dist"
MAX_FILES = 12

Step = Literal["queued", "parsing", "measuring", "counting", "protocol", "done", "failed"]


class Job(BaseModel):
    id: str
    status: Step = "queued"
    result: dict | None = None
    error: str | None = None


app = FastAPI(title="ActCheck", docs_url="/api/docs", openapi_url="/api/openapi.json")
jobs: dict[str, Job] = {}
pool = ThreadPoolExecutor(max_workers=2)


@app.get("/api/health")
def health(probe: bool = False) -> dict:
    """probe=1 also asks the Meta API which models this server can reach (one tiny call)."""
    s = get_settings()
    result = {"ok": True, "model_key": bool(s.meta_api_key or s.baseten_api_key)}
    if probe and s.meta_api_key:
        client = OpenAI(
            base_url=s.meta_api_base_url, api_key=s.meta_api_key.get_secret_value(), timeout=30
        )
        try:
            result["models"] = sorted(m.id for m in client.models.list())
        except Exception as error:
            result["models"] = f"{type(error).__name__}: {str(error)[:200]}"
        try:
            client.chat.completions.create(
                model=s.meta_spark_model, messages=[{"role": "user", "content": "ok"}], max_tokens=3
            )
            result["spark"] = "ok"
        except Exception as error:
            result["spark"] = f"{type(error).__name__}: {str(error)[:200]}"
        try:
            result["egress_ip"] = httpx.get("https://api.ipify.org", timeout=10).text
        except Exception:
            result["egress_ip"] = None
    return result


@app.get("/api/sample")
def get_sample(lang: Lang = "ru") -> dict:
    return sample.run(lang)


def _run(job: Job, folder: Path, pages: list[Path], walls, tile, lang: Lang | None) -> None:
    def step(name: str) -> None:
        job.status = name

    try:
        from measure import count_objects, measure_room

        overlays = folder / "overlays"
        insp = inspect(
            pages,
            walls,
            tile,
            lang=lang,
            measure_room=lambda w, t: measure_room(w, t, output_dir=overlays),
            count_objects=lambda p, c: count_objects(p, c, output_dir=overlays),
            on_step=step,
        )
        job.result = to_view(insp, pages)
        job.status = "done"
    except Exception as err:  # reported to the client; the server keeps running
        log.exception("inspection %s failed", job.id)
        job.error = f"{type(err).__name__}: {err}"
        job.status = "failed"


@app.post("/api/inspections", status_code=202)
async def create_inspection(
    act: Annotated[list[UploadFile], File()],
    walls: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — FastAPI copies defaults
    tile_width_mm: Annotated[float | None, Form(gt=0)] = None,
    tile_height_mm: Annotated[float | None, Form(gt=0)] = None,
    grout_mm: Annotated[float, Form(ge=0)] = 2.0,
    tile_source: Annotated[Literal["box_label", "act", "user", "tape"], Form()] = "user",
    lang: Annotated[Lang | None, Form()] = None,
) -> Job:
    if len(act) + len(walls) > MAX_FILES:
        raise HTTPException(413, f"At most {MAX_FILES} files per inspection")
    job = Job(id=uuid.uuid4().hex)
    folder = JOBS_DIR / job.id
    act_files = [await save_upload(f, folder / "act", i) for i, f in enumerate(act)]
    pages = act_pages(act_files, folder / "act_pages")
    wall_files = [
        (f"wall_{i + 1}", str(await save_upload(f, folder / "walls", i)))
        for i, f in enumerate(walls)
    ]
    tile = None
    if tile_width_mm and tile_height_mm:
        from schemas.measure import TileSpec

        tile = TileSpec(
            width_mm=tile_width_mm, height_mm=tile_height_mm, grout_mm=grout_mm, source=tile_source
        )
    jobs[job.id] = job
    pool.submit(_run, job, folder, pages, wall_files, tile, lang)
    return job


@app.get("/api/inspections/{job_id}")
def get_inspection(job_id: str) -> Job:
    if job_id not in jobs:
        raise HTTPException(404, "Unknown inspection (the server may have restarted)")
    return jobs[job_id]


JOBS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/files/jobs", StaticFiles(directory=JOBS_DIR), name="jobs")
app.mount("/api/files/sample", StaticFiles(directory=sample.DIR), name="sample")
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
