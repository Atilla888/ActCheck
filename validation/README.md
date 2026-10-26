# Validation — Atilla / B

`rooms.csv` is an empty public template using the team-plan columns. Keep actual field records, identifying notes, consent evidence, and photos under ignored `data/private/`; publish only approved anonymized rows here.

Record laser ground truth independently from predictions. Preserve wall-to-room grouping. Keep all versions of a room together when splitting data for threshold selection and evaluation. Label artificially inflated statements as `planted`; do not present them as observed contractor behavior.

Planned outputs: per-wall and per-room accuracy, MAPE and median error, uncertainty coverage, ROC/AUC over 0–30% planted inflation, and a matched comparison against a classical grout detector. Do not invent rooms, ground truth, or validation scores.
