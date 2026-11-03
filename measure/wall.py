"""The measurement contract the agent calls (team plan §5.1): never raises on a bad photo.

A wall is `measured` when the lattice fits and the whole tiled wall is in frame, `partial` when
a number exists but part of the wall is outside the photo, unrecognised or loosely fitted, and
`unavailable` when no honest number exists. Every result has an overlay.
"""

import hashlib
import logging
import math
import os
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from measure import sam_client
from measure.area import AreaResult, measure_area
from measure.lattice import LatticeFit, fit_lattice
from measure.overlay import render_failure, render_objects, render_overlay
from schemas.measure import (
    ExcludedRegion,
    MeasureQuality,
    ObjectCount,
    RoomMeasurement,
    TileSpec,
    WallMeasurement,
)

log = logging.getLogger(__name__)

DEFAULT_EXCLUDE = ("door", "mirror", "window", "bathtub")
BLOCKING = ("floor",)
MAX_RESIDUAL = 0.25  # of the tile size in pixels: no consistent lattice
HIGH_RESIDUAL = 0.08  # loosely fitted: lens distortion, uneven wall or mixed planes
OUT_OF_FRAME = 0.02  # share of the counted outline lying on the photo border
UNDETECTED_SHARE = 0.05  # unrecognised wall area relative to the counted area
ROOM_WORKERS = 4  # walls measured at once; each already sends 6 SAM requests in parallel
BORDER_GAP = 0.5  # tiles: a counted outline this close to the photo edge may continue beyond it
UNCOUNTED_SHARE = 0.2  # of probed ring cells that look like tiles SAM missed
CONFLICT_SHARE = 0.1  # matched tiles under a door/window/mirror mask: the masks are unreliable
PARTIAL_WARNINGS = {
    "wall_out_of_frame",
    "undetected_area",
    "high_residual",
    "exclusion_overlaps_tiles",
    "exclusions_unavailable",  # no hidden-area allowance, and compare.py ignores warnings
    "uncounted_tiles",
}

Segmenter = Callable[[Image.Image, Sequence[str]], sam_client.Segmentation]


@dataclass
class WallAnalysis:
    result: WallMeasurement
    image: Image.Image | None = None
    fit: LatticeFit | None = None
    area: AreaResult | None = None


def measure_wall(
    image_path: str,
    tile: TileSpec,
    wall_id: str,
    exclude_concepts: Sequence[str] | None = None,
    *,
    output_dir: str | Path | None = None,
    segmenter: Segmenter | None = None,
) -> WallMeasurement:
    return analyze_wall(
        image_path, tile, wall_id, exclude_concepts, output_dir=output_dir, segmenter=segmenter
    ).result


def analyze_wall(
    image_path, tile, wall_id, exclude_concepts=None, *, output_dir=None, segmenter=None
) -> WallAnalysis:
    """measure_wall plus the intermediate lattice and area, for overlays and animations."""
    exclusions = tuple(DEFAULT_EXCLUDE if exclude_concepts is None else exclude_concepts)
    # The floor blocks tile-looking floor masks from counting; it is never an exclusion.
    concepts = tuple(dict.fromkeys(exclusions + BLOCKING)) if exclusions else ()
    segment = segmenter or sam_client.segment
    image, data = _load(image_path)
    name = f"{_safe(wall_id)}-{_fingerprint(data, image_path)}.png"
    overlay_path = _output_dir(output_dir) / name

    def unavailable(reasons, image=image):
        path = render_failure(image, wall_id=wall_id, reasons=reasons, out_path=overlay_path)
        return WallAnalysis(
            WallMeasurement(
                wall_id=wall_id,
                image_path=str(image_path),
                tile=tile,
                status="unavailable",
                overlay_png=str(path),
                warnings=reasons,
            ),
            image,
        )

    if image is None:
        return unavailable(["unreadable_image"])
    warnings = []
    try:
        try:
            segmentation = segment(image, concepts)
        except sam_client.SegmentationError:
            if not concepts:
                raise
            segmentation = segment(image, ())
            warnings.append("exclusions_unavailable")
    except sam_client.SegmentationError as error:
        log.warning("%s: segmentation failed: %s", wall_id, error)
        return unavailable(["segmentation_failed"])
    except Exception as error:  # never let one wall crash the agent's room
        return unavailable([f"internal_error:{type(error).__name__}"])
    try:
        fit = fit_lattice(segmentation.tiles, tile)
        if fit is None:
            return unavailable(["too_few_tiles"])
        if fit.residual_px > MAX_RESIDUAL * fit.tile_px:
            return unavailable(["lattice_fit_failed"])
        area = measure_area(
            fit,
            segmentation.tiles,
            segmentation.source_size,
            tile,
            segmentation.concepts,
            image=image,
        )
        if area.tiled_area_m2 <= 0:
            return unavailable(warnings + ["lattice_fit_failed"])
        if fit.n_merged_suspected:
            warnings.append("merged_tiles")
        if area.conflict_tiles > CONFLICT_SHARE * len(fit.tiles):
            warnings.append("exclusion_overlaps_tiles")
        near_edge = area.border_gap_tiles is not None and area.border_gap_tiles < BORDER_GAP
        if area.border_fraction > OUT_OF_FRAME or near_edge:
            warnings.append("wall_out_of_frame")
        if area.uncounted_cells >= max(2, UNCOUNTED_SHARE * area.probed_cells):
            warnings.append("uncounted_tiles")
        if area.undetected_m2 > UNDETECTED_SHARE * area.tiled_area_m2:
            warnings.append("undetected_area")
        if fit.residual_px > HIGH_RESIDUAL * fit.tile_px:
            warnings.append("high_residual")
        status = "partial" if PARTIAL_WARNINGS & set(warnings) else "measured"
        path = render_overlay(
            image,
            fit,
            area,
            wall_id=wall_id,
            status=status,
            warnings=warnings,
            out_path=overlay_path,
            tile=tile,
        )
        result = WallMeasurement(
            wall_id=wall_id,
            image_path=str(image_path),
            tile=tile,
            status=status,
            full_tiles=area.full_tiles,
            partial_tiles_equiv=round(area.partial_tiles_equiv, 2),
            tiled_area_m2=round(area.tiled_area_m2, 3),
            sigma_random_m2=round(area.sigma_random_m2, 3),
            sigma_system_m2=round(area.sigma_system_m2, 3),
            excluded=[
                ExcludedRegion(label=r.label, area_m2=round(r.area_m2, 3), reason=r.reason)
                for r in area.excluded
            ],
            overlay_png=str(path),
            quality=MeasureQuality(
                method="sam_lattice",
                n_confident_tiles=len(fit.tiles),
                n_merged_suspected=fit.n_merged_suspected,
                lattice_residual_px=round(fit.residual_px, 2),
                lens_straightness_px=(
                    None if fit.straightness_px is None else round(fit.straightness_px, 2)
                ),
            ),
            warnings=warnings,
        )
        return WallAnalysis(result, image, fit, area)
    except Exception as error:
        return unavailable(warnings + [f"internal_error:{type(error).__name__}"])


