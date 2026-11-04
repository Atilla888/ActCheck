# ruff: noqa: E501 — document text reads better unwrapped
"""Four end-to-end test cases for the app's "Test files": a contractor act, a wall photo with
exact geometry, a printable report and the measurement data (what to type in, the true answer,
and what ActCheck returned).

All files are synthetic and labelled so. Walls are rendered by validation.synthetic, so the true
tiled area is exact. Output: app/frontend/public/test-data/cases/<case>/{act.jpg, wall.png,
measurement.json, report.html}; the report embeds its images, so it works on its own. With --measure, each wall is also measured through SAM 3.1 (cached afterwards,
about $0.04 per new wall) and the act's tiling line is compared with agent/compare.py's rule.

Usage: uv run python scripts/make_test_cases.py [--measure]
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_synthetic_acts import draw_table, fmt_money, fmt_qty, font, line, page, stamp  # noqa: E402

from validation.synthetic import SyntheticWall, render_wall  # noqa: E402

OUT = Path("app/frontend/public/test-data/cases")

RU_HEADER = ["№", "Наименование работ", "Ед. изм.", "Кол-во", "Цена, тг", "Сумма, тг"]
KK_HEADER = [
    "Р/с\n№",
    "Жұмыстардың атауы",
    "Өлшем\nбірлігі",
    "Саны",
    "Бағасы,\nтеңге",
    "Құны,\nтеңге",
]

CASES = [
    {
        "id": "01_honest_bill",
        "title": "Honest bill",
        "story": "The contractor bills the wall tiling correctly. ActCheck should find no over-billing.",
        "wall": SyntheticWall(
            wall_w_mm=2400, wall_h_mm=2100, tile_w_mm=300, tile_h_mm=600, yaw_deg=6, seed=301
        ),
        "language": "ru",
        "act_no": 7,
        "address": "облицовка стены в санузле",
        "lines": lambda true: [
            line(1, "Демонтаж старой плитки", "demolition", "m2", "м²", 5.0, 1500),
            line(
                2,
                "Облицовка стены плиткой 300×600",
                "tiling_wall",
                "m2",
                "м²",
                round(true, 1),
                9500,
            ),
            line(3, "Затирка швов", "other", "m2", "м²", round(true, 1), 800),
            line(4, "Грунтовка стен", "other", "m2", "м²", 5.0, 600),
        ],
        "expected": "consistent",
    },
    {
        "id": "02_overbilled_wall",
        "title": "Over-billed wall tiling",
        "story": "The act bills about 30 % more wall tiling than exists, and the grout line's amount does not match quantity × price.",
        "wall": SyntheticWall(
            wall_w_mm=2700,
            wall_h_mm=2400,
            tile_w_mm=300,
            tile_h_mm=300,
            yaw_deg=-8,
            pitch_deg=3,
            seed=302,
        ),
        "language": "ru",
        "act_no": 12,
        "address": "облицовка стены на кухне",
        "lines": lambda true: [
            line(1, "Демонтаж старой облицовки", "demolition", "m2", "м²", 6.5, 1200),
            line(2, "Облицовка стены плиткой 300×300", "tiling_wall", "m2", "м²", 8.5, 9000),
            line(3, "Затирка швов", "other", "m2", "м²", 8.5, 800, amount=7600),
            line(4, "Установка розетки", "electrical_point", "pcs", "шт", 2, 3500),
        ],
        "expected": "over_billed",
    },
    {
        "id": "03_door_not_deducted",
        "title": "Door not deducted",
        "story": "The wall has a 0.8 × 2.0 m doorway. The act bills the whole wall as if the door were tiled.",
        "wall": SyntheticWall(
            wall_w_mm=3200,
            wall_h_mm=2500,
            tile_w_mm=200,
            tile_h_mm=200,
            door=(1300, 500, 800, 2000),
            yaw_deg=5,
            seed=303,
        ),
        "language": "ru",
        "act_no": 4,
        "address": "облицовка стены коридора",
        "lines": lambda true: [
            line(1, "Облицовка стены плиткой 200×200", "tiling_wall", "m2", "м²", 8.0, 9800),
            line(2, "Затирка швов", "other", "m2", "м²", 8.0, 800),
            line(3, "Установка порога", "other", "pcs", "шт", 1, 7000),
        ],
        "expected": "over_billed",
    },
    {
        "id": "04_kazakh_within_tolerance",
        "title": "Kazakh act, small difference",
        "story": "Kazakh-language act; running bond 600 × 300 tiles photographed at an angle with glare. The bill is about 3 % above the truth, inside the measurement's uncertainty, so no accusation.",
        "wall": SyntheticWall(
            wall_w_mm=3000,
            wall_h_mm=2400,
            tile_w_mm=600,
            tile_h_mm=300,
            bond="running",
            yaw_deg=14,
            gloss=0.4,
            seed=305,
        ),
        "language": "kk",
        "act_no": 3,
        "address": "ас үй қабырғасын қаптау",
        "lines": lambda true: [
            line(1, "Ескі плитканы бөлшектеу", "demolition", "m2", "ш.м.", 7.0, 1300),
            line(
                2,
                "Қабырғаны керамикалық плиткамен қаптау 600×300",
                "tiling_wall",
                "m2",
                "ш.м.",
                round(true * 1.03, 1),
                9200,
            ),
            line(3, "Тігістерді толтыру", "other", "m2", "ш.м.", round(true * 1.03, 1), 700),
        ],
        "expected": "consistent",
    },
]


def make_act(case, lines):
    kazakh = case["language"] == "kk"
    total = sum(x["amount_stated"] for x in lines)
    if kazakh:
        title = f"ОРЫНДАЛҒАН ЖҰМЫСТАР АКТІСІ № {case['act_no']}"
        header_lines = [
            "Алматы қ.                                                              2026 жылғы 2 қараша",
            "Тапсырыс беруші: **********          Орындаушы: ЖК **********",
            f"Жұмыс: {case['address']}",
        ]
        total_text, signatures = (
            f"Барлығы: {fmt_money(total)} теңге",
            "Орындаушы: __________            Тапсырыс беруші: __________",
        )
    else:
        title = f"АКТ № {case['act_no']} выполненных работ"
        header_lines = [
            "г. Алматы                                                                 «2» ноября 2026 г.",
            "Подрядчик ИП ********** выполнил, а Заказчик ********** принял следующие работы",
            f"по объекту: {case['address']}, г. Алматы, ул. ********, д. **, кв. **",
        ]
        total_text, signatures = (
            f"Итого: {fmt_money(total)} тенге",
            "Подрядчик: __________            Заказчик: __________",
        )
    img, d, y = page(title, header_lines)
    rows = [
        [str(x["line_no"]), x["description_raw"], x["unit_raw"], fmt_qty(x["quantity"]),
         fmt_money(x["unit_price"]), fmt_money(x["amount_stated"])]
        for x in lines
    ]  # fmt: skip
    header = KK_HEADER if kazakh else RU_HEADER
    y = draw_table(d, 60, y, [80, 760, 150, 160, 230, 260], header, rows, font(22), font(23))
    d.text((1000, y + 30), total_text, font=font(30), fill="black")
    d.text((60, y + 170), signatures, font=font(24), fill="black")
    img = stamp(img, (1450, y + 190))
    act = {
        "doc_kind": "completion_act",
        "language": case["language"],
        "currency": "KZT",
        "lines": lines,
        "total_stated": total,
        "vat_stated": None,
        "parser_notes": [],
    }
    return img, act


def measure(wall_path, tile, act):
    """ActCheck's measurement of the wall, compare.py's verdict on the tiling line, the overlay."""
    import tempfile

    from agent.compare import compare_tile_line
    from measure.wall import measure_room
    from schemas.act import ActLine, VerificationPlan

    with tempfile.TemporaryDirectory() as tmp:
        room = measure_room([("wall_1", str(wall_path))], tile, output_dir=tmp)
        wall = room.walls[0]
        overlay = Image.open(wall.overlay_png).convert("RGB") if wall.overlay_png else None
    tiling = next(x for x in act["lines"] if x["work_type"] == "tiling_wall")
    plan = VerificationPlan(
        line_no=tiling["line_no"],
        verifiable="camera",
        method="tile_area",
        surfaces=["wall"],
        reason="wall tiling",
    )
    verdict = compare_tile_line(ActLine(**tiling), plan, room)
    result = {
        "status": wall.status,
        "warnings": wall.warnings,
        "tiled_area_m2": wall.tiled_area_m2,
        "sigma_random_m2": wall.sigma_random_m2,
        "sigma_system_m2": wall.sigma_system_m2,
        "excluded": [e.model_dump() for e in wall.excluded],
        "hidden_area_m2": room.hidden_area_m2,
        "tiling_line_verdict": verdict.verdict,
        "measured_range_m2": [verdict.measured_low, verdict.measured_high],
        "overbilling_min_kzt": verdict.overbilling_min,
    }
    return result, overlay


VERDICTS = {
    "consistent": "No over-billing found",
    "over_billed": "Over-billed",
    "under_billed": "Under-billed",
    "incomplete": "Needs more evidence",
    "not_verifiable": "Not verifiable from a photo",
}


def _embed(image, width):
    """A JPEG data URI of the image scaled to `width` px, so the report stands alone."""
    import base64
    import io

    image = image.convert("RGB")
    image = image.resize((width, round(image.height * width / image.width)))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def report_html(case, details, act_image, wall_image, overlay):
    from html import escape

    w, truth, act = details["wall"], details["truth"], details["act"]
    m = details.get("actcheck")
    tiling = next(x for x in act["lines"] if x["work_type"] == "tiling_wall")
    rows = lambda pairs: "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in pairs)  # noqa: E731
    truth_rows = [
        ("Wall", f"{w['wall_w_mm'] / 1000:g} × {w['wall_h_mm'] / 1000:g} m"),
        (
            "Tile and bond",
            f"{w['tile_w_mm']:g} × {w['tile_h_mm']:g} mm, {w['bond']} bond, {w['grout_mm']:g} mm joint",
        ),
    ]
    if w["door"]:
        truth_rows.append(
            (
                "Door, not tiled",
                f"{w['door'][2] / 1000:g} × {w['door'][3] / 1000:g} m = {truth['opening_area_m2']:.2f} m²",
            )
        )
    if w["occluder_h_mm"]:
        truth_rows.append(
            (
                "Bathtub hiding tiles",
                f"bottom {w['occluder_h_mm'] / 1000:g} m = {truth['hidden_area_m2']:.2f} m²",
            )
        )
    truth_rows += [
        ("<strong>True tiled area</strong>", f"<strong>{truth['tiled_area_m2']:.2f} m²</strong>"),
        ("Visible in the photo", f"{truth['visible_tiled_area_m2']:.2f} m²"),
    ]
    act_rows = "".join(
        f"<tr{' class=hit' if x is tiling else ''}><td>{x['line_no']}</td><td>{escape(x['description_raw'])}</td>"
        f"<td class=n>{fmt_qty(x['quantity'])} {escape(x['unit_raw'])}</td><td class=n>{fmt_money(x['unit_price'])}</td>"
        f"<td class=n>{fmt_money(x['amount_stated'])}</td>"
        f"<td>{'Yes: wall photo' if x is tiling else 'No'}</td></tr>"
        for x in act["lines"]
    )
    bad_sums = [
        x for x in act["lines"] if abs(x["quantity"] * x["unit_price"] - x["amount_stated"]) > 1
    ]
    arithmetic = (
        "".join(
            f"<li>Line {x['line_no']}: {fmt_qty(x['quantity'])} × {fmt_money(x['unit_price'])} = {fmt_money(x['quantity'] * x['unit_price'])} ₸, but the act states {fmt_money(x['amount_stated'])} ₸.</li>"
            for x in bad_sums
        )
        or "<li>Every line's amount equals quantity × price.</li>"
    )
    result = ""
    if m:
        two_sigma = 2 * (m["sigma_random_m2"] + m["sigma_system_m2"])
        got, want = m["tiling_line_verdict"], details["expected_verdict"]
        over = (
            f", at least {fmt_money(m['overbilling_min_kzt'])} ₸"
            if m["overbilling_min_kzt"]
            else ""
        )
        excluded = ", ".join(f"{e['label']} {e['area_m2']:.2f} m²" for e in m["excluded"]) or "none"
        result = f"""
