"""Assemble the Protocol: per-line comparisons, arithmetic issues, questions to the contractor and a
summary in the user's language. Templates, not a model: every number shown is computed here."""

from typing import Literal

from agent.compare import compare_count_line, compare_tile_line
from schemas.act import ActDocument, ActLine, ArithmeticIssue, VerificationPlan
from schemas.compare import LineComparison, Protocol
from schemas.measure import ObjectCount, RoomMeasurement

Lang = Literal["ru", "kk", "en"]
JOINT = "Compared together:"
NO_ROOM = RoomMeasurement(walls=[], status="unavailable")

TEXT: dict[Lang, dict[str, str]] = {
    "ru": {
        "over_billed": "Строка {n} «{desc}»: в акте {billed} {unit}, а по фото стен выходит не "
        "больше {high} {unit}. Как считали объём — какие стены и проёмы учтены?",
        "count_short": "Строка {n} «{desc}»: в акте {billed} {unit}, на фото видно {counted}. "
        "Где установлены остальные?",
        "line_amount": "Строка {n}: {qty} × {price} = {expected}, а в акте указано {stated}. "
        "Поясните, пожалуйста, разницу.",
        "document_total": "Сумма строк — {expected}, а итог в акте — {stated}. Откуда разница?",
        "missing_value": "Строка {n}: не указано количество, цена или сумма. Можно уточнить?",
        "share": "Камерой проверено {share}% суммы акта.",
        "over_total": "Завышение по фото — не меньше {total} {cur}.",
        "no_over": "Завышения по фото не найдено.",
        "arith": "Арифметических расхождений: {count}.",
        "reshoot": "Нужно переснять стены: {walls}.",
    },
    "kk": {
        "over_billed": "{n}-жол «{desc}»: актіде {billed} {unit}, ал қабырға суреттері бойынша "
        "ең көбі {high} {unit}. Көлем қалай есептелді — қай қабырғалар мен ойықтар ескерілді?",
        "count_short": "{n}-жол «{desc}»: актіде {billed} {unit}, суретте {counted} көрінеді. "
        "Қалғандары қайда орнатылған?",
        "line_amount": "{n}-жол: {qty} × {price} = {expected}, ал актіде {stated} көрсетілген. "
        "Айырмашылықты түсіндіріңізші.",
        "document_total": "Жолдар сомасы — {expected}, ал актідегі қорытынды — {stated}. "
        "Айырмашылық неден?",
        "missing_value": "{n}-жол: саны, бағасы немесе сомасы көрсетілмеген. Нақтылай аласыз ба?",
        "share": "Камерамен акт сомасының {share}% тексерілді.",
        "over_total": "Суреттер бойынша асыра есептеу — кемінде {total} {cur}.",
        "no_over": "Суреттер бойынша асыра есептеу табылған жоқ.",
        "arith": "Арифметикалық сәйкессіздіктер: {count}.",
        "reshoot": "Қабырғаларды қайта түсіру керек: {walls}.",
    },
    "en": {
        "over_billed": 'Line {n} "{desc}": the act bills {billed} {unit}, the wall photos show '
        "at most {high} {unit}. How was the quantity measured — which walls and openings?",
        "count_short": 'Line {n} "{desc}": the act bills {billed} {unit}, the photos show '
        "{counted}. Where are the others installed?",
        "line_amount": "Line {n}: {qty} × {price} = {expected}, but the act states {stated}. "
        "Please explain the difference.",
        "document_total": "The lines add up to {expected}, the act total is {stated}. "
        "Where does the difference come from?",
        "missing_value": "Line {n}: quantity, price or amount is missing. Could you clarify?",
        "share": "The camera checked {share}% of the act amount.",
        "over_total": "Over-billing from the photos: at least {total} {cur}.",
        "no_over": "No over-billing found on the photos.",
        "arith": "Arithmetic discrepancies: {count}.",
        "reshoot": "Walls to reshoot: {walls}.",
    },
}


def _num(x: float | None, lang: Lang, money: bool = False) -> str:
    if x is None:
        return "—"
    s = f"{x:,.0f}" if money else f"{x:,.2f}".rstrip("0").rstrip(".")
    if lang == "en":
        return s
    return s.replace(",", " ").replace(".", ",")


