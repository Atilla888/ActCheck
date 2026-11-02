"""Measurement contract between measure/ (B) and agent/ (A). DRAFT — pending Oct 27 agreement.

Conventions (answers to the open questions in schemas/README.md):
- Uncertainty: every sigma is one standard deviation (68%). Consumers decide k;
  the agent flags at k=2.
- Grout: areas are tiled *surface* (tiles + grout joints), which is what acts bill.
- Unavailable vs zero: `status` says whether a number exists. "unavailable" means area
  fields are None, never 0.0. A legitimate zero (wall with no tiles) is status="measured",
  tiled_area_m2=0.0.
- Hidden areas (behind a bathtub, a cabinet): ExcludedRegion(reason="not_visible") with the
  occluder's footprint area. They may or may not be tiled, so the agent treats them as an
  upper-bound allowance, never as measured area.
- Unreadable image: still returns an overlay (the source image with a warning banner) and
  status="unavailable".
- Room totals: sum over measured/partial walls only; unavailable walls are listed in
  `unverified_walls`.
"""

from typing import Literal

from pydantic import BaseModel, Field

MeasureStatus = Literal["measured", "partial", "unavailable"]


class TileSpec(BaseModel):
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    grout_mm: float = Field(default=2.0, ge=0)
    source: Literal["box_label", "act", "user", "tape"]


class ExcludedRegion(BaseModel):
    label: str  # "door", "mirror", "bathtub"
    area_m2: float = Field(ge=0)
    reason: Literal["opening", "not_tiled", "not_visible"]


class MeasureQuality(BaseModel):
    method: Literal["sam_lattice", "sam_masks_only", "fallback_grout"]
    n_confident_tiles: int = Field(ge=0)
    n_merged_suspected: int = Field(ge=0)
    lattice_residual_px: float | None = None
    lens_straightness_px: float | None = None


class WallMeasurement(BaseModel):
    wall_id: str
    image_path: str
    tile: TileSpec
    status: MeasureStatus
    full_tiles: int | None = None
    partial_tiles_equiv: float | None = None
    tiled_area_m2: float | None = None
    sigma_random_m2: float | None = None
    sigma_system_m2: float | None = None
    excluded: list[ExcludedRegion] = Field(default_factory=list)
    overlay_png: str
    quality: MeasureQuality | None = None
    warnings: list[str] = Field(default_factory=list)  # "glossy_merges", "wall_out_of_frame", ...


class RoomMeasurement(BaseModel):
    walls: list[WallMeasurement]
    status: MeasureStatus
    total_tiled_area_m2: float | None = None
    # random parts add in quadrature, systematic (tile-size tolerance) parts add linearly
    sigma_total_m2: float | None = None
    hidden_area_m2: float = Field(default=0.0, ge=0)  # sum of not_visible regions
    unverified_walls: list[str] = Field(default_factory=list)


class ObjectCount(BaseModel):
    concept: str
    count: int = Field(ge=0)
    presence_score: float | None = None
    overlay_png: str
