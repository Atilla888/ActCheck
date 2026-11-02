"""Line-by-line comparison and protocol, owned by agent/ (A)."""

from typing import Literal

from pydantic import BaseModel, Field

from schemas.act import ArithmeticIssue

Verdict = Literal["consistent", "over_billed", "under_billed", "not_verifiable", "incomplete"]


class LineComparison(BaseModel):
    line_no: int
    description_raw: str
    unit: str
    billed_qty: float | None
    measured_qty: float | None
    measured_low: float | None  # estimate - k*sigma
    measured_high: float | None  # estimate + k*sigma + hidden allowance
    verdict: Verdict
    # conservative: (billed - measured_high) * unit_price; only set for over_billed
    overbilling_min: float | None = None
    evidence: list[str] = Field(default_factory=list)  # overlay paths
    note: str = ""


class Protocol(BaseModel):
    comparisons: list[LineComparison]
    arithmetic_issues: list[ArithmeticIssue]
    verifiable_share: float  # share of the act's amount a camera could check, 0..1
    overbilling_min_total: float
    questions: list[str]  # polite questions to the contractor, user's language
    summary: str