def compare_tile_lines(
    lines: list[ActLine], plans: dict[int, VerificationPlan], room: RoomMeasurement
) -> list[LineComparison]:
    """The photos cover the room, so several wall-tiling lines are compared as one total."""
    if len(lines) == 1:
        return [compare_tile_line(lines[0], plans[lines[0].line_no], room)]
    qtys = [ln.quantity for ln in lines]
    amounts = [ln.amount_stated for ln in lines]
    total_qty = None if None in qtys else sum(qtys)
    price = sum(amounts) / total_qty if total_qty and None not in amounts else None
    combined = lines[0].model_copy(update={"quantity": total_qty, "unit_price": price})
    joint = compare_tile_line(combined, plans[lines[0].line_no], room)
    nos = ", ".join(str(ln.line_no) for ln in lines)
    out = []
    for i, ln in enumerate(lines):
        out.append(
            joint.model_copy(
                update={
                    "line_no": ln.line_no,
                    "description_raw": ln.description_raw,
                    "billed_qty": ln.quantity,
                    # counted once, on the first line of the group
                    "overbilling_min": joint.overbilling_min if i == 0 else None,
                    "note": f"{JOINT} lines {nos}, total {total_qty} m2. {joint.note}",
                }
            )
        )
    return out


def _questions(
    doc: ActDocument,
    plans: dict[int, VerificationPlan],
    comparisons: list[LineComparison],
    issues: list[ArithmeticIssue],
    lang: Lang,
) -> list[str]:
    t = TEXT[lang]
    by_no = {ln.line_no: ln for ln in doc.lines}
    joint = [c for c in comparisons if c.note.startswith(JOINT)]
    qs = []
    for c in comparisons:
        method = plans[c.line_no].method
        fields = dict(
            n=c.line_no,
            desc=c.description_raw,
            unit=c.unit,
            billed=_num(c.billed_qty, lang),
            high=_num(c.measured_high, lang),
            counted=_num(c.measured_qty, lang),
        )
        if c.verdict == "over_billed":
            if c in joint[1:]:
                continue  # one question per group, asked on its first line
            if c in joint:
                fields.update(
                    n=", ".join(str(j.line_no) for j in joint),
                    billed=_num(sum(j.billed_qty or 0.0 for j in joint), lang),
                )
            qs.append(t["over_billed"].format(**fields))
        elif c.verdict == "incomplete" and method == "object_count" and c.measured_qty is not None:
            qs.append(t["count_short"].format(**fields))
    for i in issues:
        line = by_no.get(i.line_no) if i.line_no is not None else None
        qs.append(
            t[i.kind].format(
                n=i.line_no,
                qty=_num(line.quantity if line else None, lang),
                price=_num(line.unit_price if line else None, lang, money=True),
                expected=_num(i.expected, lang, money=True),
                stated=_num(i.stated, lang, money=True),
            )
        )
    return qs


def build_protocol(
    doc: ActDocument,
    plans: list[VerificationPlan],
    issues: list[ArithmeticIssue],
    room: RoomMeasurement | None,
    counts: dict[str, list[ObjectCount]],
    lang: Lang,
) -> Protocol:
    by_no = {p.line_no: p for p in plans}
    tile_lines = [ln for ln in doc.lines if by_no[ln.line_no].method == "tile_area"]
    done: dict[int, LineComparison] = {}
    if tile_lines and room is not None:
        done = {c.line_no: c for c in compare_tile_lines(tile_lines, by_no, room)}

    comparisons = []
    for ln in doc.lines:
        p = by_no[ln.line_no]
        if ln.line_no in done:
            comparisons.append(done[ln.line_no])
        elif p.method == "object_count":
            comparisons.append(compare_count_line(ln, p, counts.get(p.count_concept, [])))
        else:
            # not verifiable, or tile_area without wall photos (-> incomplete)
            comparisons.append(compare_tile_line(ln, p, room or NO_ROOM))

    amounts = {ln.line_no: ln.amount_stated or 0.0 for ln in doc.lines}
    total_amount = sum(amounts.values())
    checked = sum(amounts[p.line_no] for p in plans if p.verifiable != "no")
    share = checked / total_amount if total_amount else 0.0
    over_total = sum(c.overbilling_min or 0.0 for c in comparisons)

    t = TEXT[lang]
    summary = [t["share"].format(share=round(share * 100))]
    summary.append(
        t["over_total"].format(total=_num(over_total, lang, money=True), cur=doc.currency)
        if over_total
        else t["no_over"]
    )
    if issues:
        summary.append(t["arith"].format(count=len(issues)))
    if room is not None and room.unverified_walls:
        summary.append(t["reshoot"].format(walls=", ".join(room.unverified_walls)))

    return Protocol(
        comparisons=comparisons,
        arithmetic_issues=issues,
        verifiable_share=round(share, 3),
        overbilling_min_total=over_total,
        questions=_questions(doc, by_no, comparisons, issues, lang),
        summary=" ".join(summary),
    )
