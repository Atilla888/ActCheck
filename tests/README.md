# Tests

Offline and deterministic: no test sends a request to SAM. Tests that need the local reference
photos or cached responses skip when those are absent.

- `test_sam_client.py`: benchmark-compatible cache keys, key-free cached segmentation,
  endpoint refusal, converted-mask reuse, worker fallback.
- `test_synthetic.py`: renderer ground truth, running bond, SAM-like mask format.
- `test_lattice.py`: homography accuracy on frontal/oblique walls, running and vertical bond,
  dropout, merges, false positives, orientation swap, two planes, cut edge tiles.
- `test_area.py`: area within 1–3 %, out-of-frame, doors, occluders, holes, mosaic, floor
  blocking, strips beyond doors, missed edge tiles, systematic sigma formula.
- `test_overlay.py`, `test_measure_wall.py`: overlays, animation, statuses, refusals, room
  aggregation, determinism, CLI, object counting.
- `test_synthetic_eval.py`, `test_validation_scripts.py`: accuracy sweep, field table, planted ROC.
- `test_tile_benchmark.py`, `test_crop_*.py`, `test_agent_logic.py`: benchmark and agent logic.

Run: `uv run pytest -q`.