def measure_room(
    walls: list[tuple[str, str]],
    tile: TileSpec,
    *,
    output_dir: str | Path | None = None,
    segmenter: Segmenter | None = None,
) -> RoomMeasurement:
    """Random sigmas add in quadrature, systematic (tile tolerance) ones linearly."""
    # Walls are independent and mostly wait on SAM, so they run side by side; order is kept.
    with ThreadPoolExecutor(max_workers=max(1, min(ROOM_WORKERS, len(walls)))) as pool:
        results = list(
            pool.map(
                lambda wall: measure_wall(
                    wall[1], tile, wall[0], output_dir=output_dir, segmenter=segmenter
                ),
                walls,
            )
        )
    counted = [w for w in results if w.tiled_area_m2 is not None]
    hidden = sum(r.area_m2 for w in results for r in w.excluded if r.reason == "not_visible")
    unverified = [w.wall_id for w in results if w.status != "measured"]
    if not counted:
        return RoomMeasurement(
            walls=results, status="unavailable", hidden_area_m2=0.0, unverified_walls=unverified
        )
    sigma = math.sqrt(sum(w.sigma_random_m2**2 for w in counted)) + sum(
        w.sigma_system_m2 for w in counted
    )
    return RoomMeasurement(
        walls=results,
        status="measured" if not unverified else "partial",
        total_tiled_area_m2=round(sum(w.tiled_area_m2 for w in counted), 3),
        sigma_total_m2=round(sigma, 3),
        hidden_area_m2=round(hidden, 3),
        unverified_walls=unverified,
    )


def count_objects(
    image_path: str,
    concept: str,
    *,
    output_dir: str | Path | None = None,
    segmenter: Segmenter | None = None,
) -> ObjectCount:
    """Instances of one SAM noun phrase on the full frame, e.g. "socket" or "radiator"."""
    segment = segmenter or partial(sam_client.segment, tiles=False)
    image, data = _load(image_path)
    name = f"{_safe(concept)}-{_fingerprint(data, image_path)}.png"
    out_path = _output_dir(output_dir) / "objects" / name
    if image is None:
        path = render_failure(
            None, wall_id=concept, reasons=["unreadable_image"], out_path=out_path
        )
        return ObjectCount(concept=concept, count=0, presence_score=None, overlay_png=str(path))
    found = segment(image, (concept,)).concepts.get(concept, [])
    scores = [d["confidence"] for d in found if d.get("confidence") is not None]
    path = render_objects(image, found, concept=concept, out_path=out_path)
    return ObjectCount(
        concept=concept,
        count=len(found),
        presence_score=round(max(scores), 3) if scores else None,
        overlay_png=str(path),
    )


def _load(image_path):
    path = Path(image_path)
    try:
        data = path.read_bytes()
        with Image.open(path) as original:
            return ImageOps.exif_transpose(original).convert("RGB"), data
    except (OSError, UnidentifiedImageError, ValueError):
        return None, None


def _fingerprint(data, image_path):
    return hashlib.sha256(data if data is not None else str(image_path).encode()).hexdigest()[:8]


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))[:64] or "wall"


def _output_dir(output_dir):
    if output_dir is not None:
        return Path(output_dir)
    base = Path(os.environ.get("ACTCHECK_OUTPUT_DIR", "outputs"))
    return (base if base.is_absolute() else sam_client.ROOT / base) / "measure"
