"""Publishable example outputs for integration: synthetic walls only, no private photos.

Writes data/samples/measure_example.{json,png} (one wall with a door and a bathtub band) and
data/samples/room_example.json (that wall plus a second, oblique one). Masks come from the
renderer, so no API call is made and the files are reproducible.
"""

import json
import shutil

from PIL import Image

from measure.sam_client import ROOT
from measure.wall import measure_room, measure_wall
from schemas.measure import TileSpec
from validation.synthetic import SyntheticWall, render_wall
from validation.synthetic_eval import _mask_segmenter

SAMPLES = ROOT / "data/samples"
WALLS = {
    "wall_1": SyntheticWall(
        tile_w_mm=300, tile_h_mm=150, bond="running", yaw_deg=20, pitch_deg=6, gloss=0.5,
        door=(1500, 300, 700, 1800), occluder_h_mm=500, seed=31,
    ),
    "wall_2": SyntheticWall(tile_w_mm=300, tile_h_mm=150, bond="running", yaw_deg=-25, seed=32),
}  # fmt: skip
TILE = TileSpec(width_mm=300, height_mm=150, grout_mm=2, source="box_label")


def main():
    work = ROOT / "outputs/samples"
    work.mkdir(parents=True, exist_ok=True)
    renders, paths = {}, {}
    for wall_id, wall in WALLS.items():
        renders[wall_id] = render_wall(wall)
        paths[wall_id] = work / f"{wall_id}.png"
        Image.fromarray(renders[wall_id].image).save(paths[wall_id])
    segmenters = {str(paths[w]): _mask_segmenter(renders[w]) for w in WALLS}
    pending = list(paths.values())

    def segment(image, concepts):
        return segmenters[str(pending.pop(0))](image, concepts)

    wall = measure_wall(str(paths["wall_1"]), TILE, "wall_1", output_dir=work, segmenter=segment)
    shutil.copy(wall.overlay_png, SAMPLES / "measure_example.png")
    example = wall.model_copy(
        update={"image_path": "wall_1.png", "overlay_png": "data/samples/measure_example.png"}
    )
    (SAMPLES / "measure_example.json").write_text(example.model_dump_json(indent=2) + "\n")
    pending[:] = list(paths.values())
    room = measure_room(
        [(w, str(p)) for w, p in paths.items()], TILE, output_dir=work, segmenter=segment
    )
    for index, item in enumerate(room.walls):
        # wall_1 is measured exactly as in measure_example: reuse that overlay, no duplicate.
        name = "measure_example.png" if item.wall_id == "wall_1" else f"room_{item.wall_id}.png"
        if item.wall_id != "wall_1":
            shutil.copy(item.overlay_png, SAMPLES / name)
        room.walls[index] = item.model_copy(
            update={"image_path": f"{item.wall_id}.png", "overlay_png": f"data/samples/{name}"}
        )
    (SAMPLES / "room_example.json").write_text(room.model_dump_json(indent=2) + "\n")
    truth = {w: round(r.visible_tiled_area_m2, 3) for w, r in renders.items()}
    print(json.dumps({"visible_truth_m2": truth, "wall_1": wall.tiled_area_m2}, indent=2))


if __name__ == "__main__":
    main()
