"""Overlays a person checks before trusting a number: every counted tile, every exclusion.

Matched lattice tiles are teal and numbered in row order, other counted area (cut tiles,
borders, completed gaps) is amber, exclusions are grey with their label, and the caption shows
the area with its 2-sigma interval. Failures get the photo with a reshoot banner instead.
"""

import math
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

TEAL = (20, 184, 166)
AMBER = (245, 158, 11)
GREY = (75, 85, 99)
RED = (185, 28, 28)
INK = (17, 24, 39)
WHITE = (255, 255, 255)
LABEL_LIMIT = 200
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
ASCII_FALLBACK = {"m²": "m2", "±": "+/-", "σ": "sigma", "×": "x", "·": "-", "—": "-", "•": "-"}
WARNING_TEXT = {
    "wall_out_of_frame": "the tiled wall continues outside the photo",
    "undetected_area": "part of the wall was not recognised as tiles",
    "high_residual": "the tile grid fits loosely (lens distortion or uneven wall)",
    "merged_tiles": "some neighbouring tiles were merged by segmentation",
    "unreadable_image": "the image file could not be read",
    "segmentation_failed": "tile segmentation is unavailable",
    "too_few_tiles": "too few whole tiles were recognised",
    "lattice_fit_failed": "the recognised tiles do not form one consistent grid",
    "exclusions_unavailable": "doors, mirrors and bathtubs could not be checked",
}


def render_overlay(
    image, fit, area, *, wall_id, status, warnings, out_path, max_side=2000, tile=None
):
    frame, scale = _scaled(image, max_side)
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    _draw_measurement(layer, fit, area, scale, area.full_tiles)
    _caption(layer, _caption_lines(wall_id, fit, area, tile))
    overlay = Image.alpha_composite(frame.convert("RGBA"), layer)
    if status != "measured":
        # Above the photo, so the banner never hides tiles a reviewer needs to check.
        strip = Image.new("RGBA", (frame.width, frame.height), (0, 0, 0, 0))
        height = _banner(strip, AMBER, "PARTIAL MEASUREMENT", _reasons(warnings), frame.size)
        canvas = Image.new("RGBA", (frame.width, frame.height + height), WHITE + (255,))
        canvas.paste(strip.crop((0, 0, frame.width, height)), (0, 0))
        canvas.paste(overlay, (0, height))
        overlay = canvas
    return _save(overlay, out_path)


def render_failure(image, *, wall_id, reasons, out_path, max_side=2000):
    if image is None:
        canvas = Image.new("RGBA", (1200, 800), (31, 41, 55, 255))
    else:
        frame, _ = _scaled(image, max_side)
        canvas = Image.alpha_composite(
            frame.convert("RGBA"), Image.new("RGBA", frame.size, (0, 0, 0, 115))
        )
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _banner(layer, RED, f"{wall_id}: NOT MEASURED — please reshoot", _reasons(reasons))
    return _save(Image.alpha_composite(canvas, layer), out_path)


def render_objects(image, detections, *, concept, out_path, max_side=2000):
    """Outline and number every instance of one concept, with the count as caption."""
    frame, scale = _scaled(image, max_side)
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(max(frame.size) * 0.02)
    width = max(2, round(max(frame.size) / 500))
    for number, detection in enumerate(detections, 1):
        outer = [c["points"] for c in detection["contours"] if not c.get("hole")]
        for points in outer:
            polygon = _points(points, scale)
            if len(polygon) > 2:
                draw.polygon(polygon, fill=TEAL + (90,))
                draw.line(polygon + [polygon[0]], fill=WHITE + (255,), width=width)
        if outer:
            x, y = np.mean(np.concatenate([np.asarray(p) for p in outer]), axis=0) * scale
            draw.text((x, y), str(number), fill=WHITE + (255,), font=font, anchor="mm",
                      stroke_width=2, stroke_fill=INK + (255,))  # fmt: skip
    _caption(layer, [f"{concept}: {len(detections)}"])
    return _save(Image.alpha_composite(frame.convert("RGBA"), layer), out_path)


