# ruff: noqa: E501 — document text and table layouts read better unwrapped
"""Generate synthetic completion acts with ground truth for parser evaluation.

All documents are fictional and labelled SYNTHETIC on the page. Output:
data/samples/synthetic_acts/<act_id>.jpg and <act_id>.json (ground truth).

Usage: uv run python scripts/make_synthetic_acts.py
"""

import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("data/samples/synthetic_acts")
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def fmt_money(x: float) -> str:
    # "460 750" or "460 750,00" — Kazakhstan style, space thousands, comma decimals
    whole, frac = f"{x:,.2f}".split(".")
    return whole.replace(",", " ") + ("" if frac == "00" else "," + frac)


def fmt_qty(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def line(no, desc, work_type, unit, unit_raw, qty, price, amount=None):
    return {
        "line_no": no,
        "description_raw": desc,
        "work_type": work_type,
        "unit": unit,
        "unit_raw": unit_raw,
        "quantity": qty,
        "unit_price": price,
        "amount_stated": amount if amount is not None else round(qty * price, 2),
    }


def draw_table(d, x0, y, widths, header, rows, f_head, f_row, row_h=52, head_h=80):
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    d.rectangle([xs[0], y, xs[-1], y + head_h], outline="black", width=2)
    for i, h in enumerate(header):
        for k, part in enumerate(h.split("\n")):
            d.text((xs[i] + 6, y + 6 + k * 24), part, font=f_head, fill="black")
    y += head_h
    for r in rows:
        for i, v in enumerate(r):
            d.text((xs[i] + 6, y + 12), v, font=f_row, fill="black")
        d.line([(xs[0], y + row_h), (xs[-1], y + row_h)], fill="black", width=1)
        y += row_h
    for x in xs:
        d.line([(x, y - row_h * len(rows) - head_h), (x, y)], fill="black", width=2)
    return y


def stamp(img, center, text="ИП ******\nг. Алматы"):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    for r, w in ((95, 5), (75, 2)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(40, 60, 170, 170), width=w)
    for k, part in enumerate(text.split("\n")):
        d.text((cx - 55, cy - 20 + k * 26), part, font=font(22), fill=(40, 60, 170, 170))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def phone_photo(img, seed):
    """Tilt, perspective, uneven light, noise and blur, like a hand-held phone shot."""
    rng = np.random.default_rng(seed)
    w, h = img.size
    img = img.rotate(rng.uniform(-3, 3), expand=True, fillcolor=(90, 80, 70))
    w, h = img.size
    m = 0.04
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [
        (rng.uniform(0, m) * w, rng.uniform(0, m) * h),
        (w - rng.uniform(0, m) * w, rng.uniform(0, m) * h),
        (w - rng.uniform(0, m) * w, h - rng.uniform(0, m) * h),
        (rng.uniform(0, m) * w, h - rng.uniform(0, m) * h),
    ]
    a = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    coeffs = np.linalg.solve(np.array(a, float), np.array(src, float).reshape(8))
    img = img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(90, 80, 70))
    arr = np.asarray(img).astype(np.float32)
    grad = np.linspace(0.82, 1.05, w)[None, :, None]
    arr = arr * grad + rng.normal(0, 6, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(0.8))


