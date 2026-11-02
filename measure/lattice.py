"""Tile quadrilaterals and a lattice-constrained homography from the image to the wall plane.

Scale comes from the pitch (tile + joint) between mask centres, not from mask edges, which SAM
draws slightly inside the true tile boundary. Centres are diagonal intersections, which a
homography maps exactly. Bond offsets, orientation and shear are area-preserving ambiguities
of the same lattice, so they cannot bias the measured area.
"""

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.spatial import cKDTree

MIN_TILES = 12
SOLIDITY_MIN = 0.85
MERGED_RATIO = 1.7
FRAGMENT_RATIO = 0.65  # cut half tiles at row ends are partial tiles, not lattice anchors
NEIGHBOURS = 8
SEEDS = 5
ASPECT_TOLERANCE = 1.6
START_RADIUS = 1.6  # lattice cells (Chebyshev), i.e. the eight neighbours of the seed
GROWTH = 1.5
THRESHOLDS = (0.2, 0.12, 0.12)  # lattice cells: growth/first refinement, then final
SHAPE_RANGE = (0.6, 1.3)  # rectified tile extent relative to the nominal tile, per axis
CLUSTER_GAP = 2  # lattice cells; isolated tiles further away than one missing tile are dropped


@dataclass
class Quad:
    det_id: str
    corners: np.ndarray  # (4, 2) image px, clockwise from the top-left
    center: np.ndarray  # (2,) diagonal intersection
    area_px: float


@dataclass
class LatticeTile:
    det_id: str
    i: int
    j: int
    center: np.ndarray


@dataclass
class LatticeFit:
    H: np.ndarray  # image px -> plane mm
    pitch: tuple[float, float]
    cell: tuple[float, float]  # tile size along plane x and y
    tiles: list[LatticeTile]
    row_offsets: dict[int, float]
    transposed: bool
    residual_px: float
    straightness_px: float | None
    tile_px: float
    n_merged_suspected: int = 0

    def to_plane(self, points):
        return _apply(self.H, points)

    def to_image(self, points):
        return _apply(np.linalg.inv(self.H), points)

    def cell_rect(self, i, j):
        """Plane rectangle (x0, y0, x1, y1) of tile (i, j) grown by half a joint per side."""
        px, py = self.pitch
        x, y = i * px + self.row_offsets.get(j, 0.0), j * py
        return x - px / 2, y - py / 2, x + px / 2, y + py / 2


def extract_quads(detections):
    """Quadrilaterals of complete tile masks, minus local area outliers.

    Returns (quads, n_merged). Masks over 1.7x the median area of their eight nearest neighbours
    are counted as merged tiles; under 0.4x are fragments. Both are dropped.
    """
    quads = [
        quad
        for detection in detections
        if not detection.get("edge_truncated") and (quad := _quad(detection)) is not None
    ]
    if len(quads) < 4:
        return quads, 0
    centers = np.array([q.center for q in quads])
    areas = np.array([q.area_px for q in quads])
    k = min(NEIGHBOURS, len(quads) - 1)
    _, neighbours = cKDTree(centers).query(centers, k + 1)
    ratio = areas / np.median(areas[neighbours[:, 1:]], axis=1)
    merged = ratio > MERGED_RATIO
    keep = ~merged & (ratio >= FRAGMENT_RATIO)
    return [q for q, ok in zip(quads, keep, strict=True) if ok], int(merged.sum())


def fit_lattice(detections, tile):
    """Best lattice over a few seeds and both bond directions, or None below MIN_TILES."""
    quads, merged = extract_quads(detections)
    if len(quads) < MIN_TILES:
        return None
    best = None
    for transposed in (False, True):
        for seed in _seeds(quads, tile):
            fit = _fit(quads, tile, seed, transposed)
            if fit is not None and (
                best is None
                or (len(fit.tiles), -fit.residual_px) > (len(best.tiles), -best.residual_px)
            ):
                best = fit
    if best is None or len(best.tiles) < MIN_TILES:
        return None
    best.n_merged_suspected = merged
    return best