def render_animation(
    image, fit, area, *, wall_id, out_path, fps=24, seconds=6.0, max_side=1280, tile=None
):
    """Tiles light up in row order with a counter, then the static overlay holds."""
    out_path = Path(out_path)
    final = Image.open(
        render_overlay(
            image,
            fit,
            area,
            wall_id=wall_id,
            status="measured",
            warnings=[],
            out_path=out_path.with_suffix(".final.png"),
            max_side=max_side,
            tile=tile,
        )
    ).convert("RGB")
    frame, scale = _scaled(image, max_side)
    frame = frame.convert("RGBA")
    total = max(2, round(fps * seconds))
    build = max(1, int(total * 0.75))
    blocked = set(area.blocked_ids)
    ordered = sorted((t for t in fit.tiles if t.det_id not in blocked), key=lambda t: (t.j, t.i))
    polygons = [_tile_polygon(fit, t, scale) for t in ordered]
    frames = []
    for index in range(total):
        if index >= build:
            frames.append(final)
            continue
        lit = int(np.ceil(len(ordered) * (index + 1) / build))
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for polygon in polygons[:lit]:
            draw.polygon(polygon, fill=TEAL + (120,), outline=WHITE + (230,))
        _caption(layer, [f"{wall_id}", f"tiles counted: {lit}"])
        frames.append(Image.alpha_composite(frame, layer).convert("RGB"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".gif":
        frames[0].save(
            out_path,
            save_all=True,
            append_images=frames[1:],
            duration=round(1000 / fps),
            loop=0,
            optimize=False,
        )
    else:
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, frames[0].size
        )
        for image_frame in frames:
            writer.write(cv2.cvtColor(np.asarray(image_frame), cv2.COLOR_RGB2BGR))
        writer.release()
    return out_path


def _scaled(image, max_side):
    image = image.convert("RGB")
    scale = min(1.0, max_side / max(image.size))
    if scale < 1:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image, scale


def _font_path():
    candidates = [os.environ.get("ACTCHECK_FONT", ""), *FONT_CANDIDATES]
    return next((path for path in candidates if path and Path(path).is_file()), None)


FONT_PATH = _font_path()


def _font(size):
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, max(10, int(size)))
    return ImageFont.load_default(size=max(10, int(size)))


def _text(value):
    """Pillow's bundled font lacks m², σ and ×; spell them out when no system font exists."""
    if FONT_PATH:
        return value
    for symbol, plain in ASCII_FALLBACK.items():
        value = value.replace(symbol, plain)
    return value


def _points(polygon, scale):
    return [(float(x) * scale, float(y) * scale) for x, y in np.asarray(polygon)]


def _even_odd(polygons, size, scale):
    """Fill mask where nested outlines alternate inside/outside (holes stay empty)."""
    mask = np.zeros((size[1], size[0]), bool)
    for polygon in polygons:
        if len(polygon) < 3 or not np.isfinite(polygon).all():
            continue
        single = Image.new("1", size, 0)
        ImageDraw.Draw(single).polygon(_points(polygon, scale), fill=1)
        mask ^= np.asarray(single, bool)
    return Image.fromarray(mask.astype(np.uint8) * 255)


def _tile_polygon(fit, tile, scale):
    x0, y0, x1, y1 = fit.cell_rect(tile.i, tile.j)
    inset_x, inset_y = (fit.pitch[0] - fit.cell[0]) / 2, (fit.pitch[1] - fit.cell[1]) / 2
    corners = [
        (x0 + inset_x, y0 + inset_y),
        (x1 - inset_x, y0 + inset_y),
        (x1 - inset_x, y1 - inset_y),
        (x0 + inset_x, y1 - inset_y),
    ]
    return _points(fit.to_image(corners), scale)


