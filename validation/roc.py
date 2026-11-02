"""Planted-inflation ROC for the agent's over-billing rule `billed > measured + k·σ + hidden`.

Each row is one wall with known truth (a synthetic render or a laser/tape measurement). Honest
bills equal the truth; planted bills inflate it by r. The bills are planted, never observed
contractor statements, and every output says so. agent/compare.py flags at k = 2.

    python -m validation.roc outputs/validation/roc_input.json --out outputs/validation/roc.json
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

INFLATIONS = np.arange(0.025, 0.301, 0.025)
KS = np.arange(0, 5.01, 0.25)
AGENT_K = 2.0  # agent/compare.py K_SIGMA
DETECTED = 0.9  # detection rate at which an inflation counts as detectable
RULE = "billed > measured + k*sigma + hidden, only for walls with status measured"
LABEL = "planted inflation of known truth, not observed contractor bills"
BRIEF = ("n_rows", "auc", "false_alarm_rate_at_k2", "min_detectable_inflation_at_k2")


def roc_table(rows: list[dict], inflations=INFLATIONS, ks=KS) -> dict:
    """TPR/FPR per k, AUC and detection per planted inflation at k = 2; no-number rows skipped."""
    used = [r for r in rows if r.get("measured_m2") is not None and r.get("truth_m2") is not None]
    kinds = Counter(_kind(r) for r in used)
    table = {
        "planted": True,
        "label": LABEL,
        "rule": RULE,
        "skipped": len(rows) - len(used),
        "kinds": dict(sorted(kinds.items())),
        "inflations": [round(float(r), 4) for r in inflations],
        **_roc(used, inflations, ks),
        "by_kind": {},
    }
    for kind in table["kinds"]:
        part = _roc([r for r in used if _kind(r) == kind], inflations, ks)
        table["by_kind"][kind] = {key: part[key] for key in BRIEF}
    return table


def _roc(rows, inflations, ks):
    if not rows:
        return {
            "n_rows": 0,
            "curve": [],
            "auc": None,
            "by_inflation_at_k2": [],
            "min_detectable_inflation_at_k2": None,
            "false_alarm_rate_at_k2": None,
        }
    truth, measured, sigma, hidden = (
        np.array([float(r.get(key) or 0.0) for r in rows])
        for key in ("truth_m2", "measured_m2", "sigma_m2", "hidden_m2")
    )
    inflations = np.asarray(inflations, dtype=float)
    planted = truth[:, None] * (1 + inflations)  # one column per inflation
    # The agent answers "incomplete" for any wall that is not fully measured: never flagged.
    measured_only = np.array([r.get("status", "measured") == "measured" for r in rows])

    def limit(k):
        return np.where(measured_only, measured + k * sigma + hidden, np.inf)

    curve = [
        {
            "k": round(float(k), 4),
            "tpr": _rate(planted > limit(k)[:, None]),
            "fpr": _rate(truth > limit(k)),
        }
        for k in np.asarray(ks, dtype=float)
    ]
    fpr, tpr = np.array(sorted({(p["fpr"], p["tpr"]) for p in curve} | {(0.0, 0.0), (1.0, 1.0)})).T
    detection = (planted > limit(AGENT_K)[:, None]).mean(axis=0)
    by_inflation = [
        {"inflation": round(float(r), 4), "detection_rate": round(float(rate), 4)}
        for r, rate in zip(inflations, detection, strict=True)
    ]
    return {
        "n_rows": len(rows),
        "curve": curve,
        "auc": round(float(np.trapezoid(tpr, fpr)), 4),
        "by_inflation_at_k2": by_inflation,
        "min_detectable_inflation_at_k2": min(
            (p["inflation"] for p in by_inflation if p["detection_rate"] >= DETECTED), default=None
        ),
        "false_alarm_rate_at_k2": _rate(truth > limit(AGENT_K)),
    }


def _rate(flags):
    return round(float(np.mean(flags)), 4)


def _kind(row):
    return str(row.get("kind") or "unknown")


def summary_markdown(table: dict) -> str:
    inflations = table["inflations"]
    span = f"{_pct(min(inflations))}–{_pct(max(inflations))}" if inflations else "—"
    kinds = ", ".join(f"{n} {kind}" for kind, n in table["kinds"].items()) or "none"
    field = table["kinds"].get("field", 0)
    if not field:
        scope = "No field rows: synthetic walls only, so this is not field accuracy."
    elif field == table["n_rows"]:
        scope = f"Field rows only: {field} laser/tape-measured walls (small N)."
    else:
        scope = (
            f"Field rows: {field} laser/tape-measured walls (small N); the other rows are "
            "synthetic and say nothing about field accuracy."
        )
    lines = [
        "# Planted-inflation ROC",
        "",
        f"Every bill below is **planted inflation**: a row's known truth inflated by {span}; "
        "honest bills equal the truth. None is an observed contractor bill.",
        f"Rule (agent/compare.py): over-billed when `{RULE}`; σ is 1σ and the agent uses k = 2.",
        f"Rows: N = {table['n_rows']} ({kinds}); skipped without a measurement: "
        f"{table['skipped']} (the agent answers `incomplete` for those).",
        scope,
        "",
        "| planted inflation | detected at k = 2 |",
        "|---:|---:|",
        *(
            f"| {_pct(p['inflation'])} | {_pct(p['detection_rate'])} |"
            for p in table["by_inflation_at_k2"]
        ),
        "",
        "- False alarms on honest bills (planted inflation 0 %) at k = 2: "
        f"{_pct(table['false_alarm_rate_at_k2'])}",
        "- Smallest planted inflation detected in ≥ 90 % of rows at k = 2: "
        f"{_pct(table['min_detectable_inflation_at_k2'])}",
        f"- AUC over k = 0–5 (planted inflation {span}): {_number(table['auc'])}",
    ]
    if len(table["by_kind"]) > 1:
        lines += [
            "",
            "| kind | N | AUC (planted inflation) | false alarms at k = 2 "
            "| smallest planted inflation detected ≥ 90 % at k = 2 |",
            "|---|---:|---:|---:|---:|",
            *(
                f"| {kind} | {part['n_rows']} | {_number(part['auc'])} "
                f"| {_pct(part['false_alarm_rate_at_k2'])} "
                f"| {_pct(part['min_detectable_inflation_at_k2'])} |"
                for kind, part in table["by_kind"].items()
            ),
        ]
    return "\n".join(lines) + "\n"


def _pct(value):
    return "—" if value is None else f"{100 * value:.1f} %"


def _number(value):
    return "—" if value is None else f"{value:.3f}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m validation.roc", description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="roc_input JSON files (row lists)")
    parser.add_argument("--out", type=Path, default=Path("outputs/validation/roc.json"))
    args = parser.parse_args(argv)
    rows = [row for path in args.inputs for row in json.loads(path.read_text())]
    table = {**roc_table(rows), "inputs": [str(path) for path in args.inputs]}
    markdown = summary_markdown(table)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, indent=2) + "\n")
    args.out.with_suffix(".md").write_text(markdown)
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
