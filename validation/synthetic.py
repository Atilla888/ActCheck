"""Synthetic tiled walls with exact ground truth, plus SAM-like masks of their tiles.

Plane coordinates are millimetres: x right, y down, origin at the wall's top-left corner.
Image coordinates are continuous pixels, pixel (u, v) covering [u, u+1) × [v, v+1), as in the
contours of ``measure.crop_merge``. Renders and masks are synthetic, never field evidence.
"""

from dataclasses import dataclass
from math import ceil, cos, radians, sin
from typing import Literal

import cv2
import numpy as np
from scipy.optimize import brentq

PX_PER_MM = 2.0
MAX_TEXTURE_PX = 8000
MIN_MASK_PX = 25
# Every tile colour keeps at least ~35 grey levels of contrast with both grout colours.
TILE_COLOURS = (
    (242, 242, 238),
    (150, 172, 152),
    (128, 150, 166),
    (182, 108, 78),
    (162, 152, 140),
    (176, 160, 128),
    (84, 136, 138),
    (32, 32, 34),
)
GROUT_COLOURS = ((205, 203, 198), (68, 68, 72))
PAINT_COLOURS = ((224, 220, 210), (212, 218, 220), (232, 228, 218), (206, 200, 188))
WOOD, WOOD_FRAME, HANDLE = (150, 104, 66), (112, 76, 48), (196, 196, 190)
RIM = (150, 150, 156)


@dataclass(frozen=True)
class SyntheticWall:
    """One planar tiled wall photographed by a pinhole camera; lengths in millimetres.

    ``door`` is an untiled opening (x, y, w, h). ``occluder_h_mm`` hides a bottom band of the
    wall in the image. ``fill`` is the share of the frame spanned by the wall's bounding box
    along its tighter axis; above 1 the frame cuts the wall.
    """

    wall_w_mm: float = 2400
    wall_h_mm: float = 2100
    tile_w_mm: float = 300
    tile_h_mm: float = 600
    grout_mm: float = 2
    bond: Literal["stack", "running"] = "stack"
    yaw_deg: float = 0
    pitch_deg: float = 0
    roll_deg: float = 0
    image_size: tuple[int, int] = (1600, 1200)
    fill: float = 0.8
    door: tuple[float, float, float, float] | None = None
    occluder_h_mm: float = 0
    gloss: float = 0.0
    seed: int = 0

    def __post_init__(self):
        sizes = (self.wall_w_mm, self.wall_h_mm, self.tile_w_mm, self.tile_h_mm, self.fill)
        if min(sizes) <= 0 or self.grout_mm < 0 or min(self.image_size) <= 0:
            raise ValueError("Sizes and fill must be positive and grout non-negative")
        if self.bond not in ("stack", "running"):
            raise ValueError(f"Unknown bond: {self.bond}")
        if not 0 <= self.occluder_h_mm <= self.wall_h_mm:
            raise ValueError("The occluded band must lie within the wall height")
        if self.door is not None:
            x, y, w, h = self.door
            if min(w, h) <= 0 or min(x, y) < 0 or x + w > self.wall_w_mm or y + h > self.wall_h_mm:
                raise ValueError("The door must be a non-empty rectangle inside the wall")


@dataclass
class SynthTile:
    """A tile (or one piece of a tile split by the door), clipped to the wall minus the door.

    ``cell_mm`` is the unclipped tile grown by half a joint per side; cells tile the plane.
    """

    i: int
    j: int
    polygon: np.ndarray
    plane_polygon: np.ndarray
    cell_mm: tuple[float, float, float, float]
    full: bool


@dataclass
class Render:
    """A synthetic photo and its exact ground truth; areas count tiles plus joints.

    ``visible_tiled_area_m2`` removes only the occluded band, not parts cut by the frame.
    """

    wall: SyntheticWall
    image: np.ndarray
    plane_to_image: np.ndarray
    tiles: list[SynthTile]
    tiled_area_m2: float
    visible_tiled_area_m2: float
    hidden_area_m2: float
    opening_area_m2: float
    occluder_polygon: np.ndarray | None
    door_polygon: np.ndarray | None


