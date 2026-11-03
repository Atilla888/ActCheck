"""Do tiles continue beyond the counted area? A check in the photo, independent of SAM.

SAM can miss a wall's outer tiles (glare, shadow, a cut row). The lattice predicts where they
would be. The photo is rectified onto the wall plane and each side of the counted area is judged
on its own, so a missed column is not diluted by painted wall on the other three sides.

A cell beside the counted area looks like a missed tile when the joints running into it from the
counted tiles continue across the strip next to the counted area, and its colour matches the
tiles. Only that strip is sampled, so a cut row narrower than a tile works too. A painted wall
has no joints there, and each joint is compared with the surface on both its sides, so a smooth
lighting gradient shows none either. Joint contrast is relative and colour is chromaticity, so
shadow does not hide a tile, and glare may wash the colour towards white. When the tiles' joints
are invisible, the cell's colour alone decides (strictly).
"""

import cv2
import numpy as np
from PIL import Image

TILE_SIDE = 128  # px per tile pitch in the rectified probe raster
MAX_SIDE = 3000  # px, probe raster limit
COUNTED = 0.85  # a cell this much inside the counted area is counted
BESIDE = 0.6  # share of the strip next to a cell that must be counted area
DEPTH = 0.35  # of the pitch: the strip next to the counted area that is sampled
FLANK = 0.08  # of the tile: tile surface beside a joint, compared with the joint
JOINT_SHARE = 0.25  # a continuing joint keeps at least this share of the tiles' contrast
VISIBLE_JOINT = 0.03  # relative contrast below which joints count as invisible
CHROMA_SPREAD = 0.015  # minimum chromaticity tolerance
COLOUR_SPREAD = 8.0  # minimum Lab tolerance when only colour decides
STEP = 0.05  # of the pitch: strips tested outwards from the counted area
SIDE_CELLS = 2  # cells per side that must show continuing tiles
NEUTRAL = np.array([1 / 3, 1 / 3])
SIDES = ((0, -1), (0, 1), (1, -1), (1, 1))  # (plane axis, side of the cell the region is on)


def uncounted_tiles(image, fit, plane, region, blocked):
    """(cells where tiles visibly continue past the counted region, cells probed, their mm²).

    A side of the counted region needs at least two such cells; a single one is noise. A cell's
    area is how far the joints continue into it times its length, or the rest of the cell when
    they run through the whole sampled strip.
    """
    if len(fit.tiles) < 8:
        return 0, 0, 0.0
    probe = _Probe(image, fit, plane)
    reference = probe.reference()
    if reference is None:
        return 0, 0, 0.0
    sides, looked = {}, set()
    for i, j in _candidates(fit, plane):
        rect = _cell_rect(fit, i, j)
        box = _plane_box(plane, rect)
        if box is None or region[box].mean() >= COUNTED or blocked[box].mean() >= 0.5:
            continue
        for axis, sign in SIDES:
            if not _beside(region, plane, fit, rect, axis, sign):
                continue
            counted = _counted_depth(region[box], axis, sign) * plane.res
            reach = probe.reach(rect, axis, sign, reference, counted)
            if reach is None:
                continue
            looked.add((i, j))
            if reach > 0:
                area = reach * fit.pitch[1 - axis]
                sides.setdefault((axis, sign), []).append(((i, j), area))
    missed = {}
    for cells in sides.values():
        if len(cells) >= SIDE_CELLS:
            for cell, area in cells:
                missed[cell] = max(area, missed.get(cell, 0.0))
    return len(missed), len(looked), float(sum(missed.values()))


class _Reference:
    def __init__(self, chroma, lab, joints):
        self.chroma = np.median(chroma, axis=0)
        mad = np.median(np.abs(chroma - self.chroma), axis=0)
        self.chroma_spread = max(3 * float(mad.max()), CHROMA_SPREAD)
        self.lab = np.median(lab, axis=0)
        self.lab_spread = np.maximum(3 * np.median(np.abs(lab - self.lab), axis=0), COLOUR_SPREAD)
        self.joint = [float(np.median(j)) if len(j) >= 8 else 0.0 for j in joints]


