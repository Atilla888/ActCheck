"""Debug CLI: `python -m measure.cli wall photo.jpg --tile 300x600` prints JSON, saves overlay."""

import argparse
import re
import sys
from pathlib import Path

from measure.overlay import render_animation
from measure.wall import DEFAULT_EXCLUDE, analyze_wall, count_objects, measure_room
from schemas.measure import TileSpec


def parse_tile(text, grout, source):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*", text)
    if not match:
        raise argparse.ArgumentTypeError(f"tile size must look like 300x600, got {text!r}")
    return TileSpec(
        width_mm=float(match[1]), height_mm=float(match[2]), grout_mm=grout, source=source
    )


def main(argv=None, *, segmenter=None):
    parser = argparse.ArgumentParser(prog="python -m measure.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("wall", "room"):
        sub = commands.add_parser(name)
        sub.add_argument("--tile", required=True, help="tile size in mm, e.g. 300x600")
        sub.add_argument("--grout", type=float, default=2.0, help="joint width in mm")
        sub.add_argument("--source", default="user", choices=["box_label", "act", "user", "tape"])
        sub.add_argument("--out", type=Path, default=None, help="overlay directory")
    wall = commands.choices["wall"]
    wall.add_argument("photo")
    wall.add_argument("--wall-id", default=None)
    wall.add_argument("--exclude", nargs="*", default=list(DEFAULT_EXCLUDE))
    wall.add_argument("--animate", action="store_true", help="also write an MP4 of the tiles")
    room = commands.choices["room"]
    room.add_argument("walls", nargs="+", help="WALL_ID=photo.jpg")
    count = commands.add_parser("count")
    count.add_argument("photo")
    count.add_argument("--concept", required=True)
    count.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "count":
        result = count_objects(args.photo, args.concept, output_dir=args.out, segmenter=segmenter)
        print(result.model_dump_json(indent=2))
        return 0
    tile = parse_tile(args.tile, args.grout, args.source)
    if args.command == "wall":
        wall_id = args.wall_id or Path(args.photo).stem
        analysis = analyze_wall(
            args.photo, tile, wall_id, args.exclude, output_dir=args.out, segmenter=segmenter
        )
        if args.animate and analysis.fit is not None:
            render_animation(
                analysis.image,
                analysis.fit,
                analysis.area,
                wall_id=wall_id,
                out_path=Path(analysis.result.overlay_png).with_suffix(".mp4"),
                tile=tile,
            )
        print(analysis.result.model_dump_json(indent=2))
        return 0
    pairs = []
    for item in args.walls:
        wall_id, separator, photo = item.partition("=")
        if not separator or not photo:
            parser.error(f"expected WALL_ID=photo.jpg, got {item!r}")
        pairs.append((wall_id, photo))
    result = measure_room(pairs, tile, output_dir=args.out, segmenter=segmenter)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
