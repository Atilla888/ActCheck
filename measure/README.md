# Measurement — Atilla / B

Reserved for `sam_client.py`, `lattice.py`, `area.py`, `overlay.py`, and `cli.py` after the agreed development start.

Public boundary: `measure_wall(image_path, tile, wall_id, exclude_concepts)` and `measure_room(walls, tile)` from team plan §5. Implement against the shared contract only after agreement. Bad photos should produce explicit warnings and requests to reshoot; every result needs an overlay. Cache responses using the image content, model/version, prompt, and request settings so different segmentation requests cannot collide.

Do not infer verified area from occluded regions. Distinguish openings, visible untiled regions, and unknown areas hidden behind objects. Decide with the team how unavailable measurements are represented before implementing the current numeric-only draft.
