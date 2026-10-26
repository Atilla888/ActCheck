"""Act (completion certificate) and verification-plan models, owned by agent/ (A).

The act parser fills ActDocument from a photo or PDF. Quantities are copied as written;
arithmetic is checked in code (agent/arithmetic.py), never trusted to the model.
"""

from typing import Literal

from pydantic import BaseModel, Field

WorkType = Literal[
    "tiling_wall",
    "tiling_floor",
    "skirting",
    "painting",
    "plastering",
    "waterproofing",
    "electrical_point",
    "plumbing_fixture",
    "demolition",
    "materials",
    "other",
]
Unit = Literal["m2", "m", "pcs", "lump_sum", "other"]


class ActLine(BaseModel):
    line_no: int
    description_raw: str  # exactly as printed, RU/KZ
    work_type: WorkType
    unit: Unit
    unit_raw: str  # "м2", "м²", "шт", "п.м." ...
    quantity: float | None
    unit_price: float | None
    amount_stated: float | None


class ActDocument(BaseModel):
    doc_kind: Literal["completion_act", "estimate", "invoice", "other"]
    language: Literal["ru", "kk", "mixed", "other"]
    currency: str = "KZT"
    lines: list[ActLine]
    total_stated: float | None = None
    vat_stated: float | None = None
    parser_notes: list[str] = Field(default_factory=list)  # illegible cells, ambiguities


class ArithmeticIssue(BaseModel):
    line_no: int | None  # None = document total
    kind: Literal["line_amount", "document_total", "missing_value"]
    expected: float | None
    stated: float | None
    diff: float | None


class VerificationPlan(BaseModel):
    line_no: int
    verifiable: Literal["camera", "partial", "no"]
    method: Literal["tile_area", "object_count", "none"]
    surfaces: list[Literal["wall", "floor"]] = Field(default_factory=list)
    count_concept: str | None = None  # SAM noun phrase for object_count, e.g. "socket"
    reason: str  # why / why not verifiable, shown to the user
    photos_needed: list[str] = Field(default_factory=list)  # instructions for the capture step
