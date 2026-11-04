"""Tiled area of one wall in the rectified plane, with exclusions and 1-sigma uncertainty.

Matched lattice tiles count exactly one pitch cell each. Other tile masks (cut tiles, borders,
bands) count when, rectified, they are axis-aligned rectangles next to the matched region.
Small enclosed gaps are completed; larger gaps and anything hidden become not_visible
allowances, never measured area.
"""

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from measure.probe import uncounted_tiles
from schemas.measure import ExcludedRegion

OPENING_CONCEPTS = {"door", "window"}
BLOCKING_ONLY = {"floor"}  # stops acceptance but is not an exclusion of the wall
GROUT_TOLERANCE_MM = 1.0
TILE_TOLERANCE_MM = {"box_label": 0.5, "tape": 1.0, "act": 1.5, "user": 1.5}
MAX_COMPLETED_CELLS = 4
MAX_COMPLETED_MM2 = 0.6e6  # larger unseen holes stay allowances, whatever the tile size
MAX_RASTER = 4000  # plane raster pixels per side
IMAGE_SIDE = 2000  # detections are rasterised at this long side
REACH_MARGIN_MM = 3000  # how far beyond the matched cells tiles and exclusions are considered
EDGE_PX = 1.0  # mask boundary localisation in image pixels
BOOTSTRAP = 64
THICKNESS_CHANGE = 0.06  # across a rectified tile; more means it narrows towards another plane
EDGE_NOISE_PX = 5.0  # thickness change that mask noise and pixel steps alone can produce
JOINT_TOLERANCE = 0.08  # of the tile's size along that axis
RECTANGULARITY_MIN = 0.75
ANGLE_TOLERANCE_DEG = 10
GAP_CELLS = 1.6  # missed tiles bridged along rows and columns; doors are wider
EXTEND_CELLS = 2  # at most this many missed edge tiles are inferred per row or column end
OTHER_SURFACE = "other_surface"  # tile-shaped masks whose colour matches no lattice tile
BRIGHTNESS_RATIO = 0.5  # |ln(L / L_tile)| beyond this: shadow on the same tile stays within it
CHROMA_DISTANCE = 15  # Lab a/b units beyond this


def tile_tolerance_mm(source):
    return TILE_TOLERANCE_MM[source]


@dataclass
class AreaResult:
    tiled_area_m2: float
    full_tiles: int
    partial_tiles_equiv: float
    completed_cells: int
    undetected_m2: float
    border_fraction: float
    sigma_random_m2: float
    sigma_system_m2: float
    excluded: list[ExcludedRegion] = field(default_factory=list)
    excluded_px: dict[str, list[np.ndarray]] = field(default_factory=dict)  # label -> outlines
    region_px: list[np.ndarray] = field(default_factory=list)  # outlines, source image px
    completed_px: list[np.ndarray] = field(default_factory=list)
    partial_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)  # matched tiles under an exclusion
    uncounted_cells: int = 0  # ring cells that look like tiles in the photo but were not counted
    probed_cells: int = 0
    uncounted_m2: float = 0.0  # rough upper estimate of the area those cells hold
    border_gap_tiles: float | None = None  # counted outline's distance from the photo edge

    @property
    def conflict_tiles(self):
        return len(self.conflict_ids)