def render_wall(wall: SyntheticWall) -> Render:
    """Render a wall photo with exact areas; an identical wall gives identical image bytes."""
    rng = np.random.default_rng(wall.seed)
    homography = _plane_to_image(wall)
    wall_w, wall_h = wall.wall_w_mm, wall.wall_h_mm
    door = band = None
    if wall.door is not None:
        x, y, w, h = wall.door
        door = (x, y, x + w, y + h)
    if wall.occluder_h_mm > 0:
        band = (0, wall_h - wall.occluder_h_mm, wall_w, wall_h)
    tiles = [
        SynthTile(i, j, _project(homography, plane), plane, cell, full)
        for i, j, plane, cell, full in _layout(wall, door)
    ]
    image = _photograph(wall, homography, tiles, door, band, rng)
    opening = _overlap(door, door) if door is not None else 0.0
    hidden = 0.0
    if band is not None:
        hidden = _overlap(band, band) - (_overlap(band, door) if door is not None else 0.0)
    tiled = wall_w * wall_h - opening
    return Render(
        wall=wall,
        image=image,
        plane_to_image=homography,
        tiles=tiles,
        tiled_area_m2=tiled / 1e6,
        visible_tiled_area_m2=(tiled - hidden) / 1e6,
        hidden_area_m2=hidden / 1e6,
        opening_area_m2=opening / 1e6,
        occluder_polygon=_project(homography, _rect(*band)) if band is not None else None,
        door_polygon=_project(homography, _rect(*door)) if door is not None else None,
    )


def fake_detections(
    render: Render,
    *,
    seed: int = 0,
    erosion_px: float = 1.0,
    jitter_px: float = 0.5,
    dropout: float = 0.0,
    merge_rate: float = 0.0,
    false_positives: int = 0,
) -> list[dict]:
    """Return SAM-like tile masks in ``crop_merge`` detection format, with known failures.

    Each visible tile part (inside the frame, outside the occluder) is eroded at its visible
    edges and traced, with Gaussian contour jitter. ``merge_rate`` fuses full tiles with their
    right neighbour into one mask, ``dropout`` drops masks, ``false_positives`` adds random
    blobs. ``truth`` names the tile (the left one when merged; None for false positives).
    Masks under 25 px are omitted, as SAM's candidate gate in ``crop_merge`` would reject them.
    """
    rng = np.random.default_rng(seed)
    size = tuple(int(v) for v in render.wall.image_size)
    full = {(t.i, t.j): t for t in render.tiles if t.full}
    absorbed, units = set(), []
    for tile in render.tiles:
        draw = rng.random()
        if (tile.i, tile.j) in absorbed:
            continue
        right = full.get((tile.i + 1, tile.j))
        polygon = tile.polygon
        if tile.full and right is not None and draw < merge_rate:
            absorbed.add((right.i, right.j))
            (x0, y0), (x1, y1) = tile.plane_polygon.min(0), right.plane_polygon.max(0)
            polygon = _project(render.plane_to_image, _rect(x0, y0, x1, y1))
        units.append(({"i": tile.i, "j": tile.j}, polygon))
    detections = []
    for truth, polygon in units:
        kept, confidence = rng.random() >= dropout, rng.uniform(0.6, 0.95)
        if not kept:
            continue
        visible = _mask(polygon, size, render.occluder_polygon, erosion_px)
        detection = _detection(
            visible,
            size,
            run_id="synthetic",
            object_id=str(len(detections)),
            confidence=confidence,
            truth=truth,
            rng=rng,
            jitter=jitter_px,
        )
        if detection:
            detections.append(detection)
    angles = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    for _ in range(false_positives):
        centre = rng.uniform((0, 0), size)
        half = rng.uniform(20, 80, 2) / 2
        angle = rng.uniform(0, np.pi)
        ellipse = rng.random() < 0.5
        confidence = rng.uniform(0.5, 0.7)
        if ellipse:
            shape = np.column_stack([np.cos(angles), np.sin(angles)])
        else:
            shape = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], float)
        turn = np.array([[cos(angle), sin(angle)], [-sin(angle), cos(angle)]])
        detection = _detection(
            _mask(shape * half @ turn + centre, size),
            size,
            run_id="synthetic",
            object_id=str(len(detections)),
            confidence=confidence,
            truth=None,
            rng=rng,
            jitter=jitter_px,
        )
        if detection:
            detections.append(detection)
    return detections


def fake_concept(polygon: np.ndarray, label: str, image_size: tuple[int, int]) -> dict:
    """Return one concept mask (door, mirror, ...) from an image polygon, in detection format."""
    size = tuple(int(v) for v in image_size)
    detection = _detection(
        _mask(np.asarray(polygon, np.float64), size),
        size,
        run_id=label,
        object_id="0",
        confidence=0.9,
        truth=None,
    )
    if detection is None:
        raise ValueError("The concept polygon covers too few image pixels")
    return detection


