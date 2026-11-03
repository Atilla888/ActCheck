"""Decide per act line what the camera can check. Rule-based on purpose: the decision must be
explainable and stable, and work_type/unit already carry it. Reasons are shown to the user in the
protocol language."""

from typing import Literal

from schemas.act import ActDocument, ActLine, VerificationPlan

Lang = Literal["ru", "kk", "en"]

# Stems of the printed description (RU/KZ) -> SAM noun phrase.
COUNT_CONCEPTS = {
    "electrical_point": [
        (("розет",), "socket"),
        (("выключат", "сөндіргіш", "ажыратқыш"), "light switch"),
    ],
    "plumbing_fixture": [
        (("унитаз", "дәретхана"), "toilet"),
        (("раковин", "умывальн", "қолжуғыш"), "sink"),
        (("ванн",), "bathtub"),
        (("полотенцесуш",), "towel rail"),
    ],
}

# Work that the finished surface hides: the contractor is asked for records instead.
HIDDEN_WORK = {"waterproofing", "plastering", "demolition"}
# Grout billed per m2 follows the tiled area; parsed as work_type "other".
GROUT_STEMS = ("затирк", "фуг", "швов", "тігіс")

REASONS: dict[Lang, dict[str, str]] = {
    "en": {
        "grout_floor": "Grout may include the floor, which is not measured yet",
        "tile_area": "Tiled wall area is measured from the photos and the tile size",
        "count": "Installed items ({concept}) are counted on the photos",
        "unit": "Billed in “{unit}”, not m²; the tiled area cannot be compared",
        "mixed": "The line bills several items together ({concepts})",
        "waterproofing": "Hidden under the finish; needs photos taken during the work",
        "plastering": "Covered by the finish; cannot be measured afterwards",
        "demolition": "Removed material is no longer visible",
        "materials": "Materials are checked against receipts, not photos",
        "painting": "Painted area measurement is not supported yet",
        "skirting": "Skirting length measurement is not supported yet",
        "tiling_floor": "Floor area measurement is not supported yet, walls only",
        "other": "No camera check for this kind of work",
    },
    "ru": {
        "grout_floor": "Затирка может включать пол, а пол пока не измеряется",
        "tile_area": "Площадь плитки на стенах измеряется по фото и размеру плитки",
        "count": "Установленные предметы ({concept}) считаются по фото",
        "unit": "Указано в «{unit}», а не в м² — площадь сравнить нельзя",
        "mixed": "В строке несколько разных предметов одной суммой ({concepts})",
        "waterproofing": "Скрыта под отделкой — нужны фото, сделанные во время работ",
        "plastering": "Скрыта под отделкой — после работ не измерить",
        "demolition": "Демонтированного материала уже не видно",
        "materials": "Материалы проверяются по чекам, а не по фото",
        "painting": "Площадь покраски пока не измеряется",
        "skirting": "Длина плинтуса пока не измеряется",
        "tiling_floor": "Площадь пола пока не измеряется, только стены",
        "other": "Эту работу камерой не проверить",
    },
    "kk": {
        "grout_floor": "Тігіс толтыру еденді де қамтуы мүмкін, ал еден әзірге өлшенбейді",
        "tile_area": "Қабырғадағы плитка ауданы суреттер мен плитка өлшемі бойынша өлшенеді",
        "count": "Орнатылған заттар ({concept}) суреттерден саналады",
        "unit": "«{unit}» бірлігімен көрсетілген, м² емес — ауданды салыстыру мүмкін емес",
        "mixed": "Жолда бірнеше түрлі зат бір сомамен көрсетілген ({concepts})",
        "waterproofing": "Әрлеудің астында жасырын — жұмыс кезіндегі суреттер керек",
        "plastering": "Әрлеудің астында жасырын — кейін өлшеу мүмкін емес",
        "demolition": "Бөлшектелген материал енді көрінбейді",
        "materials": "Материалдар суретпен емес, чектермен тексеріледі",
        "painting": "Бояу ауданы әзірге өлшенбейді",
        "skirting": "Плинтус ұзындығы әзірге өлшенбейді",
        "tiling_floor": "Еден ауданы әзірге өлшенбейді, тек қабырғалар",
        "other": "Бұл жұмысты камерамен тексеру мүмкін емес",
    },
}

WALL_PHOTOS = [
    "Each tiled wall straight on, the whole wall plus a margin in the frame, main camera 1x",
    "The tile box label (or a tape measure across one tile) for the tile size",
]


def _count_concepts(line: ActLine) -> list[str]:
    text = line.description_raw.lower()
    return [
        c for stems, c in COUNT_CONCEPTS.get(line.work_type, []) if any(s in text for s in stems)
    ]


def is_grout(line: ActLine) -> bool:
    text = line.description_raw.lower()
    return line.work_type == "other" and any(s in text for s in GROUT_STEMS)


def plan_line(line: ActLine, lang: Lang = "en", has_floor: bool = False) -> VerificationPlan:
    r = REASONS[lang]
    no = line.line_no
    if is_grout(line) and line.unit == "m2":
        if has_floor:
            return VerificationPlan(
                line_no=no, verifiable="no", method="none", reason=r["grout_floor"]
            )
        return VerificationPlan(
            line_no=no,
            verifiable="camera",
            method="tile_area",
            surfaces=["wall"],
            reason=r["tile_area"],
            photos_needed=WALL_PHOTOS,
        )
    if line.work_type == "tiling_wall":
        if line.unit != "m2":
            reason = r["unit"].format(unit=line.unit_raw)
            return VerificationPlan(line_no=no, verifiable="no", method="none", reason=reason)
        return VerificationPlan(
            line_no=no,
            verifiable="camera",
            method="tile_area",
            surfaces=["wall"],
            reason=r["tile_area"],
            photos_needed=WALL_PHOTOS,
        )
    if line.work_type in COUNT_CONCEPTS and line.unit == "pcs":
        concepts = _count_concepts(line)
        if len(concepts) > 1:
            # "розетки и выключатели" bills a sum; counting one concept would invent a shortfall
            reason = r["mixed"].format(concepts=", ".join(concepts))
            return VerificationPlan(line_no=no, verifiable="no", method="none", reason=reason)
        if concepts:
            # Photos may not cover every wall, so a count can confirm but never prove over-billing.
            return VerificationPlan(
                line_no=no,
                verifiable="partial",
                method="object_count",
                count_concept=concepts[0],
                reason=r["count"].format(concept=concepts[0]),
                photos_needed=[f"Every wall with a {concepts[0]} in the frame"],
            )
    reason = r.get(line.work_type, r["other"])
    return VerificationPlan(line_no=no, verifiable="no", method="none", reason=reason)


def plan(doc: ActDocument, lang: Lang = "en") -> list[VerificationPlan]:
    has_floor = any(line.work_type == "tiling_floor" for line in doc.lines)
    return [plan_line(line, lang, has_floor) for line in doc.lines]
