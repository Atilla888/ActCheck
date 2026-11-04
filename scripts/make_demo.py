# ruff: noqa: E501 — document text reads better unwrapped
"""Build the "try a sample" inspection: a synthetic act that matches B's measurement of a synthetic
wall from simulated masks (data/samples/measure_example.*). Output: data/samples/demo/.

The act over-bills wall tiling (6.2 m2 billed, the photo supports at most ~4.2 m2 including the
area hidden by the bathtub) and has one arithmetic error (grout line).

Usage: uv run python scripts/make_demo.py
"""

import json
from pathlib import Path

from make_synthetic_acts import draw_table, fmt_money, fmt_qty, font, line, page, stamp
from PIL import Image

OUT = Path("data/samples/demo")
SAMPLES = Path("data/samples")


def act_demo():
    lines = [
        line(1, "Демонтаж старой плитки", "demolition", "m2", "м²", 4.5, 1500),
        line(2, "Гидроизоляция стен в зоне ванны", "waterproofing", "m2", "м²", 3.0, 3000),
        line(3, "Облицовка стены плиткой 300×150", "tiling_wall", "m2", "м²", 6.2, 9500),
        line(4, "Затирка швов", "other", "m2", "м²", 6.2, 800, amount=5960),
        line(5, "Установка смесителя", "plumbing_fixture", "pcs", "шт", 1, 12000),
    ]
    total = sum(x["amount_stated"] for x in lines)
    img, d, y = page(
        "АКТ № 3 выполненных работ",
        [
            "г. Алматы                                                                 «28» октября 2026 г.",
            "Подрядчик ИП ********** выполнил, а Заказчик ********** принял следующие работы",
            "по облицовке стены у ванны: г. Алматы, ул. ********, д. **, кв. **",
        ],
    )
    header = ["№", "Наименование работ", "Ед. изм.", "Кол-во", "Цена, тг", "Сумма, тг"]
    rows = [
        [
            str(x["line_no"]),
            x["description_raw"],
            x["unit_raw"],
            fmt_qty(x["quantity"]),
            fmt_money(x["unit_price"]),
            fmt_money(x["amount_stated"]),
        ]
        for x in lines
    ]
    y = draw_table(d, 60, y, [80, 760, 150, 160, 230, 260], header, rows, font(22), font(23))
    d.text((1000, y + 30), f"Итого: {fmt_money(total)} тенге", font=font(30), fill="black")
    d.text(
        (60, y + 170),
        "Подрядчик: __________            Заказчик: __________",
        font=font(24),
        fill="black",
    )
    img = stamp(img, (1450, y + 190))
    act = {
        "doc_kind": "completion_act",
        "language": "ru",
        "currency": "KZT",
        "lines": lines,
        "total_stated": total,
        "vat_stated": None,
        "parser_notes": [],
    }
    return img, act


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    img, act = act_demo()
    img.convert("RGB").save(OUT / "act.jpg", quality=90)
    (OUT / "act.json").write_text(json.dumps(act, ensure_ascii=False, indent=2) + "\n")

    wall = json.loads((SAMPLES / "measure_example.json").read_text())
    wall["image_path"] = "wall_1.png"
    wall["overlay_png"] = "wall_1_overlay.jpg"
    (OUT / "wall_1.json").write_text(json.dumps(wall, indent=2) + "\n")
    with Image.open(SAMPLES / "measure_example.png") as overlay:
        overlay.convert("RGB").save(OUT / "wall_1_overlay.jpg", quality=85)
    print(f"wrote {OUT}/: act.jpg, act.json, wall_1.json, wall_1_overlay.jpg")


if __name__ == "__main__":
    main()
