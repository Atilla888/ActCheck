"""The "try a sample" inspection: the synthetic act from scripts/make_demo.py checked against B's
stored measurement of a synthetic wall (simulated masks, not SAM). Runs the real agent, no model
calls, no cost."""

import json
import math
from functools import cache

from agent.pipeline import inspect
from agent.planner import Lang
from app.server.files import SAMPLE_DIR as DIR
from app.server.files import to_view
from schemas.act import ActDocument
from schemas.measure import RoomMeasurement, WallMeasurement


def _stored_wall() -> WallMeasurement:
    wall = WallMeasurement.model_validate_json((DIR / "wall_1.json").read_text())
    return wall.model_copy(
        update={
            "image_path": str(DIR / wall.overlay_png),
            "overlay_png": str(DIR / wall.overlay_png),
        }
    )


def _room(walls: list[WallMeasurement]) -> RoomMeasurement:
    """Same aggregation as measure.measure_room."""
    counted = [w for w in walls if w.tiled_area_m2 is not None]
    unverified = [w.wall_id for w in walls if w.status != "measured"]
    sigma = math.sqrt(sum(w.sigma_random_m2**2 for w in counted)) + sum(
        w.sigma_system_m2 for w in counted
    )
    return RoomMeasurement(
        walls=walls,
        status="measured" if not unverified else "partial",
        total_tiled_area_m2=round(sum(w.tiled_area_m2 for w in counted), 3),
        sigma_total_m2=round(sigma, 3),
        hidden_area_m2=round(
            sum(r.area_m2 for w in walls for r in w.excluded if r.reason == "not_visible"), 3
        ),
        unverified_walls=unverified,
    )


@cache
def run(lang: Lang) -> dict:
    act = ActDocument.model_validate(json.loads((DIR / "act.json").read_text()))
    wall = _stored_wall()

    def no_counts(path: str, concept: str):
        raise AssertionError("the sample act has no countable lines")

    insp = inspect(
        act,
        [(wall.wall_id, wall.image_path)],
        wall.tile,
        lang=lang,
        measure_room=lambda walls, tile: _room([wall]),
        count_objects=no_counts,
    )
    view = to_view(insp, [DIR / "act.jpg"])
    view["sample"] = True
    return view