<h2>What ActCheck returned</h2>
<p class=muted>SAM 3.1 on this exact photo; the comparison uses ActCheck's rule: over-billed only if the bill
exceeds the measured area + 2σ + hidden area.</p>
<table>{
            rows(
                [
                    (
                        "Status",
                        f"{m['status']}"
                        + (f" ({', '.join(m['warnings'])})" if m["warnings"] else ""),
                    ),
                    ("Measured tiled area", f"{m['tiled_area_m2']:.2f} ± {two_sigma:.2f} m² (2σ)"),
                    ("Excluded or hidden", excluded),
                    (
                        "Range compared with the bill",
                        f"{m['measured_range_m2'][0]:.2f}–{m['measured_range_m2'][1]:.2f} m²",
                    ),
                    (f"Line {tiling['line_no']} bills", f"{fmt_qty(tiling['quantity'])} m²"),
                ]
            )
        }</table>
<div class="verdict {"ok" if got == want else "warn"}">
  <div><span>Correct answer</span><strong>{VERDICTS[want]}</strong></div>
  <div><span>ActCheck</span><strong>{VERDICTS[got]}{over}</strong></div>
</div>"""
        if got != want:
            result += f"<p class=note><strong>Known limitation.</strong> {escape(case.get('known_limitation', ''))}</p>"
        else:
            result += "<p class=muted>ActCheck matches the correct answer.</p>"
    figures = [("Contractor act", act_image, 900), ("Wall photo", wall_image, 900)]
    if overlay is not None:
        figures.append(("What ActCheck counted", overlay, 900))
    figure_html = "".join(
        f'<figure><img src="{_embed(i, px)}" alt="{t}"><figcaption>{t}</figcaption></figure>'
        for t, i, px in figures
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActCheck test case: {escape(case["title"])}</title>
<style>
:root {{ --ink:#1d1d1f; --muted:#6e6e73; --line:rgb(60 60 67 / .16); --tint:#0a7a70; --warn:#a14d00; }}
body {{ margin:0; background:#f5f5f7; color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Helvetica Neue",Arial,sans-serif; }}
main {{ max-width:860px; margin:0 auto; padding:40px 20px 60px; }}
section {{ background:#fff; border-radius:18px; padding:24px 26px; margin-top:18px; }}
h1 {{ font-size:34px; line-height:1.1; letter-spacing:-.02em; margin:6px 0 8px; }}
h2 {{ font-size:19px; margin:0 0 10px; letter-spacing:-.01em; }}
.kicker {{ color:var(--muted); font-size:14px; }}
.muted {{ color:var(--muted); font-size:13px; }}
table {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:8px 6px; border-bottom:.5px solid var(--line); vertical-align:top; }}
th {{ font-weight:500; color:var(--muted); width:42%; }}
.act th {{ width:auto; font-size:12px; }}
td.n {{ text-align:right; white-space:nowrap; }}
tr.hit td {{ background:#e3f2f0; }}
ol {{ padding-left:20px; margin:0; }} li {{ margin:4px 0; }}
.tile {{ display:inline-block; background:#e3f2f0; color:#075e56; border-radius:10px; padding:2px 10px; font-weight:600; }}
.verdict {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:16px; }}
.verdict div {{ border-radius:14px; padding:14px 16px; background:#e8f5ec; }}
.verdict.warn div:last-child {{ background:#fff2e0; }}
.verdict span {{ display:block; font-size:12px; color:var(--muted); }}
.verdict strong {{ font-size:17px; }}
.note {{ background:#fff2e0; color:#5c2c00; border-radius:12px; padding:12px 14px; }}
figure {{ margin:16px 0 0; }} figure img {{ width:100%; border-radius:12px; display:block; }}
figcaption {{ font-size:13px; color:var(--muted); margin-top:6px; }}
footer {{ color:var(--muted); font-size:12px; margin-top:20px; }}
@media print {{ body {{ background:#fff; }} section {{ padding:12px 0; }} figure {{ break-inside:avoid; }} }}
</style></head><body><main>
<div class=kicker>ActCheck test case · synthetic data</div>
<h1>{escape(case["title"])}</h1>
<p>{escape(case["story"])}</p>
<section><h2>How to run it</h2><ol>
<li>Create a new inspection and enter the tile size <span class=tile>{w["tile_w_mm"]:g} × {w["tile_h_mm"]:g} mm</span>.</li>
<li>Upload <strong>act.jpg</strong> as a statement page and <strong>wall.png</strong> as a wall photo.</li>
<li>Run the analysis and compare the wall-tiling line with the answer below.</li></ol></section>
<section><h2>True measurements</h2><p class=muted>Exact: the photo was rendered from these numbers.</p>
<table>{rows(truth_rows)}</table></section>
<section><h2>The contractor's act</h2><table class=act><tr><th>№</th><th>Work</th><th class=n>Quantity</th><th class=n>Price, ₸</th><th class=n>Amount, ₸</th><th>Checkable</th></tr>{act_rows}</table>
<p class=muted>Arithmetic:</p><ul class=muted>{arithmetic}</ul></section>
<section>{result}</section>
<section><h2>Files</h2>{figure_html}</section>
<footer>Synthetic test data generated by scripts/make_test_cases.py: not a real act, room or company.</footer>
</main></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--measure", action="store_true", help="also run ActCheck's measurement (SAM 3.1)"
    )
    args = parser.parse_args()
    from schemas.measure import TileSpec

    OUT.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        out = OUT / case["id"]
        out.mkdir(parents=True, exist_ok=True)
        wall = case["wall"]
        render = render_wall(wall)
        Image.fromarray(render.image).save(out / "wall.png")
        img, act = make_act(case, case["lines"](render.tiled_area_m2))
        img.convert("RGB").save(out / "act.jpg", quality=90)
        tile = TileSpec(
            width_mm=wall.tile_w_mm,
            height_mm=wall.tile_h_mm,
            grout_mm=wall.grout_mm,
            source="box_label",
        )
        details = {
            "case": case["id"],
            "story": case["story"],
            "tile_to_enter": {"width_mm": wall.tile_w_mm, "height_mm": wall.tile_h_mm, "grout_mm": wall.grout_mm},
            "wall": {
                "wall_w_mm": wall.wall_w_mm, "wall_h_mm": wall.wall_h_mm, "tile_w_mm": wall.tile_w_mm,
                "tile_h_mm": wall.tile_h_mm, "grout_mm": wall.grout_mm, "bond": wall.bond,
                "door": list(wall.door) if wall.door else None, "occluder_h_mm": wall.occluder_h_mm,
                "camera": {"yaw_deg": wall.yaw_deg, "pitch_deg": wall.pitch_deg, "gloss": wall.gloss},
            },
            "truth": {
                "tiled_area_m2": round(render.tiled_area_m2, 3),
                "visible_tiled_area_m2": round(render.visible_tiled_area_m2, 3),
                "hidden_area_m2": round(render.hidden_area_m2, 3),
                "opening_area_m2": round(render.opening_area_m2, 3),
            },
            "act": act,
            "expected_verdict": case["expected"],
        }  # fmt: skip
        overlay = None
        if args.measure:
            details["actcheck"], overlay = measure(out / "wall.png", tile, act)
        (out / "measurement.json").write_text(
            json.dumps(details, ensure_ascii=False, indent=2) + "\n"
        )
        wall_image = Image.fromarray(render.image)
        (out / "report.html").write_text(report_html(case, details, img, wall_image, overlay))
        got = details.get("actcheck", {}).get("tiling_line_verdict", "-")
        print(
            f"{case['id']}: truth {render.tiled_area_m2:.2f} m², expected {case['expected']}, ActCheck {got}"
        )


if __name__ == "__main__":
    main()
