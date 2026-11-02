import json
from pathlib import Path

import pytest

from agent.pipeline import inspect
from agent.planner import plan
from schemas.act import ActDocument, ActLine
from schemas.measure import ObjectCount, RoomMeasurement, TileSpec, WallMeasurement

ACTS = Path(__file__).parent.parent / "data/samples/synthetic_acts"
TILE = TileSpec(width_mm=300, height_mm=600, source="box_label")
WALLS = [("wall_1", "w1.jpg"), ("wall_2", "w2.jpg")]


def load(name) -> ActDocument:
    return ActDocument.model_validate(json.loads((ACTS / f"{name}.json").read_text()))


def fake_room(area=36.9, sigma=0.55, hidden=0.0, unverified=()):
    def measure_room(walls, tile):
        status = "partial" if unverified else "measured"
        return RoomMeasurement(
            walls=[
                WallMeasurement(
                    wall_id=w,
                    image_path=p,
                    tile=tile,
                    status=status if w in unverified else "measured",
                    tiled_area_m2=area / len(walls),
                    overlay_png=f"{w}.png",
                )
                for w, p in walls
            ],
            status=status,
            total_tiled_area_m2=area,
            sigma_total_m2=sigma,
            hidden_area_m2=hidden,
            unverified_walls=list(unverified),
        )

    return measure_room


def fake_count(per_photo):
    def count_objects(path, concept):
        return ObjectCount(concept=concept, count=per_photo.get(concept, 0), overlay_png="o.png")

    return count_objects


def no_tools(*args):
    raise AssertionError("measurement must not be called")


def by_line(insp):
    return {c.line_no: c for c in insp.protocol.comparisons}


def test_planner_free_form():
    plans = {p.line_no: p for p in plan(load("free_form_error"))}
    assert plans[1].verifiable == "no"  # plastering, hidden
    assert (plans[2].method, plans[2].surfaces) == ("tile_area", ["wall"])
    assert plans[4].verifiable == "no"  # sockets and switches billed together
    assert (plans[5].method, plans[5].count_concept) == ("object_count", "toilet")


def test_grout_not_compared_when_act_has_floor():
    act = load("free_form_error")
    floor = act.lines[1].model_copy(
        update={"line_no": 9, "work_type": "tiling_floor", "description_raw": "Пол"}
    )
    act = act.model_copy(update={"lines": [*act.lines, floor]})
    plans = {p.line_no: p for p in plan(act)}
    assert plans[3].verifiable == "no"  # Затирка швов may include the floor
    assert plans[2].method == "tile_area"


def test_planner_kazakh_sink():
    plans = {p.line_no: p for p in plan(load("kazakh"))}
    assert plans[2].method == "tile_area"
    assert plans[3].verifiable == "no"  # floor not supported
    assert plans[5].count_concept == "sink"


def test_over_billed_end_to_end():
    act = load("free_form_error")
    insp = inspect(
        act, WALLS, TILE, measure_room=fake_room(), count_objects=fake_count({"toilet": 1})
    )
    c = by_line(insp)
    tile = c[2]
    assert tile.verdict == "over_billed"
    assert tile.measured_high == pytest.approx(38.0)
    price = next(ln.unit_price for ln in act.lines if ln.line_no == 2)
    assert tile.overbilling_min == round((48.5 - 38.0) * price)
    assert c[5].verdict == "consistent"  # one toilet on the photos (two photos, counted once each)
    assert c[1].verdict == "not_verifiable"
    p = insp.protocol
    assert c[3].verdict == "over_billed"  # grout follows the tiled area
    assert c[3].overbilling_min == round((48.5 - 38.0) * 800)
    assert p.overbilling_min_total == tile.overbilling_min + c[3].overbilling_min
    assert insp.arithmetic_issues  # planted error in this act
    assert any("48,5" in q and "38" in q for q in p.questions)
    # tiling, grout, the planted arithmetic error, and records for the hidden plastering
    assert len(p.questions) == 4
    assert "акт скрытых работ" in c[1].question
    assert "21" in c[4].question and "24" in c[4].question
    assert "9,5" in tile.explanation or "10,5" in tile.explanation
    assert "Завышение" in p.summary


def test_no_wall_photos_is_incomplete_and_skips_measurement():
    insp = inspect(load("r1_official"), [], TILE, measure_room=no_tools, count_objects=no_tools)
    c = by_line(insp)
    assert c[3].verdict == "incomplete"
    assert c[6].verdict == "not_verifiable"  # смеситель: no count concept
    assert insp.room is None
    assert insp.protocol.overbilling_min_total == 0
    assert insp.protocol.verifiable_share == 0  # nothing was measured


def test_no_tile_size_skips_area():
    insp = inspect(load("r1_official"), WALLS, None, measure_room=no_tools, count_objects=no_tools)
    assert by_line(insp)[3].verdict == "incomplete"


def test_unverified_wall_never_over_billed():
    insp = inspect(
        load("free_form_error"),
        WALLS,
        TILE,
        measure_room=fake_room(unverified=("wall_2",)),
        count_objects=fake_count({"toilet": 1}),
    )
    assert by_line(insp)[2].verdict == "incomplete"
    assert insp.protocol.overbilling_min_total == 0
    assert "wall_2" in insp.protocol.summary


def line(no, qty, price, desc="Облицовка стен плиткой"):
    return ActLine(
        line_no=no,
        description_raw=desc,
        work_type="tiling_wall",
        unit="m2",
        unit_raw="м2",
        quantity=qty,
        unit_price=price,
        amount_stated=qty * price,
    )


def test_two_tile_lines_compared_as_one_total():
    act = ActDocument(
        doc_kind="completion_act",
        language="ru",
        lines=[line(1, 20.0, 9000.0, "Облицовка стен, санузел"), line(2, 28.5, 10000.0)],
    )
    insp = inspect(act, WALLS, TILE, measure_room=fake_room(), count_objects=no_tools)
    c = by_line(insp)
    assert c[1].verdict == c[2].verdict == "over_billed"
    avg = (20 * 9000 + 28.5 * 10000) / 48.5
    assert c[1].overbilling_min == round((48.5 - 38.0) * avg)
    assert c[2].overbilling_min is None
    assert len(insp.protocol.questions) == 1
    assert "1, 2" in insp.protocol.questions[0] and "48,5" in insp.protocol.questions[0]


def test_count_shortfall_asks_contractor():
    act = ActDocument(
        doc_kind="completion_act",
        language="ru",
        lines=[
            ActLine(
                line_no=1,
                description_raw="Установка розеток",
                work_type="electrical_point",
                unit="pcs",
                unit_raw="шт",
                quantity=6,
                unit_price=3000.0,
                amount_stated=18000.0,
            )
        ],
    )
    insp = inspect(act, WALLS, TILE, measure_room=no_tools, count_objects=fake_count({"socket": 2}))
    c = by_line(insp)[1]
    assert (c.verdict, c.measured_qty) == ("incomplete", 4.0)
    assert insp.protocol.questions == [
        "Строка 1 «Установка розеток»: в акте 6 шт, на фото видно 4. Где установлены остальные?"
    ]
    assert insp.protocol.verifiable_share == 1.0


def test_kazakh_protocol_language():
    insp = inspect(
        load("kazakh"), WALLS, TILE, measure_room=fake_room(27.0), count_objects=fake_count({})
    )
    assert "тексерілді" in insp.protocol.summary
    assert by_line(insp)[2].verdict == "consistent"
