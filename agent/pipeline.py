"""One inspection end to end: act photo(s) + wall photos + tile size -> Protocol.

Steps: parse the act (Spark), audit its arithmetic, plan what the camera can check, call the
measure/ tools only where a plan needs them, compare and write the protocol. Measurement
functions are injectable so tests and the API can run without SAM."""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agent.arithmetic import audit
from agent.planner import Lang, plan
from agent.protocol import build_protocol
from schemas.act import ActDocument, ArithmeticIssue, VerificationPlan
from schemas.compare import Protocol
from schemas.measure import ObjectCount, RoomMeasurement, TileSpec

MeasureRoom = Callable[[list[tuple[str, str]], TileSpec], RoomMeasurement]
CountObjects = Callable[[str, str], ObjectCount]


class Inspection(BaseModel):
    act: ActDocument
    plans: list[VerificationPlan]
    arithmetic_issues: list[ArithmeticIssue]
    room: RoomMeasurement | None
    counts: dict[str, list[ObjectCount]]
    protocol: Protocol


def _measure_tools() -> tuple[MeasureRoom, CountObjects]:
    from measure import count_objects, measure_room  # B's package; heavy imports, load lazily

    return measure_room, count_objects


def language_of(act: ActDocument) -> Lang:
    return "kk" if act.language == "kk" else "ru"


def inspect(
    act: ActDocument | list[str | Path],
    walls: list[tuple[str, str]],
    tile: TileSpec | None,
    *,
    lang: Lang | None = None,
    measure_room: MeasureRoom | None = None,
    count_objects: CountObjects | None = None,
    on_step: Callable[[str], None] = lambda step: None,
) -> Inspection:
    """`act` is a parsed ActDocument or the act's page images. `walls` are (wall_id, photo path).
    Without a tile size or wall photos, tile lines come back `incomplete`, never guessed.
    `on_step` receives "parsing", "measuring", "counting", "protocol" as the work progresses."""
    if not isinstance(act, ActDocument):
        on_step("parsing")
        from agent.act_parser import parse_act

        act = parse_act(act)
    lang = lang or language_of(act)
    plans = plan(act, lang)
    issues = audit(act)

    need_area = any(p.method == "tile_area" for p in plans) and walls and tile is not None
    concepts = list(dict.fromkeys(p.count_concept for p in plans if p.method == "object_count"))
    if (need_area or (concepts and walls)) and (measure_room is None or count_objects is None):
        default_room, default_count = _measure_tools()
        measure_room = measure_room or default_room
        count_objects = count_objects or default_count

    room = None
    if need_area:
        on_step("measuring")
        room = measure_room(walls, tile)
    counts = {}
    if concepts and walls:
        on_step("counting")
        counts = {c: [count_objects(path, c) for _, path in walls] for c in concepts}

    on_step("protocol")
    protocol = build_protocol(act, plans, issues, room, counts, lang)
    return Inspection(
        act=act, plans=plans, arithmetic_issues=issues, room=room, counts=counts, protocol=protocol
    )


def translate(insp: Inspection, lang: Lang) -> Inspection:
    """The same inspection with plans and protocol written in `lang`; no model calls."""
    plans = plan(insp.act, lang)
    protocol = build_protocol(insp.act, plans, insp.arithmetic_issues, insp.room, insp.counts, lang)
    return insp.model_copy(update={"plans": plans, "protocol": protocol})