def _apply(H, points):
    points = np.asarray(points, np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, H).reshape(-1, 2)


def _polygon_area(points):
    x, y = np.asarray(points, np.float64).T
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


def _order(corners):
    center = corners.mean(axis=0)
    angles = np.arctan2(corners[:, 1] - center[1], corners[:, 0] - center[0])
    ordered = corners[np.argsort(angles)]
    return np.roll(ordered, -int(np.argmin(ordered.sum(axis=1))), axis=0)


def _diagonal_intersection(c):
    d1, d2 = c[2] - c[0], c[3] - c[1]
    denominator = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denominator) < 1e-9:
        return None
    offset = c[1] - c[0]
    s = (offset[0] * d2[1] - offset[1] * d2[0]) / denominator
    return c[0] + s * d1


def _quad(detection):
    outer = [
        np.asarray(c["points"], np.float32)
        for c in detection.get("contours", [])
        if not c.get("hole") and len(c["points"]) >= 3
    ]
    if not outer:
        return None
    points = max(outer, key=lambda p: abs(cv2.contourArea(p)))
    hull = cv2.convexHull(points)
    perimeter = cv2.arcLength(hull, True)
    for fraction in np.arange(0.005, 0.15, 0.005):
        approx = cv2.approxPolyDP(hull, fraction * perimeter, True)
        if len(approx) == 4:
            break
        if len(approx) < 4:
            return None
    else:
        return None
    corners = _order(approx.reshape(4, 2).astype(np.float64))
    quad_area = _polygon_area(corners)
    if quad_area <= 0 or abs(cv2.contourArea(points)) / quad_area < SOLIDITY_MIN:
        return None
    center = _diagonal_intersection(corners)
    if center is None:
        return None
    return Quad(str(detection["id"]), corners, center, quad_area)


def _seeds(quads, tile, count=SEEDS):
    """Spread-out seeds among quads shaped like the given tile and of the dominant size.

    Decorative bands and mosaics often sit where the median centre falls; seeding on them
    builds the lattice at the wrong pitch. The area-weighted median picks the tiles that cover
    most of the wall.
    """
    centers = np.array([q.center for q in quads])
    areas = np.array([q.area_px for q in quads])
    c = np.array([q.corners for q in quads])
    first = np.linalg.norm(c[:, 1] - c[:, 0], axis=1) + np.linalg.norm(c[:, 2] - c[:, 3], axis=1)
    second = np.linalg.norm(c[:, 3] - c[:, 0], axis=1) + np.linalg.norm(c[:, 2] - c[:, 1], axis=1)
    aspect = np.maximum(first, second) / np.maximum(np.minimum(first, second), 1e-9)
    expected = max(tile.width_mm, tile.height_mm) / min(tile.width_mm, tile.height_mm)
    shaped = (aspect >= expected / ASPECT_TOLERANCE) & (aspect <= expected * ASPECT_TOLERANCE)
    if shaped.sum() < MIN_TILES:
        shaped[:] = True
    order = np.argsort(areas[shaped])
    cumulative = np.cumsum(areas[shaped][order])
    typical = areas[shaped][order][np.searchsorted(cumulative, cumulative[-1] / 2)]
    candidates = np.flatnonzero(shaped & (areas >= typical / 2.5) & (areas <= typical * 2.5))
    points = centers[candidates]
    picked = [int(np.argmin(np.linalg.norm(points - points.mean(axis=0), axis=1)))]
    gaps = np.linalg.norm(points - points[picked[0]], axis=1)
    while len(picked) < min(count, len(candidates)):
        picked.append(int(np.argmax(gaps)))
        gaps = np.minimum(gaps, np.linalg.norm(points - points[picked[-1]], axis=1))
    return [int(candidates[k]) for k in picked]


