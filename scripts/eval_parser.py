# ruff: noqa: E501 — HTML template lines
"""Evaluate the act parser against ground-truth JSON next to each image.

Usage: uv run python scripts/eval_parser.py [--provider meta|baseten] [DIR]
Default DIR: data/samples/synthetic_acts
"""

import argparse
import html
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.act_parser import parse_act  # noqa: E402
from agent.arithmetic import audit  # noqa: E402

FIELDS = ("quantity", "unit_price", "amount_stated", "unit", "work_type")


def same(a, b):
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(a - b) < 0.005
    return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="data/samples/synthetic_acts")
    ap.add_argument("--provider", choices=["meta", "baseten"], default=None)
    ap.add_argument("--html", help="write a side-by-side HTML report to this path")
    args = ap.parse_args()

    hits = {f: 0 for f in FIELDS}
    n_lines = errors_found = errors_planted = false_alarms = 0
    records = []
    for truth_path in sorted(Path(args.dir).glob("*.json")):
        truth = json.loads(truth_path.read_text())
        image = truth_path.with_suffix(".jpg")
        t0 = time.time()
        doc = parse_act([image], provider=args.provider)
        dt = time.time() - t0

        by_no = {ln.line_no: ln for ln in doc.lines}
        misses = []
        for exp in truth["lines"]:
            got = by_no.get(exp["line_no"])
            n_lines += 1
            for f in FIELDS:
                if got is not None and same(getattr(got, f), exp[f]):
                    hits[f] += 1
                else:
                    misses.append(f"#{exp['line_no']} {f}: {getattr(got, f, None)!r} != {exp[f]!r}")

        planted = {(e["line_no"], e["kind"]) for e in truth["planted_errors"]}
        issues = audit(doc)
        found = {(i.line_no, i.kind) for i in issues}
        records.append((truth_path.stem, image, truth, doc, issues, dt))
        errors_planted += len(planted)
        errors_found += len(planted & found)
        false_alarms += len(found - planted)

        flags = [
            f"lines {len(doc.lines)}/{len(truth['lines'])}",
            f"total {'ok' if same(doc.total_stated, truth['total_stated']) else doc.total_stated}",
            f"lang {doc.language}",
            f"errors {len(planted & found)}/{len(planted)} +{len(found - planted)} false",
        ]
        print(f"{truth_path.stem:18} {dt:5.1f}s  " + " | ".join(flags))
        for m in misses:
            print("    ", m)

    print("\nField accuracy over", n_lines, "lines:")
    for f in FIELDS:
        print(f"  {f:14} {hits[f] / n_lines:6.1%}")
    print(f"Planted errors caught: {errors_found}/{errors_planted}, false alarms: {false_alarms}")

    if args.html:
        summary = {f: hits[f] / n_lines for f in FIELDS}
        summary["errors"] = f"{errors_found}/{errors_planted}, ложных: {false_alarms}"
        write_report(records, summary, Path(args.html))
        print("Report:", args.html)


def write_report(records, summary, out: Path):
    """Side-by-side HTML: act image | ground truth vs parsed, mismatches in red."""
    out.parent.mkdir(parents=True, exist_ok=True)
    esc = html.escape
    labels = {
        "quantity": "Кол-во",
        "unit_price": "Цена",
        "amount_stated": "Сумма",
        "unit": "Ед.",
        "work_type": "Тип работ",
    }
    cards = []
    for act_id, image, truth, doc, issues, dt in records:
        by_no = {ln.line_no: ln for ln in doc.lines}
        rows = []
        for exp in truth["lines"]:
            got = by_no.get(exp["line_no"])
            cells = [f"<td>{exp['line_no']}</td><td>{esc(exp['description_raw'])}</td>"]
            for f in FIELDS:
                g = getattr(got, f, None)
                ok = got is not None and same(g, exp[f])
                body = esc(str(exp[f])) if ok else f"{esc(str(exp[f]))}<br><s>{esc(str(g))}</s>"
                cells.append(f'<td class="{"ok" if ok else "bad"}">{body}</td>')
            rows.append("<tr>" + "".join(cells) + "</tr>")
        planted = {(e["line_no"], e["kind"]) for e in truth["planted_errors"]}
        found = [
            f"<li class='{'ok' if (i.line_no, i.kind) in planted else 'bad'}'>строка {i.line_no}: "
            f"{i.kind}, ожидалось {i.expected}, в акте {i.stated} (разница {i.diff})</li>"
            for i in issues
        ]
        missed = [
            f"<li class='bad'>не найдена: строка {n} ({k})</li>"
            for n, k in planted - {(i.line_no, i.kind) for i in issues}
        ]
        audit_html = "".join(found + missed) or "<li class='ok'>ошибок нет (и не закладывали)</li>"
        total_ok = same(doc.total_stated, truth["total_stated"])
        head = "".join(f"<th>{labels[f]}</th>" for f in FIELDS)
        cards.append(f"""
<section>
 <h2>{esc(act_id)} <small>{dt:.1f} с · язык: {doc.language} · строк {len(doc.lines)}/{len(truth["lines"])}
  · итог {"✓" if total_ok else "✗ " + str(doc.total_stated)} {truth["total_stated"]:,.0f}</small></h2>
 <div class="grid">
  <a href="{image.resolve().as_uri()}" target="_blank"><img src="{image.resolve().as_uri()}"></a>
  <div>
   <table><tr><th>№</th><th>Описание (эталон)</th>{head}</tr>{"".join(rows)}</table>
   <h3>Проверка арифметики (код)</h3><ul>{audit_html}</ul>
  </div>
 </div>
</section>""")
    acc = " · ".join(f"{labels[f]} {summary[f]:.0%}" for f in FIELDS)
    out.write_text(f"""<!doctype html><meta charset="utf-8"><title>Parser eval</title>
<style>
body{{font:15px system-ui;margin:24px;background:#fafafa;color:#111}}
section{{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px;margin:18px 0}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:18px}}
img{{width:100%;border:1px solid #ccc}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:5px 7px;text-align:left;vertical-align:top}}
.ok{{background:#e8f6ea}} .bad{{background:#fde4e4}} s{{color:#b00}} small{{color:#666;font-weight:400}}
li{{padding:3px 6px;margin:3px 0;list-style:none}}
</style>
<h1>Разбор актов: эталон против модели</h1>
<p>Зелёное — модель прочитала как в эталоне. Красное — расхождение (эталон сверху, ответ модели
зачёркнут). Арифметику проверяет код, а не модель.</p>
<p><b>Точность:</b> {acc} · <b>Заложенные ошибки:</b> {summary["errors"]}</p>
{"".join(cards)}""")


if __name__ == "__main__":
    main()