def measure_area(fit, detections, image_size, tile, concepts=None, *, seed=0, image=None):
    concepts = concepts or {}
    px, py = fit.pitch
    cell_area = px * py
    plane = _Plane(fit, image_size, concepts, detections)
    labels = plane.labels([d["contours"] for d in detections])
    erosion = _erosion_mm(fit, detections, labels, plane)
    cells = plane.cells(fit, fit.tiles)
    # Quantisation of whole cells is corrected analytically before exclusions clip them.
    correction = len(fit.tiles) * cell_area - cells.sum() * plane.res**2
    # Matched tiles are seen. A detection lying mostly on them is not a door, mirror or floor
    # there (a glass screen read as a door, a floor mask spilling up the wall): it is dropped.
    masks, conflict_ids = {}, set()
    for concept, found in concepts.items():
        union = np.zeros(plane.shape, bool)
        for detection in found:
            mask = plane.mask([detection]) & plane.frame
            if not mask.any():
                continue
            if (mask & cells).sum() >= 0.5 * mask.sum():
                if concept not in BLOCKING_ONLY:
                    conflict_ids.update(plane.covered_tiles(fit, mask))
                continue
            union |= mask
        if union.any():
            masks[concept] = union
    blocked = np.zeros(plane.shape, bool)
    exclusions = np.zeros(plane.shape, bool)
    for concept, mask in masks.items():
        blocked |= mask
        if concept not in BLOCKING_ONLY:
            exclusions |= mask
    # A kept mask still covering most of a matched cell is lifted there; covering less, an
    # exclusion clips the cell (an L-shaped tile at a door corner). The floor never clips.
    conflict_ids.update(plane.covered_tiles(fit, exclusions))
    # Wherever SAM saw a tile, a door/window/mirror/bathtub outline is wrong there (a casing or
    # a glass screen drawn over tiles): lift it from every detected tile mask. The floor stays.
    grow = max(1, int(round((erosion + tile.grout_mm / 2) / plane.res)) + 1)
    kernel = np.ones((2 * grow + 1,) * 2, np.uint8)
    tiles_seen = cv2.dilate((labels > 0).astype(np.uint8), kernel) > 0
    floor = blocked & ~exclusions
    exclusions &= ~tiles_seen
    blocked = exclusions | floor
    masks = {c: (m if c in BLOCKING_ONLY else m & ~tiles_seen) for c, m in masks.items()}
    seen = np.zeros(plane.shape, bool)
    for tile_ in fit.tiles:
        box = plane.cell_box(fit, tile_)
        if box is not None and blocked[box].mean() >= 0.5:
            seen[box] = True
    blocked &= ~seen
    exclusions &= ~seen
    masks = {c: m & ~seen for c, m in masks.items()}
    cells &= ~exclusions
    accepted, partial_ids = _accept(
        fit, detections, labels, cells, plane, blocked, erosion, exclusions
    )
    others = _other_surfaces(fit, detections, image, partial_ids, plane) if image else []
    if others:
        other = plane.mask(others) & plane.frame & ~cells
        masks[OTHER_SURFACE] = other
        blocked |= other
        exclusions |= other
        accepted, partial_ids = _accept(
            fit, detections, labels, cells, plane, blocked, erosion, exclusions
        )
    grow = max(0, int(round((erosion + tile.grout_mm / 2) / plane.res)))
    if grow:
        accepted = cv2.dilate(accepted.astype(np.uint8), np.ones((2 * grow + 1,) * 2, np.uint8))
    region = (cells | accepted.astype(bool)) & plane.frame
    bridged = _close_gaps(region, fit, plane) & plane.frame & ~blocked & ~region
    patches, _ = ndimage.label(bridged)
    sizes = np.bincount(patches.ravel()) * plane.res**2
    bridged &= (sizes <= MAX_COMPLETED_MM2)[patches]  # a larger unseen patch stays a hole
    region |= bridged
    filled = ndimage.binary_fill_holes(region)
    holes, count = ndimage.label(filled & ~region)
    completed, undetected = np.zeros_like(region), np.zeros_like(region)
    for index, hole in enumerate(ndimage.find_objects(holes), 1):
        part = holes[hole] == index
        if (part & blocked[hole]).sum() > 0.5 * part.sum():
            continue  # a mirror or window inside the tiling: reported as an exclusion
        size = part.sum() * plane.res**2
        if size <= min(MAX_COMPLETED_CELLS * cell_area * 1.05, MAX_COMPLETED_MM2):
            completed[hole] |= part
        else:
            undetected[hole] |= part
    region |= completed
    extended = _extend_to_neighbours(region, plane.frame & ~blocked & ~undetected, fit, plane)
    region |= extended
    undetected |= _hull_gaps(region, blocked | undetected, plane, cell_area)
    completed_cells = int(round(completed.sum() * plane.res**2 / cell_area))
    completed |= bridged | extended
    full = len(fit.tiles)
    area_mm2 = region.sum() * plane.res**2 + correction
    excluded, excluded_px, undetected_m2 = _exclusions(region, undetected, masks, plane)
    uncounted, probed, uncounted_mm2 = (
        uncounted_tiles(image, fit, plane, region, blocked) if image is not None else (0, 0, 0.0)
    )
    region_px = plane.outlines(region)
    points = np.concatenate(region_px) if region_px else np.zeros((0, 2))
    points = points[np.isfinite(points).all(axis=1)]
    border_gap = None
    if len(points):
        width, height = image_size
        gaps = np.minimum.reduce(
            [points[:, 0], points[:, 1], width - points[:, 0], height - points[:, 1]]
        )
        border_gap = float(gaps.min() / max(fit.tile_px, 1e-9))
    border = region & ~cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    inner = cv2.erode(plane.frame.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    border_fraction = float((border & ~inner).sum() / max(1, border.sum()))
    sigma_random = _sigma_random(fit, region & ~cells, region, erosion, plane, seed)
    # Completed holes, bridged gaps and extended row ends are inferred, not seen: half their
    # area is one sigma (the tiles may be there, or an untiled niche may be).
    sigma_random = math.hypot(sigma_random, 0.5 * completed.sum() * plane.res**2)
    delta = math.hypot(tile_tolerance_mm(tile.source), GROUT_TOLERANCE_MM)
    area_m2 = area_mm2 / 1e6
    return AreaResult(
        tiled_area_m2=area_m2,
        full_tiles=full,
        partial_tiles_equiv=area_mm2 / cell_area - full,
        completed_cells=completed_cells,
        undetected_m2=undetected_m2,
        border_fraction=border_fraction,
        sigma_random_m2=sigma_random / 1e6,
        sigma_system_m2=area_m2 * (delta / px + delta / py),
        excluded=excluded,
        excluded_px=excluded_px,
        region_px=region_px,
        uncounted_cells=uncounted,
        probed_cells=probed,
        uncounted_m2=uncounted_mm2 / 1e6,
        border_gap_tiles=border_gap,
        completed_px=plane.outlines(completed),
        partial_ids=partial_ids,
        conflict_ids=sorted(conflict_ids),
    )


class _Plane:
    """A raster of the wall plane around the matched cells, and image→raster warping."""

    def __init__(self, fit, image_size, concepts, detections=()):
        px, py = fit.pitch
        rects = np.array([fit.cell_rect(t.i, t.j) for t in fit.tiles])
        low, high = rects[:, :2].min(axis=0), rects[:, 2:].max(axis=0)
        lo, hi = low - 2 * np.array([px, py]), high + 2 * np.array([px, py])
        # Tile masks reachable through accepted neighbours, and exclusions, widen the raster.
        others = [d for found in concepts.values() for d in found] + list(detections)
        if others:
            points = fit.to_plane(np.concatenate([_outer_points(d["contours"]) for d in others]))
            points = points[np.isfinite(points).all(axis=1)]
            if len(points):
                lo = np.minimum(lo, np.maximum(points.min(axis=0), low - REACH_MARGIN_MM))
                hi = np.maximum(hi, np.minimum(points.max(axis=0), high + REACH_MARGIN_MM))
        self.res = max(float(np.clip(min(px, py) / 60, 1, 5)), float((hi - lo).max() / MAX_RASTER))
        self.lo = lo
        self.shape = (int(math.ceil((hi[1] - lo[1]) / self.res)) + 1,
                      int(math.ceil((hi[0] - lo[0]) / self.res)) + 1)  # fmt: skip
        self.scale = min(1.0, IMAGE_SIDE / max(image_size))
        self.small = (round(image_size[0] * self.scale), round(image_size[1] * self.scale))
        to_raster = np.array(
            [[1 / self.res, 0, -lo[0] / self.res], [0, 1 / self.res, -lo[1] / self.res], [0, 0, 1]]
        )
        self.H = fit.H
        self.M = to_raster @ fit.H @ np.diag([1 / self.scale, 1 / self.scale, 1.0])
        # Which plane axis runs up the wall: the image vertical, rectified at the tiles.
        middle = np.median([t.center for t in fit.tiles], axis=0)
        up = np.diff(fit.to_plane([middle, middle + (0, 50)]), axis=0)[0]
        self.vertical_axis = 0 if abs(up[0]) > abs(up[1]) else 1
        self.frame = self.warp(np.ones((self.small[1], self.small[0]), np.float32)) > 0

    def warp(self, image):
        return cv2.warpPerspective(
            image, self.M, (self.shape[1], self.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0
        )

    def covered_tiles(self, fit, mask):
        """Ids of matched tiles whose cell lies at least half inside mask."""
        boxes = ((tile.det_id, self.cell_box(fit, tile)) for tile in fit.tiles)
        return [i for i, box in boxes if box is not None and mask[box].mean() >= 0.5]

    def cell_box(self, fit, tile):
        """Raster slices of tile (i, j)'s cell, or None when it lies outside the raster."""
        x0, y0, x1, y1 = fit.cell_rect(tile.i, tile.j)
        c0, c1 = (max(0, round((x - self.lo[0]) / self.res)) for x in (x0, x1))
        r0, r1 = (max(0, round((y - self.lo[1]) / self.res)) for y in (y0, y1))
        c1, r1 = min(c1, self.shape[1]), min(r1, self.shape[0])
        return (slice(r0, r1), slice(c0, c1)) if r1 > r0 and c1 > c0 else None

    def cells(self, fit, tiles):
        mask = np.zeros(self.shape, bool)
        for tile in tiles:
            x0, y0, x1, y1 = fit.cell_rect(tile.i, tile.j)
            c0, c1 = (round((x - self.lo[0]) / self.res) for x in (x0, x1))
            r0, r1 = (round((y - self.lo[1]) / self.res) for y in (y0, y1))
            mask[max(r0, 0) : max(r1, 0), max(c0, 0) : max(c1, 0)] = True
        return mask

    def labels(self, contour_sets):
        """Rectified label raster: pixel value k marks detection k-1 (outer contours only)."""
        image = np.zeros((self.small[1], self.small[0]), np.int32)
        for k, contours in enumerate(contour_sets, 1):
            polygons = [
                np.round(np.asarray(c["points"]) * self.scale).astype(np.int32)
                for c in contours
                if not c.get("hole") and len(c["points"]) >= 3
            ]
            if polygons:
                cv2.fillPoly(image, polygons, k)
        return self.warp(image.astype(np.float32)).astype(np.int64)

    def mask(self, detections):
        return self.labels([d["contours"] for d in detections]) > 0

    def outlines(self, mask):
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        inverse = np.linalg.inv(self.H)
        result = []
        for contour in contours:
            points = contour.reshape(-1, 2) * self.res + self.lo
            image = cv2.perspectiveTransform(points.reshape(-1, 1, 2).astype(np.float64), inverse)
            result.append(image.reshape(-1, 2))
        return result


def _outer_points(contours):
    return np.concatenate(
        [np.asarray(c["points"], np.float64) for c in contours if not c.get("hole")]
        or [np.zeros((0, 2))]
    )


def _erosion_mm(fit, detections, labels, plane):
    """Median inset of matched tile masks relative to the nominal tile, per side (mm)."""
    cw, ch = fit.cell
    index = {d["id"]: k for k, d in enumerate(detections, 1)}
    counts = np.bincount(labels.ravel(), minlength=len(detections) + 1)
    insets = []
    for tile in fit.tiles:
        area = counts[index[tile.det_id]] * plane.res**2
        discriminant = (cw + ch) ** 2 - 4 * (cw * ch - area)
        if area > 0 and discriminant >= 0:
            insets.append(((cw + ch) - math.sqrt(discriminant)) / 4)
    if not insets:
        return 0.0
    return float(np.clip(np.median(insets), 0, 0.05 * min(cw, ch)))


def _other_surfaces(fit, detections, image, accepted_ids, plane):
    """Accepted non-lattice masks unlike every lattice tile: a panel, a column of other tile.

    They are not this tile, but they may be tiled: they become a not_visible allowance, so a
    decor band can never turn into an accusation. Comparing with every lattice tile, not their
    average, keeps mixed-colour walls and lighting falloff across the wall within tolerance.
    """
    lab = cv2.cvtColor(
        np.asarray(image.convert("RGB").resize(plane.small, Image.Resampling.BILINEAR)),
        cv2.COLOR_RGB2LAB,
    ).astype(np.float64)
    by_id = {d["id"]: d for d in detections}
    colours = [_colour(by_id[t.det_id], lab, plane.scale) for t in fit.tiles]
    reference = np.array([c for c in colours if c is not None])
    if not len(reference):
        return []
    found = []
    for detection_id in accepted_ids:
        colour = _colour(by_id[detection_id], lab, plane.scale)
        if colour is None:
            continue
        brightness = np.abs(np.log((colour[0] + 1) / (reference[:, 0] + 1)))
        chroma = np.hypot(*(colour[1:] - reference[:, 1:]).T)
        if ((brightness > BRIGHTNESS_RATIO) | (chroma > CHROMA_DISTANCE)).all():
            found.append(by_id[detection_id])
    return found


def _colour(detection, lab, scale):
    """Median Lab colour inside a mask, away from its edges and the joints; None if too small."""
    polygons = [
        np.round(np.asarray(c["points"]) * scale).astype(np.int32)
        for c in detection["contours"]
        if not c.get("hole") and len(c["points"]) >= 3
    ]
    if not polygons:
        return None
    x0, y0 = np.min([p.min(axis=0) for p in polygons], axis=0).clip(0)
    x1, y1 = np.max([p.max(axis=0) for p in polygons], axis=0) + 1
    crop = lab[y0:y1, x0:x1]
    if not crop.size:
        return None
    mask = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(mask, [p - (x0, y0) for p in polygons], 1)
    inner = cv2.erode(mask, np.ones((5, 5), np.uint8)) > 0
    return np.median(crop[inner], axis=0) if inner.any() else None


def _accept(fit, detections, labels, cells, plane, blocked, erosion=0.0, exclusions=None):
    """Non-lattice masks that are tiles of this wall: one tile or less, square-edged in the
    plane and lying on this wall's joint lines.

    Tiles of a neighbouring wall or the floor rectify to trapezoids off the joint lines. Masks
    on the joint lines of both axes count wherever they are; masks on one row band (cut tiles)
    count when they connect to the matched cells through other accepted tiles, so a strip of
    cut tiles beside a door counts.
    """
    px, py = fit.pitch
    reach = max(1, int(round(max(px, py) / plane.res)))
    kernel = np.ones((2 * reach + 1,) * 2, np.uint8)
    matched = {t.det_id for t in fit.tiles}
    # Next to the matched cells only door/window/mirror masks block: a floor mask spilling up
    # the wall must not remove the wall's cut bottom row.
    beside = cv2.dilate(cells.astype(np.uint8), kernel) > 0
    exclusions = blocked if exclusions is None else exclusions
    candidates = []
    for k, box in enumerate(ndimage.find_objects(labels), 1):
        detection = detections[k - 1] if k <= len(detections) else None
        if box is None or detection is None or detection["id"] in matched:
            continue
        part = labels[box] == k
        pixels = int(part.sum())
        if pixels * plane.res**2 < 0.02 * px * py:
            continue
        near = (part & beside[box]).sum() >= 0.5 * pixels
        if (part & (exclusions if near else blocked)[box]).sum() >= 0.5 * pixels:
            continue  # floor, bathtub apron, door: tile-like but not this wall
        level = _joint_level(fit, box, part, plane, erosion)
        if level and _square_edged(part, pixels):
            candidates.append((detection["id"], box, part, pixels, level))
    accepted, ids = np.zeros(plane.shape, bool), []
    grown = cells.copy()
    for detection_id, box, part, _, level in candidates:
        if level == 2:
            accepted[box] |= part
            grown[box] |= part
            ids.append(detection_id)
    candidates = [c for c in candidates if c[0] not in set(ids)]
    while candidates:
        near = cv2.dilate(grown.astype(np.uint8), kernel) > 0
        joined = [c for c in candidates if (c[2] & near[c[1]]).sum() >= 0.5 * c[3]]
        if not joined:
            break
        for detection_id, box, part, _, _ in joined:
            accepted[box] |= part
            grown[box] |= part
            ids.append(detection_id)
        candidates = [c for c in candidates if c[0] not in set(ids)]
    return accepted, ids


def _square_edged(part, pixels):
    """A filled, axis-aligned rectangle in the plane: not a trapezoid from another plane.

    A tile of a neighbouring wall or the floor, rectified with this wall's homography, narrows
    towards its vanishing point: its thickness changes across it by about tile width over
    vanishing distance (~10 % for a 300 mm tile), even near eye level where its edges look flat.
    """
    points = np.column_stack(np.nonzero(part)[::-1]).astype(np.float32)
    (_, _), (w, h), angle = cv2.minAreaRect(points)
    if pixels / max(1.0, (w + 1) * (h + 1)) < RECTANGULARITY_MIN:
        return False
    if min(angle % 90, 90 - angle % 90) > ANGLE_TOLERANCE_DEG:
        return False
    for mask in (part, part.T):  # thickness across columns, then across rows
        columns = np.flatnonzero(mask.any(axis=0))
        if len(columns) < 8:
            continue
        inner = columns[int(0.15 * len(columns)) : int(0.85 * len(columns)) + 1]
        thickness = mask[:, inner].sum(axis=0).astype(np.float64)
        typical = float(np.median(thickness))
        change = abs(np.polyfit(inner, thickness, 1)[0]) * (columns[-1] - columns[0] + 1)
        if change > max(EDGE_NOISE_PX, THICKNESS_CHANGE * typical):
            return False
    return True


def _joint_level(fit, box, part, plane, erosion):
    """How a mask of at most one tile sits on this wall's joint lines, in the wall's directions.

    2: a full tile row and a column edge (a whole or end-cut tile); 1: a full tile row (cut by a
    door or corner) or a row edge plus a column edge (a corner cut); 0: anything else. A full
    tile column alone is not enough: the floor and ceiling continue the wall's columns.
    """
    (px, py), (cw, ch) = fit.pitch, fit.cell
    rows, cols = np.nonzero(part)
    x0 = plane.lo[0] + (box[1].start + cols.min()) * plane.res
    x1 = plane.lo[0] + (box[1].start + cols.max() + 1) * plane.res
    y0 = plane.lo[1] + (box[0].start + rows.min()) * plane.res
    y1 = plane.lo[1] + (box[0].start + rows.max() + 1) * plane.res
    if x1 - x0 > 1.1 * px or y1 - y0 > 1.1 * py:
        return 0
    # Per axis: the lattice is extrapolated beyond the matched tiles, so a long tile's ends can
    # sit a few percent of its length off the joint.
    tolerance_x = max(3 * plane.res, JOINT_TOLERANCE * cw)
    tolerance_y = max(3 * plane.res, JOINT_TOLERANCE * ch)
    j = round((y0 + y1) / 2 / py)
    band = (
        abs(y0 - (j * py - ch / 2 + erosion)) <= tolerance_y,
        abs(y1 - (j * py + ch / 2 - erosion)) <= tolerance_y,
    )
    across = (False, False)
    for offset in _row_offsets(fit, j):
        left = (x0 - erosion + cw / 2 - offset) / px
        right = (x1 + erosion - cw / 2 - offset) / px
        aligned = (
            abs(left - round(left)) * px <= tolerance_x,
            abs(right - round(right)) * px <= tolerance_x,
        )
        across = tuple(a or b for a, b in zip(across, aligned, strict=True))
    # Lattice rows run along plane x; the wall's horizontal joints are lines of constant plane
    # y when plane y runs up the wall, otherwise lines of constant plane x.
    if plane.vertical_axis == 1:
        horizontal, vertical, low, high, axis = band, across, y0, y1, 1
    else:
        horizontal, vertical, low, high, axis = across, band, x0, x1, 0
    if all(horizontal):
        return 2 if any(vertical) else 1
    if not (any(horizontal) and any(vertical)):
        return 0
    # A cut row beyond the matched rows shares its joint with them: the aligned edge faces the
    # lattice. A floor sliver at the junction meets a joint line, if at all, on its far side.
    rects = np.array([fit.cell_rect(t.i, t.j) for t in fit.tiles])
    first, last = rects[:, axis].min(), rects[:, axis + 2].max()
    slack = 0.25 * fit.pitch[axis]
    if high <= first + slack:
        return 1 if horizontal[1] else 0
    if low >= last - slack:
        return 1 if horizontal[0] else 0
    return 1


def _extend_to_neighbours(region, allowed, fit, plane):
    """Extend tile rows and columns cut short by missed edge tiles to their neighbours' extent.

    Tiled walls are rectangular apart from openings: a row ending one tile before both its
    neighbours most likely lost an edge tile. At most EXTEND_CELLS tiles are added per end,
    never into exclusions or outside the photo.
    """
    added = np.zeros_like(region)
    for axis in (0, 1):  # 0: rows along plane x (bands in y); 1: columns (bands in x)
        pitch = fit.pitch[1 - axis]
        across = fit.pitch[axis]
        limit = int(round(EXTEND_CELLS * across / plane.res))
        origin = plane.lo[1 - axis]
        length = region.shape[axis]
        first = math.floor((origin + pitch / 2) / pitch) - 1
        last = math.ceil((origin + length * plane.res + pitch / 2) / pitch) + 1
        bands, extents = [], []
        for k in range(first, last + 1):
            r0 = max(0, round((k * pitch - pitch / 2 - origin) / plane.res))
            r1 = min(length, round((k * pitch + pitch / 2 - origin) / plane.res))
            if r1 <= r0:
                continue
            slab = region[r0:r1] if axis == 0 else region[:, r0:r1].T
            covered = np.flatnonzero(slab.mean(axis=0) >= 0.3)
            bands.append((r0, r1))
            extents.append((covered[0], covered[-1]) if len(covered) else None)
        for index, ((r0, r1), own) in enumerate(zip(bands, extents, strict=True)):
            window = extents[max(0, index - 2) : index] + extents[index + 1 : index + 3]
            neighbours = [e for e in window if e is not None]
            if own is None or len(neighbours) < 2:
                continue
            # The median of up to four neighbours: one stray mask cannot drag a row outward.
            low = max(int(np.median([e[0] for e in neighbours])), own[0] - limit)
            high = min(int(np.median([e[1] for e in neighbours])), own[1] + limit)
            if own[1] - own[0] < 0.5 * max(e[1] - e[0] for e in neighbours):
                continue
            # Only the part of the band that already holds tiles: bands straddling the wall's
            # edge must not paint beyond it.
            if axis == 0:
                inside = region[r0:r1].any(axis=1)[:, None]
            else:
                inside = region[:, r0:r1].any(axis=0)[None, :]
            for a, b in ((low, own[0]), (own[1] + 1, high + 1)):
                if b <= a:
                    continue
                if axis == 0:
                    fill = allowed[r0:r1, a:b] & ~region[r0:r1, a:b] & inside
                    added[r0:r1, a:b] |= fill
                else:
                    fill = allowed[a:b, r0:r1] & ~region[a:b, r0:r1] & inside
                    added[a:b, r0:r1] |= fill
    return added


def _hull_gaps(region, explained, plane, cell_area):
    """Unexplained area inside the counted outline: missed tiles we cannot see the edge of.

    Openings and occluders are explained elsewhere; what remains inside the convex hull of the
    counted region is reported as undetected rather than silently left out.
    """
    points = np.column_stack(np.nonzero(region)[::-1]).astype(np.int32)
    if len(points) < 3:
        return np.zeros_like(region)
    hull = np.zeros(region.shape, np.uint8)
    cv2.fillPoly(hull, [cv2.convexHull(points)], 1)
    gaps = hull.astype(bool) & ~region & ~explained & plane.frame
    size = max(3, int(round(0.3 * math.sqrt(cell_area) / plane.res)))
    opened = cv2.morphologyEx(
        gaps.astype(np.uint8), cv2.MORPH_OPEN, np.ones((size, size), np.uint8)
    )
    return opened.astype(bool)


def _row_offsets(fit, j):
    """Candidate column offsets for row j: its own, and the one rows of its parity agree on.

    A row holding only a few matched tiles (beside a door) can carry a poor offset of its own.
    """
    px = fit.pitch[0]
    candidates = [fit.row_offsets[j]] if j in fit.row_offsets else []
    same = [o for row, o in fit.row_offsets.items() if row % 2 == j % 2]
    if same:
        angles = 2 * np.pi * np.asarray(same) / px
        if np.hypot(np.sin(angles).mean(), np.cos(angles).mean()) >= 0.95:  # a regular bond
            mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
            candidates.append(float(mean / (2 * np.pi) * px % px))
    return candidates


def _close_gaps(region, fit, plane):
    """Fill gaps shorter than GAP_CELLS along tile rows and columns (missed tiles at edges)."""
    px, py = fit.pitch
    across = max(3, int(round(GAP_CELLS * px / plane.res)) | 1)
    down = max(3, int(round(GAP_CELLS * py / plane.res)) | 1)
    mask = region.astype(np.uint8)
    rows = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, across), np.uint8))
    columns = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((down, 1), np.uint8))
    return (rows | columns).astype(bool)