def page(title, header_lines, size=(1800, 1250)):
    img = Image.new("RGB", size, (252, 251, 247))
    d = ImageDraw.Draw(img)
    d.text(
        (60, 20), "SYNTHETIC TEST DOCUMENT — not a real act", font=font(18), fill=(150, 150, 150)
    )
    d.text((size[0] // 2 - len(title) * 9, 60), title, font=font(34), fill="black")
    y = 120
    for t in header_lines:
        d.text((60, y), t, font=font(24), fill="black")
        y += 36
    return img, d, y + 20


def act_r1():
    lines = [
        line(1, "Демонтаж старой облицовки стен", "demolition", "m2", "м2", 24.0, 1200),
        line(2, "Гидроизоляция пола обмазочная", "waterproofing", "m2", "м2", 5.2, 2800),
        line(
            3, "Облицовка стен керамической плиткой 250×400", "tiling_wall", "m2", "м2", 31.6, 9000
        ),
        line(4, "Укладка керамогранита на пол 600×600", "tiling_floor", "m2", "м2", 4.8, 11000),
        line(5, "Установка плинтуса", "skirting", "m", "п.м.", 9.4, 1500),
        line(6, "Установка смесителя", "plumbing_fixture", "pcs", "шт", 2, 6000),
    ]
    total = sum(x["amount_stated"] for x in lines)
    img, d, y = page(
        "АКТ ВЫПОЛНЕННЫХ РАБОТ (ОКАЗАННЫХ УСЛУГ)",
        [
            "ИИН/БИН ************",
            "Заказчик: ********** , г. Алматы",
            "Исполнитель: ИП ********** , г. Алматы",
            "Договор (контракт) № 17 «02» сентября 2026 г.   Номер документа: 31   Дата составления: 14.10.2026",
        ],
    )
    header = [
        "Номер\nпо пор.",
        "Наименование работ (услуг)",
        "Дата\nвыполнения",
        "Сведения\nоб отчете",
        "Единица\nизмерения",
        "количество",
        "цена за\nединицу",
        "стоимость",
    ]
    rows = [
        [
            str(x["line_no"]),
            x["description_raw"],
            "14.10.2026",
            "",
            x["unit_raw"],
            fmt_qty(x["quantity"]),
            fmt_money(x["unit_price"]),
            fmt_money(x["amount_stated"]),
        ]
        for x in lines
    ]
    rows.append(["", "Итого", "", "", "", "х", "х", fmt_money(total)])
    y = draw_table(
        d, 60, y, [110, 620, 150, 130, 140, 170, 170, 200], header, rows, font(19), font(21)
    )
    d.text(
        (60, y + 40),
        "Сдал (Исполнитель) ________ / ________     Принял (Заказчик) ________ / ________",
        font=font(24),
        fill="black",
    )
    d.text(
        (60, y + 90),
        "М.П.                                   Дата подписания: 14.10.2026",
        font=font(24),
        fill="black",
    )
    return img, lines, total, None, [], "ru", "completion_act"


def act_free_form_error():
    lines = [
        line(1, "Выравнивание стен штукатуркой", "plastering", "m2", "м²", 28.0, 2500),
        line(2, "Облицовка стен плиткой 300×600", "tiling_wall", "m2", "м²", 48.5, 9500),
        line(3, "Затирка швов", "other", "m2", "м²", 48.5, 800),
        line(
            4,
            "Установка розеток и выключателей",
            "electrical_point",
            "pcs",
            "шт",
            6,
            3500,
            amount=24000,
        ),
        line(5, "Установка унитаза (инсталляция)", "plumbing_fixture", "pcs", "шт", 1, 25000),
    ]
    total = sum(x["amount_stated"] for x in lines)
    img, d, y = page(
        "АКТ № 8 сдачи-приемки выполненных работ",
        [
            "г. Алматы                                                                 «21» октября 2026 г.",
            "Подрядчик ИП ********** выполнил, а Заказчик ********** принял следующие работы",
            "по ремонту санузла в квартире по адресу: г. Алматы, ул. ********, д. **, кв. **",
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
        (60, y + 110),
        "Работы выполнены в полном объеме. Претензий по качеству и срокам нет.",
        font=font(24),
        fill="black",
    )
    d.text(
        (60, y + 170),
        "Подрядчик: __________            Заказчик: __________",
        font=font(24),
        fill="black",
    )
    # 6 × 3 500 = 21 000, stated 24 000
    return img, lines, total, None, [{"line_no": 4, "kind": "line_amount"}], "ru", "completion_act"


def act_kazakh():
    lines = [
        line(1, "Ескі плитканы бөлшектеу", "demolition", "m2", "ш.м.", 18.0, 1300),
        line(
            2, "Қабырғаларды керамикалық плиткамен қаптау", "tiling_wall", "m2", "ш.м.", 27.4, 9200
        ),
        line(3, "Еденге плитка төсеу", "tiling_floor", "m2", "ш.м.", 3.6, 10500),
        line(4, "Гидрооқшаулау", "waterproofing", "m2", "ш.м.", 6.0, 3000),
        line(5, "Раковина орнату", "plumbing_fixture", "pcs", "дана", 1, 12000),
    ]
    total = sum(x["amount_stated"] for x in lines)
    img, d, y = page(
        "ОРЫНДАЛҒАН ЖҰМЫСТАР АКТІСІ № 5",
        [
            "Алматы қ.                                                              2026 жылғы 19 қазан",
            "Тапсырыс беруші: **********          Орындаушы: ЖК **********",
            "Шарт № 12, 2026 жылғы 1 қыркүйек",
        ],
    )
    header = [
        "Р/с\n№",
        "Жұмыстардың атауы",
        "Өлшем\nбірлігі",
        "Саны",
        "Бағасы,\nтеңге",
        "Құны,\nтеңге",
    ]
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
    y = draw_table(d, 60, y, [90, 760, 160, 150, 230, 260], header, rows, font(21), font(23))
    d.text((980, y + 30), f"Барлығы: {fmt_money(total)} теңге", font=font(30), fill="black")
    d.text(
        (60, y + 110),
        "Тапсырды (Орындаушы): ________        Қабылдады (Тапсырыс беруші): ________",
        font=font(24),
        fill="black",
    )
    return img, lines, total, None, [], "kk", "completion_act"


def act_estimate():
    lines = [
        line(1, "Демонтаж ванны и плитки", "demolition", "lump_sum", "компл.", 1, 35000),
        line(2, "Облицовка стен плиткой (кабанчик 75×150)", "tiling_wall", "m2", "м2", 22.3, 12500),
        line(3, "Укладка плитки на пол", "tiling_floor", "m2", "м2", 3.9, 10000),
        line(4, "Покраска потолка водоэмульсионной краской", "painting", "m2", "м2", 4.2, 1800),
        line(5, "Плитка настенная 75×150 (материал)", "materials", "m2", "м2", 24.5, 7800),
        line(6, "Клей плиточный, 25 кг (материал)", "materials", "pcs", "меш.", 8, 3200),
        line(7, "Вывоз строительного мусора", "other", "lump_sum", "усл.", 1, 15000),
    ]
    total = sum(x["amount_stated"] for x in lines)
    vat = round(total * 0.12 / 1.12, 2)
    img, d, y = page(
        "СМЕТА на ремонт санузла",
        [
            "Объект: квартира, г. Астана, ул. ********",
            "Составлено: 05.10.2026       Исполнитель: ТОО «*********»",
        ],
    )
    header = ["№", "Наименование работ и материалов", "Ед.", "Кол.", "Цена", "Сумма"]
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
    y = draw_table(d, 60, y, [70, 820, 130, 130, 230, 260], header, rows, font(22), font(22))
    d.text((960, y + 30), f"Всего по смете: {fmt_money(total)} тг", font=font(28), fill="black")
    d.text((960, y + 75), f"в т.ч. НДС 12%: {fmt_money(vat)} тг", font=font(26), fill="black")
    return img, lines, total, vat, [], "ru", "estimate"


def act_phone_photo():
    img, lines, total, vat, errors, lang, kind = act_free_form_error()
    lines = [dict(x) for x in lines]
    img = stamp(img, (1350, 820))
    return phone_photo(img, seed=7), lines, total, vat, errors, lang, kind


ACTS = {
    "r1_official": act_r1,
    "free_form_error": act_free_form_error,
    "kazakh": act_kazakh,
    "estimate_vat": act_estimate,
    "phone_photo": act_phone_photo,
}


def main():
    random.seed(0)
    OUT.mkdir(parents=True, exist_ok=True)
    for act_id, make in ACTS.items():
        img, lines, total, vat, errors, lang, kind = make()
        img.save(OUT / f"{act_id}.jpg", quality=88)
        truth = {
            "doc_kind": kind,
            "language": lang,
            "lines": lines,
            "total_stated": total,
            "vat_stated": vat,
            "planted_errors": errors,
        }
        (OUT / f"{act_id}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1))
        print(f"{act_id}: {len(lines)} lines, total {total}, errors {errors}")


if __name__ == "__main__":
    main()