def _layout(wall, door):
    """Yield (i, j, plane polygon, cell, full) for every tile piece inside the wall."""
    g, tile_w, tile_h = wall.grout_mm, wall.tile_w_mm, wall.tile_h_mm
    pitch_x, pitch_y = tile_w + g, tile_h + g
    width, height = wall.wall_w_mm, wall.wall_h_mm
    for j in range(int(height // pitch_y) + 1):
        offset = (j % 2) * pitch_x / 2 if wall.bond == "running" else 0.0
        for i in range(-1, int(width // pitch_x) + 2):
            x0, y0 = i * pitch_x + offset + g / 2, j * pitch_y + g / 2
            tile = (x0, y0, x0 + tile_w, y0 + tile_h)
            clipped = (max(x0, 0), max(y0, 0), min(tile[2], width), min(tile[3], height))
            if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
                continue
            cut = door is not None and _overlap(clipped, door) > 0
            cell = (x0 - g / 2, y0 - g / 2, tile[2] + g / 2, tile[3] + g / 2)
            for piece in _minus(clipped, door) if cut else [_rect(*clipped)]:
                yield i, j, piece, cell, clipped == tile and not cut


def _minus(rect, hole):
    """Return the exact polygons of an axis-aligned rectangle minus another one."""
    xs = np.unique(np.clip([rect[0], hole[0], hole[2], rect[2]], rect[0], rect[2]))
    ys = np.unique(np.clip([rect[1], hole[1], hole[3], rect[3]], rect[1], rect[3]))
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    cut = ((cy > hole[1]) & (cy < hole[3]))[:, None] & ((cx > hole[0]) & (cx < hole[2]))[None, :]
    # Each grid cell becomes 2×2 pixels, so contour pixel p lies on cell edge p//2 + p%2.
    grid = np.kron((~cut).astype(np.uint8), np.ones((2, 2), np.uint8))
    contours, hierarchy = cv2.findContours(grid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if contours and (hierarchy[0, :, 3] >= 0).any():
        raise ValueError("A door strictly inside a single tile is not supported")
    pieces = []
    for contour in contours:
        p = contour[:, 0, :]
        piece = np.column_stack([xs[p[:, 0] // 2 + p[:, 0] % 2], ys[p[:, 1] // 2 + p[:, 1] % 2]])
        piece = piece[np.any(piece != np.roll(piece, 1, axis=0), axis=1)]
        pieces.append(piece[::-1] if _signed_area(piece) < 0 else piece)
    return pieces


def _plane_to_image(wall):
    """Pinhole homography (mm → px) whose wall bounding box spans ``fill``, centred."""
    width, height = wall.image_size
    wall_w, wall_h = wall.wall_w_mm, wall.wall_h_mm
    focal = 0.9 * max(width, height)
    camera = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]])
    yaw, pitch, roll = (radians(a) for a in (wall.yaw_deg, wall.pitch_deg, wall.roll_deg))
    ry = np.array([[cos(yaw), 0, sin(yaw)], [0, 1, 0], [-sin(yaw), 0, cos(yaw)]])
    rx = np.array([[1, 0, 0], [0, cos(pitch), -sin(pitch)], [0, sin(pitch), cos(pitch)]])
    rz = np.array([[cos(roll), -sin(roll), 0], [sin(roll), cos(roll), 0], [0, 0, 1]])
    rotation = rz @ rx @ ry
    corners = _rect(0, 0, wall_w, wall_h)
    centred = rotation @ np.array([-wall_w / 2, -wall_h / 2, 0])

    def homography(distance):
        translation = centred + (0, 0, distance)
        return camera @ np.column_stack([rotation[:, 0], rotation[:, 1], translation])

    def excess(distance):
        span = np.ptp(_project(homography(distance), corners), axis=0)
        return max(span[0] / width, span[1] / height) - wall.fill

    # Corners must stay in front of the camera; the span shrinks monotonically beyond that.
    depth = (corners - (wall_w / 2, wall_h / 2)) @ rotation[2, :2]
    near = max(0.0, -depth.min()) + 1e-3 * max(wall_w, wall_h)
    result = homography(brentq(excess, near, near + 1e4 * max(wall_w, wall_h)))
    projected = _project(result, corners)
    shift = np.array([width, height]) / 2 - (projected.min(0) + projected.max(0)) / 2
    return np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1]]) @ result


def _photograph(wall, homography, tiles, door, band, rng):
    """Draw the plane texture, warp it with 2× supersampling, then gloss, occluder and noise."""
    width, height = wall.image_size
    base = np.array(TILE_COLOURS[rng.integers(len(TILE_COLOURS))], np.float64)
    grout = GROUT_COLOURS[rng.integers(len(GROUT_COLOURS))]
    paint = PAINT_COLOURS[rng.integers(len(PAINT_COLOURS))]
    ppm = min(PX_PER_MM, MAX_TEXTURE_PX / max(wall.wall_w_mm, wall.wall_h_mm))
    texture = np.empty((ceil(wall.wall_h_mm * ppm), ceil(wall.wall_w_mm * ppm), 3), np.uint8)
    texture[:] = grout
    half, drawn = wall.grout_mm / 2, set()
    for tile in tiles:
        if (tile.i, tile.j) in drawn:
            continue
        drawn.add((tile.i, tile.j))
        colour = np.clip(base * rng.uniform(0.94, 1.06), 0, 255).astype(np.uint8)
        x0, y0, x1, y1 = (round(v * ppm) for v in np.add(tile.cell_mm, (half, half, -half, -half)))
        texture[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)] = colour
    if door is not None:
        x0, y0, x1, y1 = (round(v * ppm) for v in door)
        frame = max(1, round(0.05 * (x1 - x0)))
        texture[y0:y1, x0:x1] = WOOD_FRAME
        texture[y0 + frame : y1, x0 + frame : x1 - frame] = WOOD
        knob = (x0 + round(0.85 * (x1 - x0)), y0 + round(0.55 * (y1 - y0)))
        cv2.circle(texture, knob, max(2, round(0.03 * (x1 - x0))), HANDLE, -1, cv2.LINE_AA)
    to_texture = np.array([[ppm, 0, -0.5], [0, ppm, -0.5], [0, 0, 1]])
    to_double = np.array([[2, 0, -0.5], [0, 2, -0.5], [0, 0, 1]])
    double = cv2.warpPerspective(
        texture,
        to_double @ homography @ np.linalg.inv(to_texture),
        (2 * width, 2 * height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=paint,
    )
    image = cv2.resize(double, (width, height), interpolation=cv2.INTER_AREA).astype(np.float32)

    spot = rng.uniform((0.25, 0.2), (0.75, 0.6)) * (wall.wall_w_mm, wall.wall_h_mm)
    spot = _project(homography, [spot])[0]
    sigma = rng.uniform(0.05, 0.12, 2) * max(width, height)
    angle = rng.uniform(0, np.pi)
    if wall.gloss > 0:
        du = np.arange(width, dtype=np.float32)[None, :] + 0.5 - spot[0]
        dv = np.arange(height, dtype=np.float32)[:, None] + 0.5 - spot[1]
        a = (du * cos(angle) + dv * sin(angle)) / sigma[0]
        b = (dv * cos(angle) - du * sin(angle)) / sigma[1]
        surface = _coverage(
            _project(homography, _rect(0, 0, wall.wall_w_mm, wall.wall_h_mm)), image
        )
        if door is not None:
            surface = np.clip(surface - _coverage(_project(homography, _rect(*door)), image), 0, 1)
        weight = wall.gloss * np.exp(-0.5 * (a * a + b * b)) * surface
        image += weight[..., None] * (255 - image)
    if band is not None:
        polygon = _project(homography, _rect(*band))
        top, bottom = polygon[:, 1].min(), polygon[:, 1].max()
        rows = (np.arange(height, dtype=np.float32) + 0.5 - top) / max(bottom - top, 1.0)
        shade = 250 - 36 * np.clip(rows, 0, 1)
        white = shade[:, None, None] * np.array([1.0, 1.0, 0.985], np.float32)
        alpha = _coverage(polygon, image)[..., None]
        image = image * (1 - alpha) + white * alpha
        rim = _coverage(polygon, image, thickness=2)[..., None]
        image = image * (1 - rim) + np.array(RIM, np.float32) * rim
    image += rng.standard_normal(image.shape, dtype=np.float32) * 2.0
    return np.clip(np.rint(image), 0, 255).astype(np.uint8)


def _coverage(polygon, image, thickness=-1):
    """Anti-aliased coverage in [0, 1] of a filled polygon, or of its outline (drawing only)."""
    alpha = np.zeros(image.shape[:2], np.uint8)
    points = [np.round((np.asarray(polygon) - 0.5) * 16).astype(np.int32)]
    if thickness < 0:
        cv2.fillPoly(alpha, points, 255, cv2.LINE_AA, shift=4)
    else:
        cv2.polylines(alpha, points, True, 255, thickness, cv2.LINE_AA, shift=4)
    return alpha.astype(np.float32) / 255


def _mask(polygon, size, occluder=None, erosion=0.0):
    """Return (mask, origin) of the polygon's pixels in the frame minus the occluder, or None.

    The window stops at the frame, where distanceTransform sees no background: erosion acts
    on visible edges only, so a tile cut by the frame keeps its mask up to the border.
    """
    width, height = size
    pad = ceil(erosion) + 1
    x0, y0 = (int(v) - pad for v in np.floor(polygon.min(0)))
    x1, y1 = (int(v) + pad for v in np.ceil(polygon.max(0)))
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width), min(y1, height)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = _inside(polygon, x0, y0, x1 - x0, y1 - y0)
    if occluder is not None:
        mask &= ~_inside(occluder, x0, y0, x1 - x0, y1 - y0)
    mask = mask.astype(np.uint8)
    if erosion > 0:
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        mask = (distance > erosion).astype(np.uint8)
    return mask, (x0, y0)


def _inside(polygon, x0, y0, width, height):
    """Return which window pixels have their centre inside the polygon (even-odd, exact)."""
    start = np.asarray(polygon, np.float64) - (x0, y0)
    end = np.roll(start, -1, axis=0)
    y = np.arange(height) + 0.5
    low, high = np.minimum(start[:, 1], end[:, 1]), np.maximum(start[:, 1], end[:, 1])
    rows, edges = np.nonzero((y[:, None] >= low) & (y[:, None] < high))
    t = (y[rows] - start[edges, 1]) / (end[edges, 1] - start[edges, 1])
    x = start[edges, 0] + t * (end[edges, 0] - start[edges, 0])
    # A crossing flips every pixel whose centre lies at or right of it; odd parity is inside.
    column = np.clip(np.ceil(x - 0.5), 0, width).astype(np.intp)
    flips = np.bincount(rows * (width + 1) + column, minlength=height * (width + 1))
    return np.cumsum(flips.reshape(height, width + 1)[:, :width], axis=1) % 2 == 1


def _detection(visible, size, *, run_id, object_id, confidence, truth, rng=None, jitter=0.0):
    """Build one detection like ``crop_merge.convert_record`` for a full-frame request."""
    if visible is None:
        return None
    mask, (ox, oy) = visible
    ys, xs = np.nonzero(mask)
    if len(xs) < MIN_MASK_PX:
        return None
    width, height = size
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    traced = []
    for contour in contours:
        contour = cv2.approxPolyDP(contour, 0.5, True)
        if len(contour) < 3:
            continue
        points = contour[:, 0, :] + (ox + 0.5, oy + 0.5)
        if jitter > 0:
            points = points + rng.normal(0, jitter, points.shape)
        points = np.clip(points, 0, size)
        traced.append({"points": np.round(points, 3).tolist(), "hole": False, "depth": 0})
    if not traced:
        return None
    _, (side_a, side_b), _ = cv2.minAreaRect(np.concatenate(contours))
    area = float(len(xs))
    box = [
        float(ox + xs.min()),
        float(oy + ys.min()),
        float(ox + xs.max() + 1),
        float(oy + ys.max() + 1),
    ]
    margin = max(2.0, 0.005 * min(width, height))
    edge = bool(
        box[0] <= margin
        or box[1] <= margin
        or box[2] >= width - margin
        or box[3] >= height - margin
    )
    return {
        "id": f"{run_id}:{object_id}",
        "run_id": run_id,
        "object_id": object_id,
        "box": box,
        "contours": traced,
        "confidence": float(confidence),
        "area_px": area,
        "rectangularity": round(min(1.0, area / max(1.0, (side_a + 1) * (side_b + 1))), 6),
        "edge_truncated": edge,
        "crop_boundary": False,
        "image_boundary": edge,
        "candidate": True,
        "input_size": [width, height],
        "crop_box": [0, 0, width, height],
        "source_size": [width, height],
        "truth": truth,
    }


def _project(matrix, points):
    points = np.asarray(points, np.float64)
    mapped = np.column_stack([points, np.ones(len(points))]) @ matrix.T
    return mapped[:, :2] / mapped[:, 2:]


def _rect(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)


def _overlap(a, b):
    """Positive-area overlap of two (x0, y0, x1, y1) rectangles."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _signed_area(points):
    x, y = points.T
    return (x @ np.roll(y, -1) - y @ np.roll(x, -1)) / 2