def _exclusions(region, undetected, masks, plane):
    rows, cols = np.nonzero(region)
    claimed = region.copy()
    excluded, outlines = [], {}
    if len(rows):
        box = np.zeros_like(region)
        box[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1] = True
        band = np.zeros_like(region)
        if plane.vertical_axis == 1:
            band[:, cols.min() : cols.max() + 1] = True
        else:
            band[rows.min() : rows.max() + 1, :] = True
        for concept, mask in masks.items():
            if concept in BLOCKING_ONLY:
                continue
            opening = concept in OPENING_CONCEPTS
            # Other surfaces may lie beyond the counted outline and still be billed as tiling.
            reach = True if concept == OTHER_SURFACE else box if opening else band
            part = mask & reach & ~claimed
            claimed |= part
            if part.any():
                outlines[concept] = plane.outlines(part)
                excluded.append(
                    ExcludedRegion(
                        label=concept,
                        area_m2=float(part.sum() * plane.res**2 / 1e6),
                        reason="opening" if opening else "not_visible",
                    )
                )
    rest = undetected & ~claimed
    undetected_m2 = float(rest.sum() * plane.res**2 / 1e6)
    if undetected_m2 > 0:
        outlines["undetected"] = plane.outlines(rest)
        excluded.append(
            ExcludedRegion(label="undetected", area_m2=undetected_m2, reason="not_visible")
        )
    return excluded, outlines, undetected_m2