def _circular_offset(values):
    """Mean of fractional positions on the unit circle, trimmed to the consistent majority."""
    angles = 2 * np.pi * values
    mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()) / (2 * np.pi) % 1
    close = np.abs((values - mean + 0.5) % 1 - 0.5) <= 0.25
    if close.any() and not close.all():
        angles = angles[close]
        mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()) / (2 * np.pi) % 1
    return mean


def _assign(lattice):
    """Integer indices, per-row offsets and target centres for points in lattice units."""
    j = np.rint(lattice[:, 1]).astype(int)
    offsets = {int(row): _circular_offset(lattice[j == row, 0] % 1) for row in np.unique(j)}
    o = np.array([offsets[int(row)] for row in j])
    i = np.rint(lattice[:, 0] - o).astype(int)
    targets = np.column_stack([i + o, j])
    error = np.linalg.norm(lattice - targets, axis=1)
    best = {}
    for index in np.argsort(error):
        best.setdefault((int(i[index]), int(j[index])), int(index))
    keep = np.array(sorted(best.values()), int)
    return keep, i[keep], j[keep], targets[keep], offsets


def _fit_image_space(targets, centers):
    """Least squares in image pixels, where mask noise is roughly uniform."""
    inverse, _ = cv2.findHomography(targets, centers, 0)
    if inverse is None or abs(np.linalg.det(inverse)) < 1e-12:
        return None
    return np.linalg.inv(inverse)


def _fit(quads, tile, seed, transposed):
    """Grow a lattice from one seed tile; H maps image px to lattice units until the end."""
    centers = np.array([q.center for q in quads])
    corners = [q.corners for q in quads]
    if transposed:
        centers = centers[:, ::-1].copy()
        corners = [_order(c[:, ::-1].copy()) for c in corners]
    seed_corners = corners[seed]
    top = np.linalg.norm(seed_corners[1] - seed_corners[0])
    side = np.linalg.norm(seed_corners[3] - seed_corners[0])
    w, h, g = tile.width_mm, tile.height_mm, tile.grout_mm
    cell = (w, h) if (top >= side) == (w >= h) else (h, w)
    pitch = (cell[0] + g, cell[1] + g)
    hx, hy = cell[0] / pitch[0] / 2, cell[1] / pitch[1] / 2
    rectangle = np.array([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]], np.float32)
    H = cv2.getPerspectiveTransform(seed_corners.astype(np.float32), rectangle).astype(np.float64)
    radius, extra = START_RADIUS, 2
    for _ in range(40):
        lattice = _apply(H, centers)
        distance = np.abs(lattice - lattice[seed]).max(axis=1)
        finite = np.isfinite(distance)
        near = np.flatnonzero(finite & (distance <= radius))
        keep, _, _, targets, _ = _assign(lattice[near])
        if len(keep) < 4:
            return None
        if len(keep) < 8:
            found, mask = cv2.findHomography(centers[near[keep]], targets, 0), None
            found = found[0]
            inliers = near[keep]
        else:
            found, mask = cv2.findHomography(
                centers[near[keep]], targets, cv2.RANSAC, THRESHOLDS[0]
            )
            if mask is not None:
                inliers = near[keep][mask.ravel().astype(bool)]
        if found is None:
            return None
        H = found
        if radius >= distance[finite].max():
            extra -= 1
            if extra < 0:
                break
        radius *= GROWTH
    else:
        return None
    for threshold in THRESHOLDS:
        result = _refine(H, centers, corners, inliers, threshold, (2 * hx, 2 * hy))
        if result is None:
            return None
        H, keep, i, j, targets, offsets = result
        inliers = keep
    if len(keep) < MIN_TILES:
        return None
    scale = np.diag([pitch[0], pitch[1], 1.0])
    H = scale @ H
    plane_targets = targets * pitch
    inverse = np.linalg.inv(H)
    residual = float(
        np.sqrt(np.mean(np.sum((_apply(inverse, plane_targets) - centers[keep]) ** 2, axis=1)))
    )
    swap = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]], np.float64)
    rows = set(j.tolist())
    original_centers = centers[:, ::-1] if transposed else centers
    tiles = [
        LatticeTile(quads[k].det_id, int(a), int(b), original_centers[k])
        for k, a, b in zip(keep, i, j, strict=True)
    ]
    return LatticeFit(
        H=H @ swap if transposed else H,
        pitch=pitch,
        cell=cell,
        tiles=tiles,
        row_offsets={row: float(o) * pitch[0] for row, o in offsets.items() if row in rows},
        transposed=transposed,
        residual_px=residual,
        straightness_px=_straightness(centers[keep], j),
        tile_px=float(np.sqrt(np.median([quads[k].area_px for k in keep]))),
    )


