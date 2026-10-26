"""Compare billed quantities with measured ones. Conservative by design: a line is only flagged
over_billed when the bill exceeds the upper end of the measured interval, hidden areas included."""

from schemas.act import ActLine, VerificationPlan
from schemas.compare import LineComparison
from schemas.measure import RoomMeasurement

K_SIGMA = 2.0


def compare_tile_line(
    line: ActLine, plan: VerificationPlan, room: RoomMeasurement
) -> LineComparison:
    base = dict(
        line_no=line.line_no,
        description_raw=line.description_raw,
        unit=line.unit_raw,
        billed_qty=line.quantity,
    )
    if plan.verifiable == "no" or plan.method != "tile_area":
        return LineComparison(
            **base,
            measured_qty=None,
            measured_low=None,
            measured_high=None,
            verdict="not_verifiable",
            note=plan.reason,
        )
    if room.status == "unavailable" or room.total_tiled_area_m2 is None:
        return LineComparison(
            **base,
            measured_qty=None,
            measured_low=None,
            measured_high=None,
            verdict="incomplete",
            note="No usable wall photos; reshoot: " + ", ".join(room.unverified_walls),
        )

    est = room.total_tiled_area_m2
    spread = K_SIGMA * (room.sigma_total_m2 or 0.0)
    low = max(0.0, est - spread)
    high = est + spread + room.hidden_area_m2
    evidence = [w.overlay_png for w in room.walls]

    if line.quantity is None:
        verdict, overbilling = "incomplete", None
    elif line.quantity > high:
        verdict = "over_billed"
        overbilling = (line.quantity - high) * line.unit_price if line.unit_price else None
    elif line.quantity < low:
        verdict, overbilling = "under_billed", None
    else:
        verdict, overbilling = "consistent", None

    # Unmeasured walls make over_billed unsafe: the missing wall may hold the area.
    if verdict == "over_billed" and room.unverified_walls:
        verdict = "incomplete"
        overbilling = None

    return LineComparison(
        **base,
        measured_qty=round(est, 2),
        measured_low=round(low, 2),
        measured_high=round(high, 2),
        verdict=verdict,
        overbilling_min=round(overbilling, 0) if overbilling is not None else None,
        evidence=evidence,
        note=", ".join(room.unverified_walls) if room.unverified_walls else "",
    )