def _sigma_random(fit, observed, region, erosion, plane, seed):
    """Homography bootstrap over matched tiles for image-derived area, plus edge localisation.

    Lattice cells have exact area; only partial tiles and completed gaps are mapped from image
    observations, so only they move with the homography.
    """
    sigma_h = 0.0
    contours, hierarchy = cv2.findContours(
        observed.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if contours and len(fit.tiles) >= 8:
        inverse = np.linalg.inv(fit.H)
        images = [
            cv2.perspectiveTransform(
                (c.reshape(-1, 1, 2) * plane.res + plane.lo).astype(np.float64), inverse
            )
            for c in contours
        ]
        signs = [-1.0 if h[3] >= 0 else 1.0 for h in hierarchy[0]]
        centers = np.array([t.center for t in fit.tiles], np.float64)
        targets = np.array(
            [[t.i * fit.pitch[0] + fit.row_offsets.get(t.j, 0.0), t.j * fit.pitch[1]] for t in
             fit.tiles]
        )  # fmt: skip
        rng = np.random.default_rng(seed)
        areas = []
        for _ in range(BOOTSTRAP):
            pick = rng.integers(0, len(centers), len(centers))
            inverse_b, _ = cv2.findHomography(targets[pick], centers[pick], 0)
            if inverse_b is None or abs(np.linalg.det(inverse_b)) < 1e-12:
                continue
            H_b = np.linalg.inv(inverse_b)
            total = 0.0
            for image, sign in zip(images, signs, strict=True):
                points = cv2.perspectiveTransform(image, H_b).reshape(-1, 2)
                if np.isfinite(points).all():
                    x, y = points.T
                    total += sign * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2
            areas.append(total)
        if len(areas) > 1:
            sigma_h = float(np.std(areas))
    perimeter = (
        sum(
            cv2.arcLength(c, True)
            for c in cv2.findContours(
                region.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
            )[0]
        )
        * plane.res
    )
    mm_per_px = math.sqrt(fit.cell[0] * fit.cell[1]) / max(fit.tile_px, 1e-9)
    sigma_edge = perimeter * (EDGE_PX * mm_per_px + erosion / 2)
    return math.hypot(sigma_h, sigma_edge)
