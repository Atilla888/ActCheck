"""Decide per act line what the camera can check. Rule-based on purpose: the decision must be
explainable and stable, and work_type/unit already carry it. Reasons are shown to the user."""

from schemas.act import ActDocument, ActLine, VerificationPlan

WALL_PHOTOS = [
    "Each tiled wall straight on, the whole wall plus a margin in the frame, main camera 1x",
    "The tile box label (or a tape measure across one tile) for the tile size",
]

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

NOT_VISIBLE = {
    "waterproofing": "Hidden under the finish; ask for photos taken during the work",
    "plastering": "Covered by the finish; the area cannot be measured afterwards",
    "demolition": "Removed material is no longer visible",
    "materials": "Materials are checked against receipts, not photos",
    "painting": "Painted area measurement is not supported yet",
    "skirting": "Skirting length measurement is not supported yet",
    "tiling_floor": "Floor area measurement is not supported yet; wall tiling only",
}


def _count_concepts(line: ActLine) -> list[str]:
    text = line.description_raw.lower()
    return [
        c for stems, c in COUNT_CONCEPTS.get(line.work_type, []) if any(s in text for s in stems)
    ]


def plan_line(line: ActLine) -> VerificationPlan:
    no = line.line_no
    if line.work_type == "tiling_wall":
        if line.unit != "m2":
            return VerificationPlan(
                line_no=no,
                verifiable="no",
                method="none",
                reason=f"Billed in '{line.unit_raw}', not m2; tile area cannot be compared",
            )
        return VerificationPlan(
            line_no=no,
            verifiable="camera",
            method="tile_area",
            surfaces=["wall"],
            reason="Tiled wall area is measured from photos and the tile size",
            photos_needed=WALL_PHOTOS,
        )
    if line.work_type in COUNT_CONCEPTS and line.unit == "pcs":
        concepts = _count_concepts(line)
        if len(concepts) > 1:
            # "розетки и выключатели" bills a sum; counting one concept would invent a shortfall
            return VerificationPlan(
                line_no=no,
                verifiable="no",
                method="none",
                reason=f"The line bills several items together ({', '.join(concepts)})",
            )
        if concepts:
            concept = concepts[0]
            # Photos may not cover every wall, so a count can confirm but never prove over-billing.
            return VerificationPlan(
                line_no=no,
                verifiable="partial",
                method="object_count",
                count_concept=concept,
                reason=f"Installed items ({concept}) are counted on the wall photos",
                photos_needed=[f"Every wall with a {concept} in the frame"],
            )
    reason = NOT_VISIBLE.get(line.work_type, "No camera check for this kind of work")
    return VerificationPlan(line_no=no, verifiable="no", method="none", reason=reason)


def plan(doc: ActDocument) -> list[VerificationPlan]:
    return [plan_line(line) for line in doc.lines]