def _refine(H, centers, corners, inliers, threshold, expected):
    """Remove shear using the inlier tile edges, then reassign and refit on lattice inliers.

    A centre near a lattice point is not enough: a tile from another plane lands within the
    threshold by chance. Its rectified corners must also span about one tile per axis.
    """
    H = _unshear(H, [corners[k] for k in inliers])
    lattice = _apply(H, centers)
    keep, i, j, targets, offsets = _assign(lattice)
    good = np.linalg.norm(lattice[keep] - targets, axis=1) <= threshold
    good &= np.array([_tile_shaped(H, corners[k], expected) for k in keep], bool)
    good[good] = _largest_cluster(i[good], j[good])
    if good.sum() < MIN_TILES:
        return None
    keep, i, j, targets = keep[good], i[good], j[good], targets[good]
    refined = _fit_image_space(targets, centers[keep])
    if refined is None:
        return None
    return refined, keep, i, j, targets, offsets


def _largest_cluster(i, j, gap=CLUSTER_GAP):
    """Mask of the largest group of lattice cells linked through at most gap-1 missing tiles."""
    cells = {(a, b): k for k, (a, b) in enumerate(zip(i.tolist(), j.tolist(), strict=True))}
    seen, best = set(), []
    for start in cells:
        if start in seen:
            continue
        seen.add(start)
        stack, group = [start], []
        while stack:
            a, b = stack.pop()
            group.append(cells[(a, b)])
            for da in range(-gap, gap + 1):
                for db in range(-gap, gap + 1):
                    neighbour = (a + da, b + db)
                    if neighbour in cells and neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
        if len(group) > len(best):
            best = group
    mask = np.zeros(len(i), bool)
    mask[best] = True
    return mask


def _tile_shaped(H, corners, expected):
    span = np.ptp(_apply(H, corners), axis=0) / np.asarray(expected)
    return bool(np.all((span >= SHAPE_RANGE[0]) & (span <= SHAPE_RANGE[1])))


def _unshear(H, corners):
    """Make tile edges that cross the rows vertical in the plane (an area-preserving shear)."""
    tilts = []
    for quad in corners:
        plane = _apply(H, quad)
        for a, b in ((0, 3), (1, 2), (0, 1), (3, 2)):
            dx, dy = plane[b] - plane[a]
            if abs(dy) > abs(dx):
                tilts.append(dx / dy)
    if not tilts:
        return H
    shear = np.array([[1, -np.median(tilts), 0], [0, 1, 0], [0, 0, 1]], np.float64)
    return shear @ H


def _straightness(centers, rows):
    """RMS distance of tile centres from straight fitted rows; lens distortion bends rows."""
    residuals = []
    for row in np.unique(rows):
        points = centers[rows == row]
        if len(points) < 4:
            continue
        centred = points - points.mean(axis=0)
        normal = np.linalg.svd(centred, full_matrices=False)[2][1]
        residuals.extend(centred @ normal)
    if not residuals:
        return None
    return float(np.sqrt(np.mean(np.square(residuals))))
