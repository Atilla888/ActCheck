from agent.arithmetic import audit
from agent.compare import compare_tile_line
from schemas.act import ActDocument, ActLine, VerificationPlan
from schemas.measure import ExcludedRegion, RoomMeasurement, TileSpec, WallMeasurement

TILE = TileSpec(width_mm=300, height_mm=600, source="box_label")


def line(no=1, qty=48.5, price=9500.0, amount=460750.0, unit="m2"):
    return ActLine(
        line_no=no,
        description_raw="Облицовка стен плиткой",
        work_type="tiling_wall",
        unit=unit,
        unit_raw="м2",
        quantity=qty,
        unit_price=price,
        amount_stated=amount,
    )


def doc(lines, total=None, vat=None):
    return ActDocument(
        doc_kind="completion_act", language="ru", lines=lines, total_stated=total, vat_stated=vat
    )


def wall(wall_id="w1", area=36.9, status="measured", excluded=()):
    return WallMeasurement(
        wall_id=wall_id,
        image_path=f"{wall_id}.jpg",
        tile=TILE,
        status=status,
        tiled_area_m2=area if status != "unavailable" else None,
        overlay_png=f"{wall_id}_overlay.png",
        excluded=list(excluded),
    )


def room(area=36.9, sigma=0.55, hidden=0.0, unverified=(), status="measured"):
    return RoomMeasurement(
        walls=[wall(area=area)],
        status=status,
        total_tiled_area_m2=area if status != "unavailable" else None,
        sigma_total_m2=sigma,
        hidden_area_m2=hidden,
        unverified_walls=list(unverified),
    )


PLAN = VerificationPlan(
    line_no=1, verifiable="camera", method="tile_area", surfaces=["wall"], reason="tiled walls"
)


# --- arithmetic ---------------------------------------------------------------------------


def test_correct_act_has_no_issues():
    assert audit(doc([line()], total=460750.0)) == []


def test_line_amount_mismatch_is_reported():
    issues = audit(doc([line(amount=470750.0)]))
    assert len(issues) == 1
    assert issues[0].kind == "line_amount"
    assert issues[0].diff == 10000.0


def test_rounding_to_whole_tenge_is_tolerated():
    assert audit(doc([line(qty=12.37, price=9500.0, amount=117515.0)])) == []


def test_total_with_or_without_vat_is_accepted():
    lines = [line(), line(no=2, qty=10, price=1000.0, amount=10000.0, unit="pcs")]
    assert audit(doc(lines, total=470750.0)) == []
    assert audit(doc(lines, total=470750.0 + 56490.0, vat=56490.0)) == []


def test_wrong_total_is_reported():
    issues = audit(doc([line()], total=500000.0))
    assert [i.kind for i in issues] == ["document_total"]


def test_missing_value_is_reported_not_guessed():
    issues = audit(doc([line(price=None)]))
    assert [i.kind for i in issues] == ["missing_value"]


def test_lump_sum_lines_are_not_multiplied():
    assert audit(doc([line(qty=1, price=None, amount=50000.0, unit="lump_sum")])) == []


# --- comparison ---------------------------------------------------------------------------


def test_demo_case_is_over_billed_with_conservative_amount():
    c = compare_tile_line(line(), PLAN, room(area=36.9, sigma=0.55))
    assert c.verdict == "over_billed"
    assert c.measured_high == 38.0
    # (48.5 - 38.0) * 9500 = 99,750: billed against the upper bound, not the estimate
    assert c.overbilling_min == 99750


def test_within_uncertainty_is_consistent():
    assert compare_tile_line(line(qty=37.5), PLAN, room()).verdict == "consistent"


def test_hidden_area_protects_the_contractor():
    # 4 m2 behind a bathtub might be tiled: 48.5 vs 36.9 + 1.1 + 4 is still over, 41 is not
    r = room(hidden=4.0)
    assert compare_tile_line(line(qty=41.0), PLAN, r).verdict == "consistent"
    assert compare_tile_line(line(), PLAN, r).verdict == "over_billed"


def test_unverified_wall_blocks_over_billed():
    c = compare_tile_line(line(), PLAN, room(unverified=["w4"]))
    assert c.verdict == "incomplete"
    assert c.overbilling_min is None


def test_unavailable_room_is_incomplete_not_zero():
    c = compare_tile_line(line(), PLAN, room(status="unavailable", unverified=["w1"]))
    assert c.verdict == "incomplete"
    assert c.measured_qty is None


def test_non_camera_line_is_not_verifiable():
    plan = VerificationPlan(line_no=1, verifiable="no", method="none", reason="hidden work")
    assert compare_tile_line(line(), plan, room()).verdict == "not_verifiable"


def test_excluded_region_model_accepts_hidden_reason():
    w = wall(excluded=[ExcludedRegion(label="bathtub", area_m2=1.2, reason="not_visible")])
    assert w.excluded[0].reason == "not_visible"