def _draw_measurement(layer, fit, area, scale, count):
    size = layer.size
    layer.paste(Image.new("RGBA", size, AMBER + (70,)), mask=_even_odd(area.region_px, size, scale))
    for label, polygons in area.excluded_px.items():
        shade = _even_odd(polygons, size, scale)
        layer.paste(Image.new("RGBA", size, GREY + (165,)), mask=shade)
        found = np.argwhere(np.asarray(shade) > 0)
        if len(found):
            y, x = found.mean(axis=0)
            value = sum(r.area_m2 for r in area.excluded if r.label == label)
            text = _text(f"{label.replace('_', ' ')} {value:.2f} m²")
            font = _font(max(size) * 0.018)
            ImageDraw.Draw(layer).text(
                (x, y), text, fill=WHITE + (255,), font=font, anchor="mm", stroke_width=2,
                stroke_fill=INK + (255,),
            )  # fmt: skip
    draw = ImageDraw.Draw(layer)
    blocked = set(area.blocked_ids)
    ordered = sorted((t for t in fit.tiles if t.det_id not in blocked), key=lambda t: (t.j, t.i))
    label_size = np.clip(fit.tile_px * scale * 0.32, 9, 22)
    font = _font(label_size)
    for number, tile in enumerate(ordered, 1):
        polygon = _tile_polygon(fit, tile, scale)
        draw.polygon(polygon, fill=TEAL + (115,), outline=WHITE + (220,))
        x, y = np.mean(polygon, axis=0)
        if count <= LABEL_LIMIT:
            draw.text((x, y), str(number), fill=WHITE + (255,), font=font, anchor="mm",
                      stroke_width=1, stroke_fill=INK + (255,))  # fmt: skip
        else:
            radius = max(1.5, label_size / 5)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=WHITE + (235,))
    for polygon in area.completed_px:
        _dashed(draw, _points(polygon, scale), WHITE + (235,))
    width = max(2, round(max(size) / 600))
    for polygon in area.region_px:
        points = _points(polygon, scale)
        if len(points) > 1:
            draw.line(points + [points[0]], fill=WHITE + (255,), width=width)


def _dashed(draw, points, color, dash=8.0):
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        length = float(np.hypot(x1 - x0, y1 - y0))
        steps = max(1, int(length // dash))
        for k in range(0, steps, 2):
            a, b = k / steps, min(1.0, (k + 1) / steps)
            draw.line(
                [
                    (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                    (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b),
                ],
                fill=color,
                width=2,
            )


def _caption_lines(wall_id, fit, area, tile):
    interval = 2 * float(np.hypot(area.sigma_random_m2, area.sigma_system_m2))
    if tile is not None:
        size = f"{tile.width_mm:g} × {tile.height_mm:g} mm"
    else:
        size = f"{fit.cell[0]:g} × {fit.cell[1]:g} mm"
    partial = f"{area.partial_tiles_equiv:.1f} tile-equivalents"
    return [
        f"{wall_id} · {area.tiled_area_m2:.2f} ± {interval:.2f} m² (2σ)",
        f"{area.full_tiles} whole tiles + {partial} · tile {size}",
    ]


def _caption(layer, lines):
    draw = ImageDraw.Draw(layer)
    width, height = layer.size
    font = _font(max(width, height) * 0.024)
    small = _font(max(width, height) * 0.016)
    fonts = [font] + [small] * (len(lines) - 1)
    lines = [_text(line) for line in lines]
    boxes = [draw.textbbox((0, 0), line, font=f) for line, f in zip(lines, fonts, strict=True)]
    pad = max(width, height) * 0.012
    box_w = max(b[2] - b[0] for b in boxes) + 2 * pad
    box_h = sum(b[3] - b[1] for b in boxes) + pad * (len(lines) + 1)
    left, top = pad, height - box_h - pad
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=pad, fill=INK + (215,))
    y = top + pad
    for line, f, box in zip(lines, fonts, boxes, strict=True):
        draw.text((left + pad, y - box[1]), line, fill=WHITE + (255,), font=f)
        y += box[3] - box[1] + pad


def _banner(layer, color, title, lines, reference=None):
    """Draw a coloured banner at the top of layer and return its height in pixels."""
    draw = ImageDraw.Draw(layer)
    width, height = reference or layer.size
    title_font = _font(max(width, height) * 0.024)
    font = _font(max(width, height) * 0.017)
    pad = max(width, height) * 0.012
    rows = [(_text(title), title_font)] + [(_text(line), font) for line in lines]
    heights = [draw.textbbox((0, 0), text, font=f)[3] for text, f in rows]
    bottom = int(math.ceil(sum(heights) + pad * (len(rows) + 1)))
    draw.rectangle((0, 0, width, bottom), fill=color + (235,))
    y = pad
    for (text, f), h in zip(rows, heights, strict=True):
        draw.text((pad, y), text, fill=WHITE + (255,), font=f)
        y += h + pad
    return bottom


def _reasons(codes):
    return [f"• {WARNING_TEXT.get(code.split(':')[0], code)}" for code in codes]


def _save(image, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out_path)
    return out_path
