"""Uploads on disk, PDF pages as images, and server paths -> URLs in API responses."""

from pathlib import Path

import pypdfium2
from fastapi import HTTPException, UploadFile

from agent.config import get_settings
from agent.pipeline import Inspection

ROOT = Path(__file__).resolve().parents[2]
_out = Path(get_settings().actcheck_output_dir)
JOBS_DIR = (_out if _out.is_absolute() else ROOT / _out) / "api" / "jobs"
SAMPLE_DIR = ROOT / "data/samples/demo"

MAX_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 6
TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MOUNTS = {JOBS_DIR: "/api/files/jobs", SAMPLE_DIR: "/api/files/sample"}


async def save_upload(upload: UploadFile, folder: Path, index: int) -> Path:
    ext = TYPES.get(upload.content_type or "")
    if ext is None:
        raise HTTPException(415, f"{upload.filename}: use JPG, PNG, WebP or PDF")
    data = await upload.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, f"{upload.filename}: choose a nonempty file under 20 MB")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{index:02d}{ext}"
    path.write_bytes(data)
    return path


def act_pages(files: list[Path], folder: Path) -> list[Path]:
    """Images pass through; PDF pages are rendered to JPEG for the vision model."""
    pages: list[Path] = []
    for f in files:
        if f.suffix != ".pdf":
            pages.append(f)
            continue
        try:
            pdf = pypdfium2.PdfDocument(f)
        except pypdfium2.PdfiumError as err:
            raise HTTPException(422, f"{f.name}: the PDF cannot be read") from err
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(min(len(pdf), MAX_PDF_PAGES)):
            out = folder / f"{f.stem}_p{i + 1}.jpg"
            pdf[i].render(scale=2).to_pil().convert("RGB").save(out, quality=88)
            pages.append(out)
        pdf.close()
    return pages


def url(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path).resolve()
    for base, prefix in MOUNTS.items():
        if p.is_relative_to(base.resolve()):
            return f"{prefix}/{p.relative_to(base.resolve()).as_posix()}"
    return None


def to_view(insp: Inspection, pages: list[Path]) -> dict:
    """Inspection as JSON with every server path replaced by a URL the browser can load."""
    view = insp.model_dump(mode="json")
    for c in view["protocol"]["comparisons"]:
        c["evidence"] = [u for u in map(url, c["evidence"]) if u]
    if view["room"]:
        for w in view["room"]["walls"]:
            w["overlay_png"] = url(w["overlay_png"])
            w["image_path"] = url(w["image_path"])
    for items in view["counts"].values():
        for c in items:
            c["overlay_png"] = url(c["overlay_png"])
    view["act_pages"] = [url(p) for p in pages]
    return view