class _Probe:
    """The photo rectified onto the wall plane, sampled in plane millimetres."""

    def __init__(self, image, fit, plane):
        self.fit = fit
        self.lo = np.asarray(plane.lo, np.float64)
        extent = np.array([plane.shape[1], plane.shape[0]]) * plane.res
        self.res = max(min(fit.pitch) / TILE_SIDE, float(extent.max()) / MAX_SIDE)
        size = tuple(int(np.ceil(e / self.res)) for e in extent)
        scale = min(1.0, 1.5 * TILE_SIDE / max(fit.tile_px, 1.0))  # joints stay unaliased
        if scale < 1.0:
            target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(target, Image.Resampling.BOX)
        rgb = np.asarray(image.convert("RGB"))
        to_raster = np.array(
            [[1 / self.res, 0, -self.lo[0] / self.res], [0, 1 / self.res, -self.lo[1] / self.res],
             [0, 0, 1]]
        )  # fmt: skip
        M = to_raster @ fit.H @ np.diag([1 / scale, 1 / scale, 1.0])
        warped = cv2.warpPerspective(rgb, M, size, flags=cv2.INTER_LINEAR, borderValue=0)
        ones = np.ones(rgb.shape[:2], np.uint8)
        self.valid = cv2.warpPerspective(ones, M, size, flags=cv2.INTER_NEAREST) > 0
        self.rgb = warped
        self.lab = cv2.cvtColor(warped, cv2.COLOR_RGB2LAB)
        mm_per_px = min(fit.pitch) / max(fit.tile_px, 1e-9)
        self.tol = max(self.res, mm_per_px * max(fit.residual_px, 0.5))

    def reference(self):
        """Colour and joint contrast of the matched tiles, or None when too few are visible."""
        fit = self.fit
        chroma, lab, joints = [], [], ([], [])
        for tile in fit.tiles:
            rect = _cell_rect(fit, tile.i, tile.j)
            for o in (0, 1):
                margin = 0.1 * fit.cell[1 - o]
                span = (rect[1 - o] + margin, rect[3 - o] - margin)
                for at in (rect[o], rect[o + 2]):
                    contrast = self.joint(o, at, span)
                    if contrast is not None:
                        joints[o].append(contrast)
            px, py = fit.pitch
            x0, y0, x1, y1 = rect
            colour = self.colour((x0 + 0.25 * px, y0 + 0.25 * py, x1 - 0.25 * px, y1 - 0.25 * py))
            if colour is not None:
                chroma.append(colour[0])
                lab.append(colour[1])
        if len(chroma) < 8:
            return None
        return _Reference(np.array(chroma), np.array(lab), joints)

    def reach(self, rect, axis, sign, reference, counted=0.0):
        """How far (mm) tiles visibly continue into the cell past the counted area, or None.

        Thin strips are tested outwards from the counted area (which a cut piece may already
        carry `counted` mm into the cell). When the joints run through the whole sampled depth,
        the rest of the cell is taken as tile. None when the first strip is not in the photo.
        """
        pitch, cell = self.fit.pitch[axis], self.fit.cell[axis]
        step = max(STEP * pitch, 2 * self.res)
        start = counted + (pitch - cell) / 2 + 0.04 * cell
        steps = max(1, int((counted + DEPTH * pitch - start) // step))
        edge = rect[axis] if sign < 0 else rect[axis + 2]
        reach = 0.0
        for k in range(steps):
            near, far = start + k * step, start + (k + 1) * step
            strip = (edge + near, edge + far) if sign < 0 else (edge - far, edge - near)
            verdict = self._tile_like(strip, axis, rect, reference)
            if verdict is None and k == 0:
                return None
            if not verdict:
                return reach
            reach = far - counted
        return pitch - counted

    def _tile_like(self, strip, axis, rect, reference):
        """Whether the cell's strip (along `axis`) shows the tiles' joints and colour, or None."""
        o = 1 - axis
        across = (rect[o] + 0.25 * self.fit.pitch[o], rect[o + 2] - 0.25 * self.fit.pitch[o])
        colour = self.colour(_along(axis, strip, across))
        if colour is None:
            return None
        chroma, lab = colour
        expected = reference.joint[o]
        if abs(expected) < VISIBLE_JOINT:  # joints invisible: colour alone, strictly
            return bool(np.all(np.abs(lab - reference.lab) <= reference.lab_spread))
        contrasts = [self.joint(o, rect[o], strip), self.joint(o, rect[o + 2], strip)]
        contrasts = [c for c in contrasts if c is not None]
        if not contrasts:
            return None
        # One joint is enough: the other may be the wall's own edge.
        continuing = any(
            c * expected > 0 and abs(c) >= JOINT_SHARE * abs(expected) for c in contrasts
        )
        washed = _to_segment(chroma, reference.chroma, NEUTRAL)  # glare desaturates
        return continuing and washed <= reference.chroma_spread

    def joint(self, o, at, span):
        """(joint band − tile on both sides) / tile lightness for the joint at plane[o] = at.

        Both sides cancel a lighting gradient and the next tile's slightly different shade.
        """
        fit = self.fit
        half = (fit.pitch[o] - fit.cell[o]) / 2 + self.tol
        flank = FLANK * fit.cell[o]
        boxes = [
            self._box(_along(1 - o, span, across))
            for across in ((at - half, at + half), (at - half - flank, at - half),
                           (at + half, at + half + flank))
        ]  # fmt: skip
        if any(box is None for box in boxes):
            return None
        band, low, high = (self._mean(self.lab, box)[0] for box in boxes)
        lightness = (low + high) / 2
        return (band - lightness) / max(lightness, 1.0)

    def colour(self, rect):
        """(rg chromaticity, Lab) of the rectangle, or None when mostly outside the photo."""
        box = self._box(rect)
        if box is None:
            return None
        rgb = self._mean(self.rgb, box)
        return rgb[:2] / max(rgb.sum(), 1.0), self._mean(self.lab, box)

    def _box(self, rect):
        x0, y0, x1, y1 = rect
        c0, c1 = (int(round((x - self.lo[0]) / self.res)) for x in (x0, x1))
        r0, r1 = (int(round((y - self.lo[1]) / self.res)) for y in (y0, y1))
        height, width = self.valid.shape
        c0, c1, r0, r1 = max(c0, 0), min(c1, width), max(r0, 0), min(r1, height)
        if c1 <= c0 or r1 <= r0:
            return None
        box = slice(r0, r1), slice(c0, c1)
        if self.valid[box].mean() < 0.8:
            return None
        return box

    def _mean(self, raster, box):
        return raster[box][self.valid[box]].astype(np.float64).mean(axis=0)


def _along(axis, along, across):
    """Plane rectangle spanning `along` on plane axis `axis` and `across` on the other."""
    if axis == 0:
        return along[0], across[0], along[1], across[1]
    return across[0], along[0], across[1], along[1]


def _to_segment(point, a, b):
    """Distance from point to the segment a–b."""
    ab = b - a
    t = float(np.clip(np.dot(point - a, ab) / max(float(np.dot(ab, ab)), 1e-12), 0.0, 1.0))
    return float(np.linalg.norm(point - (a + t * ab)))


def _candidates(fit, plane):
    px, py = fit.pitch
    lo = np.asarray(plane.lo, np.float64)
    hi = lo + np.array([plane.shape[1], plane.shape[0]]) * plane.res
    shift = max((abs(o) for o in fit.row_offsets.values()), default=0.0)
    for j in range(int(np.floor(lo[1] / py)) - 1, int(np.ceil(hi[1] / py)) + 2):
        for i in range(
            int(np.floor((lo[0] - shift) / px)) - 1, int(np.ceil((hi[0] + shift) / px)) + 2
        ):
            yield i, j


def _beside(region, plane, fit, rect, axis, sign):
    """Whether the counted region lies along the cell's side (`sign` end of `axis`)."""
    depth, inset = 0.3 * fit.pitch[axis], 0.2 * fit.pitch[1 - axis]
    edge = rect[axis] if sign < 0 else rect[axis + 2]
    along = (edge - depth, edge) if sign < 0 else (edge, edge + depth)
    box = _plane_box(plane, _along(axis, along, (rect[1 - axis] + inset, rect[3 - axis] - inset)))
    return box is not None and region[box].mean() >= BESIDE


def _counted_depth(cell, axis, sign):
    """Raster px the counted area reaches into the cell from its `sign` end along `axis`."""
    cover = cell.mean(axis=axis) >= 0.5  # per position along the plane axis
    cover = cover if sign < 0 else cover[::-1]
    return len(cover) if cover.all() else int(np.argmin(cover))


def _cell_rect(fit, i, j):
    px, py = fit.pitch
    offset = fit.row_offsets.get(j)
    if offset is None:
        same = [o for row, o in fit.row_offsets.items() if row % 2 == j % 2]
        offset = float(np.median(same)) if same else 0.0
    x, y = i * px + offset, j * py
    return x - px / 2, y - py / 2, x + px / 2, y + py / 2


def _plane_box(plane, rect):
    x0, y0, x1, y1 = rect
    c0, c1 = (round((x - plane.lo[0]) / plane.res) for x in (x0, x1))
    r0, r1 = (round((y - plane.lo[1]) / plane.res) for y in (y0, y1))
    if c0 < 0 or r0 < 0 or c1 > plane.shape[1] or r1 > plane.shape[0] or c1 <= c0 or r1 <= r0:
        return None
    return slice(r0, r1), slice(c0, c1)
