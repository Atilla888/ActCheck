"""Arithmetic audit of a parsed act: quantity x price vs stated amount, and the document total."""

from schemas.act import ActDocument, ArithmeticIssue

# Acts round to whole tenge; allow rounding of the quantity (2 decimals) times the price.
ABS_TOL = 1.0
REL_TOL = 0.005


def _mismatch(expected: float, stated: float) -> bool:
    return abs(expected - stated) > max(ABS_TOL, REL_TOL * abs(expected))


def audit(doc: ActDocument) -> list[ArithmeticIssue]:
    issues: list[ArithmeticIssue] = []
    line_sum = 0.0
    for line in doc.lines:
        if line.amount_stated is not None:
            line_sum += line.amount_stated
        if line.unit == "lump_sum":
            continue
        values = (line.quantity, line.unit_price, line.amount_stated)
        if all(v is None for v in values):
            continue
        if any(v is None for v in values):
            issues.append(
                ArithmeticIssue(
                    line_no=line.line_no,
                    kind="missing_value",
                    expected=None,
                    stated=line.amount_stated,
                    diff=None,
                )
            )
            continue
        expected = line.quantity * line.unit_price
        if _mismatch(expected, line.amount_stated):
            issues.append(
                ArithmeticIssue(
                    line_no=line.line_no,
                    kind="line_amount",
                    expected=round(expected, 2),
                    stated=line.amount_stated,
                    diff=round(line.amount_stated - expected, 2),
                )
            )

    if doc.total_stated is not None:
        # The total may or may not include VAT; accept either reading.
        candidates = [line_sum]
        if doc.vat_stated is not None:
            candidates.append(line_sum + doc.vat_stated)
        if all(_mismatch(c, doc.total_stated) for c in candidates):
            issues.append(
                ArithmeticIssue(
                    line_no=None,
                    kind="document_total",
                    expected=round(line_sum, 2),
                    stated=doc.total_stated,
                    diff=round(doc.total_stated - line_sum, 2),
                )
            )
    return issues
