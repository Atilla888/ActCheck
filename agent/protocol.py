"""Assemble the Protocol: per-line comparisons with an explanation and a question to the
contractor, arithmetic issues and a summary in the user's language. Templates, not a model: every
number shown is computed here."""

from agent.compare import compare_count_line, compare_tile_line
from agent.planner import HIDDEN_WORK, Lang, is_grout
from schemas.act import ActDocument, ActLine, ArithmeticIssue, VerificationPlan
from schemas.compare import LineComparison, Protocol
from schemas.measure import ObjectCount, RoomMeasurement

NO_ROOM = RoomMeasurement(walls=[], status="unavailable")

TEXT: dict[Lang, dict[str, str]] = {
    "ru": {
        "q_over": "Строка {n} «{desc}»: в акте {billed} {unit}, а по фото стен выходит не "
        "больше {high} {unit}. Как считали объём — какие стены и проёмы учтены?",
        "q_count": "Строка {n} «{desc}»: в акте {billed} {unit}, на фото видно {counted}. "
        "Где установлены остальные?",
        "q_hidden": "Строка {n} «{desc}»: работа скрыта под отделкой. Пришлите, пожалуйста, "
        "фото процесса или акт скрытых работ.",
        "q_demolition": "Строка {n} «{desc}»: пришлите, пожалуйста, фото до начала работ, "
        "чтобы подтвердить объём демонтажа.",
        "q_line_amount": "Строка {n}: {qty} × {price} = {expected}, а в акте указано {stated}. "
        "Поясните, пожалуйста, разницу.",
        "q_document_total": "Сумма строк — {expected}, а итог в акте — {stated}. Откуда разница?",
        "q_missing_value": "Строка {n}: не указано количество, цена или сумма. Можно уточнить?",
        "e_consistent": "В акте {billed} {unit}, по фото {low}–{high} {unit}: совпадает в "
        "пределах погрешности.",
        "e_over": "В акте {billed} {unit}, а по фото не больше {high} {unit}{hidden}. "
        "Разница — не меньше {diff} {unit}.",
        "e_hidden": " (включая {area} м², скрытые ванной, зеркалом и т. п., — там тоже могла "
        "быть плитка)",
        "e_under": "В акте {billed} {unit}, а по фото не меньше {low} {unit}: указано меньше, "
        "чем видно.",
        "e_reshoot": "Не все стены удалось измерить ({walls}). Переснимите их, чтобы сравнить.",
        "e_no_photos": "Нет фото стен или размера плитки — сравнить не с чем.",
        "e_count_ok": "На фото найдено {counted}: совпадает с актом.",
        "e_count_short": "В акте {billed}, на фото найдено {counted}. Возможно, не все стены "
        "попали в кадр.",
        "e_joint": " Строки {nos} сравниваются вместе: всего {total} {unit}.",
        "share": "Камерой проверено {share}% суммы акта.",
        "over_total": "Завышение по фото — не меньше {total} {cur}.",
        "no_over": "Завышения по фото не найдено.",
        "arith": "Арифметических расхождений: {count}.",
        "reshoot": "Нужно переснять стены: {walls}.",
    },
    "kk": {
        "q_over": "{n}-жол «{desc}»: актіде {billed} {unit}, ал қабырға суреттері бойынша "
        "ең көбі {high} {unit}. Көлем қалай есептелді — қай қабырғалар мен ойықтар ескерілді?",
        "q_count": "{n}-жол «{desc}»: актіде {billed} {unit}, суретте {counted} көрінеді. "
        "Қалғандары қайда орнатылған?",
        "q_hidden": "{n}-жол «{desc}»: жұмыс әрлеудің астында жасырын. Жұмыс барысындағы "
        "суреттерді немесе жасырын жұмыстар актісін жіберіңізші.",
        "q_demolition": "{n}-жол «{desc}»: бөлшектеу көлемін растау үшін жұмыс басталғанға "
        "дейінгі суреттерді жіберіңізші.",
        "q_line_amount": "{n}-жол: {qty} × {price} = {expected}, ал актіде {stated} "
        "көрсетілген. Айырмашылықты түсіндіріңізші.",
        "q_document_total": "Жолдар сомасы — {expected}, ал актідегі қорытынды — {stated}. "
        "Айырмашылық неден?",
        "q_missing_value": "{n}-жол: саны, бағасы немесе сомасы көрсетілмеген. Нақтылай аласыз ба?",
        "e_consistent": "Актіде {billed} {unit}, суреттер бойынша {low}–{high} {unit}: "
        "қателік шегінде сәйкес.",
        "e_over": "Актіде {billed} {unit}, ал суреттер бойынша ең көбі {high} {unit}{hidden}. "
        "Айырмашылық — кемінде {diff} {unit}.",
        "e_hidden": " (ваннаның, айнаның т. б. артындағы {area} м² қоса алғанда — онда да "
        "плитка болуы мүмкін)",
        "e_under": "Актіде {billed} {unit}, ал суреттер бойынша кемінде {low} {unit}: "
        "көрінгеннен аз көрсетілген.",
        "e_reshoot": "Барлық қабырға өлшенбеді ({walls}). Салыстыру үшін оларды қайта түсіріңіз.",
        "e_no_photos": "Қабырға суреттері немесе плитка өлшемі жоқ — салыстыратын ештеңе жоқ.",
        "e_count_ok": "Суретте {counted} табылды: актіге сәйкес.",
        "e_count_short": "Актіде {billed}, суретте {counted} табылды. Барлық қабырға кадрға "
        "түспеген болуы мүмкін.",
        "e_joint": " {nos} жолдары бірге салыстырылады: барлығы {total} {unit}.",
        "share": "Камерамен акт сомасының {share}% тексерілді.",
        "over_total": "Суреттер бойынша асыра есептеу — кемінде {total} {cur}.",
        "no_over": "Суреттер бойынша асыра есептеу табылған жоқ.",
        "arith": "Арифметикалық сәйкессіздіктер: {count}.",
        "reshoot": "Қабырғаларды қайта түсіру керек: {walls}.",
    },
    "en": {
        "q_over": "Line {n} “{desc}”: the act bills {billed} {unit}, the wall photos show at "
        "most {high} {unit}. How was the quantity measured — which walls and openings?",
        "q_count": "Line {n} “{desc}”: the act bills {billed} {unit}, the photos show "
        "{counted}. Where are the others installed?",
        "q_hidden": "Line {n} “{desc}”: this work is hidden under the finish. Please share "
        "photos taken during the work or the hidden-works record.",
        "q_demolition": "Line {n} “{desc}”: please share photos taken before the work to "
        "confirm the demolished quantity.",
        "q_line_amount": "Line {n}: {qty} × {price} = {expected}, but the act states {stated}. "
        "Please explain the difference.",
        "q_document_total": "The lines add up to {expected}, the act total is {stated}. "
        "Where does the difference come from?",
        "q_missing_value": "Line {n}: quantity, price or amount is missing. Could you clarify?",
        "e_consistent": "The act bills {billed} {unit}, the photos show {low}–{high} {unit}: "
        "consistent within the uncertainty.",
        "e_over": "The act bills {billed} {unit}, the photos show at most {high} {unit}"
        "{hidden}. The difference is at least {diff} {unit}.",
        "e_hidden": " (including {area} m² hidden by a bathtub, mirror etc. that may also be "
        "tiled)",
        "e_under": "The act bills {billed} {unit}, the photos show at least {low} {unit}: "
        "less than what is visible.",
        "e_reshoot": "Not every wall could be measured ({walls}). Retake them to compare.",
        "e_no_photos": "No wall photos or tile size — nothing to compare with.",
        "e_count_ok": "Found {counted} on the photos: matches the act.",
        "e_count_short": "The act bills {billed}, the photos show {counted}. Some walls may be "
        "out of frame.",
        "e_joint": " Lines {nos} are compared together: {total} {unit} in total.",
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
    return [
        joint.model_copy(
            update={
                "line_no": ln.line_no,
                "description_raw": ln.description_raw,
                "billed_qty": ln.quantity,
                # counted once, on the first line of the group
                "overbilling_min": joint.overbilling_min if i == 0 else None,
                "note": f"Compared together: lines {nos}, total {total_qty} m2. {joint.note}",
            }
        )
        for i, ln in enumerate(lines)
    ]


def _explain(
    c: LineComparison,
    p: VerificationPlan,
    line: ActLine,
    room: RoomMeasurement | None,
    group: list[ActLine],
    lang: Lang,
) -> tuple[str, str]:
    """(explanation for the user, question to the contractor or "")."""
    t = TEXT[lang]
    billed = sum(ln.quantity or 0.0 for ln in group) if len(group) > 1 else c.billed_qty
    f = dict(
        n=", ".join(str(ln.line_no) for ln in group) if group else c.line_no,
        desc=c.description_raw,
        unit=c.unit,
        billed=_num(billed, lang),
        low=_num(c.measured_low, lang),
        high=_num(c.measured_high, lang),
        counted=_num(c.measured_qty, lang),
    )
    joint = ""
    if len(group) > 1:
        joint = t["e_joint"].format(nos=f["n"], total=f["billed"], unit=c.unit)
    first_of_group = not group or group[0].line_no == c.line_no

    if c.verdict == "not_verifiable":
        q = ""
        if line.work_type in HIDDEN_WORK:
            key = "q_demolition" if line.work_type == "demolition" else "q_hidden"
            q = t[key].format(**f)
        return p.reason, q
    if p.method == "object_count":
        if c.measured_qty is None:
            return t["e_no_photos"], ""
        if c.verdict == "consistent":
            return t["e_count_ok"].format(**f), ""
        return t["e_count_short"].format(**f), t["q_count"].format(**f)
    # tile_area
    if c.measured_qty is None:
        if room is not None and room.unverified_walls:
            return t["e_reshoot"].format(walls=", ".join(room.unverified_walls)), ""
        return t["e_no_photos"], ""
    if c.verdict == "consistent":
        return t["e_consistent"].format(**f) + joint, ""
    if c.verdict == "under_billed":
        return t["e_under"].format(**f) + joint, ""
    if c.verdict == "incomplete":  # over the bound, but a wall is unmeasured
        return t["e_reshoot"].format(walls=", ".join(room.unverified_walls)) + joint, ""
    hidden = room.hidden_area_m2 if room else 0.0
    explanation = t["e_over"].format(
        **f,
        diff=_num(billed - c.measured_high, lang),
        hidden=t["e_hidden"].format(area=_num(hidden, lang)) if hidden else "",
    )
    return explanation + joint, t["q_over"].format(**f) if first_of_group else ""


def _issue_question(i: ArithmeticIssue, line: ActLine | None, lang: Lang) -> str:
    return TEXT[lang][f"q_{i.kind}"].format(
        n=i.line_no,
        qty=_num(line.quantity if line else None, lang),
        price=_num(line.unit_price if line else None, lang, money=True),
        expected=_num(i.expected, lang, money=True),
        stated=_num(i.stated, lang, money=True),
    )


def build_protocol(
    doc: ActDocument,
    plans: list[VerificationPlan],
    issues: list[ArithmeticIssue],
    room: RoomMeasurement | None,
    counts: dict[str, list[ObjectCount]],
    lang: Lang,
) -> Protocol:
    by_no = {p.line_no: p for p in plans}
    lines = {ln.line_no: ln for ln in doc.lines}
    area_lines = [ln for ln in doc.lines if by_no[ln.line_no].method == "tile_area"]
    # Wall-tiling lines share the room's area; grout lines are each compared on their own.
    tile_lines = [ln for ln in area_lines if not is_grout(ln)]
    done: dict[int, LineComparison] = {}
    if area_lines and room is not None:
        done = (
            {c.line_no: c for c in compare_tile_lines(tile_lines, by_no, room)}
            if tile_lines
            else {}
        )
        for ln in area_lines:
            if is_grout(ln):
                done[ln.line_no] = compare_tile_line(ln, by_no[ln.line_no], room)
    group = tile_lines if len(tile_lines) > 1 and done else []

    comparisons = []
    for ln in doc.lines:
        p = by_no[ln.line_no]
        if ln.line_no in done:
            c = done[ln.line_no]
        elif p.method == "object_count":
            c = compare_count_line(ln, p, counts.get(p.count_concept, []))
        else:
            # not verifiable, or tile_area without wall photos (-> incomplete)
            c = compare_tile_line(ln, p, room or NO_ROOM)
        explanation, question = _explain(c, p, ln, room, group if ln in group else [], lang)
        line_issues = [i for i in issues if i.line_no == ln.line_no]
        question = " ".join(
            [q for q in [question] if q] + [_issue_question(i, ln, lang) for i in line_issues]
        )
        comparisons.append(c.model_copy(update={"explanation": explanation, "question": question}))

    questions = [c.question for c in comparisons if c.question]
    questions += [_issue_question(i, None, lang) for i in issues if i.line_no is None]

    amounts = {no: ln.amount_stated or 0.0 for no, ln in lines.items()}
    total_amount = sum(amounts.values())
    # what was actually compared with a measurement, not what could have been
    checked = sum(amounts[c.line_no] for c in comparisons if c.measured_qty is not None)
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
        questions=questions,
        summary=" ".join(summary),
    )
