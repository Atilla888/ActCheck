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
from scipy import ndimage

from schemas.measure import ExcludedRegion

OPENING_CONCEPTS = {"door", "window"}
BLOCKING_ONLY = {"floor"}  # stops acceptance but is not an exclusion of the wall
GROUT_TOLERANCE_MM = 1.0
TILE_TOLERANCE_MM = {"box_label": 0.5, "tape": 1.0, "act": 1.5, "user": 1.5}
MAX_COMPLETED_CELLS = 4
MAX_RASTER = 4000  # plane raster pixels per side
IMAGE_SIDE = 2000  # detections are rasterised at this long side
CONCEPT_MARGIN_MM = 3000  # how far beyond the matched cells exclusions are considered
EDGE_PX = 1.0  # mask boundary localisation in image pixels
BOOTSTRAP = 64
MAX_ACCEPTED_CELLS = 4  # larger rectified masks are walls, mirrors or merged blobs
RECTANGULARITY_MIN = 0.75
ANGLE_TOLERANCE_DEG = 10
GAP_CELLS = 1.6  # missed tiles bridged along rows and columns; doors are wider


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
    blocked_ids: list[str] = field(default_factory=list)  # lattice tiles inside floor/door/...


def measure_area(fit, detections, image_size, tile, concepts=None, *, seed=0):
    concepts = concepts or {}
    px, py = fit.pitch
    cell_area = px * py
    plane = _Plane(fit, image_size, concepts)
    labels = plane.labels([d["contours"] for d in detections])
    erosion = _erosion_mm(fit, detections, labels, plane)
    masks = {c: plane.mask(found) & plane.frame for c, found in concepts.items() if found}
    blocked = np.zeros(plane.shape, bool)
    for mask in masks.values():
        blocked |= mask
    kept, blocked_ids = [], []
    for tile_ in fit.tiles:
        (blocked_ids if plane.blocked_at(fit, tile_, blocked) else kept).append(tile_)
    cells = plane.cells(fit, kept)
    accepted, partial_ids = _accept(fit, detections, labels, cells, plane, blocked)
    grow = max(0, int(round((erosion + tile.grout_mm / 2) / plane.res)))
    if grow:
        accepted = cv2.dilate(accepted.astype(np.uint8), np.ones((2 * grow + 1,) * 2, np.uint8))
    region = (cells | accepted.astype(bool)) & plane.frame
    bridged = _close_gaps(region, fit, plane) & plane.frame & ~blocked & ~region
    region |= bridged
    filled = ndimage.binary_fill_holes(region)
    holes, count = ndimage.label(filled & ~region)
    completed, undetected = np.zeros_like(region), np.zeros_like(region)
    for index, hole in enumerate(ndimage.find_objects(holes), 1):
        part = holes[hole] == index
        if (part & blocked[hole]).sum() > 0.5 * part.sum():
            continue  # a mirror or window inside the tiling: reported as an exclusion
        if part.sum() * plane.res**2 <= MAX_COMPLETED_CELLS * cell_area * 1.05:
            completed[hole] |= part
        else:
            undetected[hole] |= part
    region |= completed
    completed_cells = int(round(completed.sum() * plane.res**2 / cell_area))
    completed |= bridged
    full = len(kept)
    area_mm2 = region.sum() * plane.res**2 + (full * cell_area - cells.sum() * plane.res**2)
    excluded, excluded_px, undetected_m2 = _exclusions(region, undetected, masks, plane)
    border = region & ~cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    inner = cv2.erode(plane.frame.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    border_fraction = float((border & ~inner).sum() / max(1, border.sum()))
    sigma_random = _sigma_random(fit, region & ~cells, region, erosion, plane, seed)
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
        region_px=plane.outlines(region),
        completed_px=plane.outlines(completed),
        partial_ids=partial_ids,
        blocked_ids=[t.det_id for t in blocked_ids],
    )


class _Plane:
    """A raster of the wall plane around the matched cells, and image→raster warping."""

    def __init__(self, fit, image_size, concepts):
        px, py = fit.pitch
        rects = np.array([fit.cell_rect(t.i, t.j) for t in fit.tiles])
        low, high = rects[:, :2].min(axis=0), rects[:, 2:].max(axis=0)
        self.cells_low, self.cells_high = low, high
        lo, hi = low - 2 * np.array([px, py]), high + 2 * np.array([px, py])
        for found in concepts.values():
            for detection in found:
                points = fit.to_plane(_outer_points(detection["contours"]))
                points = points[np.isfinite(points).all(axis=1)]
                if len(points):
                    lo = np.minimum(lo, np.maximum(points.min(axis=0), low - CONCEPT_MARGIN_MM))
                    hi = np.maximum(hi, np.minimum(points.max(axis=0), high + CONCEPT_MARGIN_MM))
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

    def blocked_at(self, fit, tile, blocked):
        """True when the tile's cell centre lies in a floor, door, mirror or similar mask."""
        x0, y0, x1, y1 = fit.cell_rect(tile.i, tile.j)
        col = int(round(((x0 + x1) / 2 - self.lo[0]) / self.res))
        row = int(round(((y0 + y1) / 2 - self.lo[1]) / self.res))
        inside = 0 <= row < self.shape[0] and 0 <= col < self.shape[1]
        return bool(inside and blocked[row, col])

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


def _accept(fit, detections, labels, cells, plane, blocked):
    """Non-lattice masks that look like coplanar tiles: rectified, aligned and connected.

    Acceptance grows outward from the matched cells through accepted tiles, so a strip of cut
    tiles beside a door counts even when it is several tiles away from the nearest lattice cell.
    """
    px, py = fit.pitch
    reach = max(1, int(round(max(px, py) / plane.res)))
    kernel = np.ones((2 * reach + 1,) * 2, np.uint8)
    matched = {t.det_id for t in fit.tiles}
    candidates = []
    for k, box in enumerate(ndimage.find_objects(labels), 1):
        detection = detections[k - 1] if k <= len(detections) else None
        if box is None or detection is None or detection["id"] in matched:
            continue
        part = labels[box] == k
        pixels = int(part.sum())
        if not 0.02 * px * py <= pixels * plane.res**2 <= MAX_ACCEPTED_CELLS * px * py:
            continue
        if (part & blocked[box]).sum() >= 0.5 * pixels:
            continue  # floor, bathtub apron, door: tile-like but not this wall
        points = np.column_stack(np.nonzero(part)[::-1]).astype(np.float32)
        (_, _), (w, h), angle = cv2.minAreaRect(points)
        if pixels / max(1.0, (w + 1) * (h + 1)) < RECTANGULARITY_MIN:
            continue
        if min(angle % 90, 90 - angle % 90) > ANGLE_TOLERANCE_DEG:
            continue
        candidates.append((detection["id"], box, part, pixels))
    accepted, ids = np.zeros(plane.shape, bool), []
    grown = cells.copy()
    while candidates:
        near = cv2.dilate(grown.astype(np.uint8), kernel) > 0
        joined = [c for c in candidates if (c[2] & near[c[1]]).sum() >= 0.5 * c[3]]
        if not joined:
            break
        for detection_id, box, part, _ in joined:
            accepted[box] |= part
            grown[box] |= part
            ids.append(detection_id)
        candidates = [c for c in candidates if c[0] not in set(ids)]
    return accepted, ids


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
            part = mask & (box if opening else band) & ~claimed
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
