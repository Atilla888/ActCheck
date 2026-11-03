"""Do tiles continue beyond the counted area? A check in the photo, independent of SAM.

SAM can miss a wall's outer tiles (glare, shadow, the photo edge). The lattice predicts where the
next tiles would be; a ring cell counts as an uncounted tile when its interior has the matched
tiles' colour and its border shows the same joint contrast. A painted wall has neither joints
nor, usually, the tile colour, so it stays quiet.
"""

import cv2
import numpy as np

PROBE_SIDE = 1000  # the photo is sampled at this long side
INSET = 0.25  # of the cell, kept clear of joints when sampling a tile's colour
COLOUR_SPREAD = 8.0  # minimum Lab tolerance, also when matched tiles are very uniform
RING = 1  # cells beyond the counted area


def uncounted_tiles(image, fit, plane, region, blocked):
    """(ring cells that look like uncounted tiles, ring cells probed) around the region."""
    scale = min(1.0, PROBE_SIDE / max(image.size))
    small = image.resize((round(image.width * scale), round(image.height * scale)))
    lab = cv2.cvtColor(np.asarray(small.convert("RGB")), cv2.COLOR_RGB2LAB).astype(np.float32)
    reference = [_sample(lab, fit, t.i, t.j, scale) for t in fit.tiles]
    reference = [r for r in reference if r is not None]
    if len(reference) < 8:
        return 0, 0
    colours = np.array([r[0] for r in reference])
    joints = np.array([r[1] for r in reference])
    centre = np.median(colours, axis=0)
    spread = np.maximum(3 * np.median(np.abs(colours - centre), axis=0), COLOUR_SPREAD)
    joint = float(np.median(joints))
    joint_spread = max(3 * float(np.median(np.abs(joints - joint))), 0.5 * abs(joint))
    rows = {t.j for t in fit.tiles}
    columns = [t.i for t in fit.tiles]
    looked = found = 0
    for j in range(min(rows) - RING - 1, max(rows) + RING + 2):
        for i in range(min(columns) - RING - 1, max(columns) + RING + 2):
            box = _cell_box(plane, fit, i, j)
            if box is None or region[box].mean() >= 0.3 or blocked[box].mean() >= 0.5:
                continue
            if not _touches(region, box, plane, fit):
                continue
            sample = _sample(lab, fit, i, j, scale)
            if sample is None:
                continue
            looked += 1
            colour, contrast = sample
            similar = np.all(np.abs(colour - centre) <= spread)
            if abs(joint) >= 4:  # visible joints: a tile shows them, a painted wall does not
                similar &= abs(contrast - joint) <= joint_spread
            found += bool(similar)
    return found, looked


def _cell_rect(fit, i, j):
    px, py = fit.pitch
    offsets = fit.row_offsets
    offset = offsets.get(j)
    if offset is None:
        same = [o for row, o in offsets.items() if row % 2 == j % 2]
        offset = float(np.median(same)) if same else 0.0
    x, y = i * px + offset, j * py
    return x - px / 2, y - py / 2, x + px / 2, y + py / 2


def _cell_box(plane, fit, i, j):
    x0, y0, x1, y1 = _cell_rect(fit, i, j)
    c0, c1 = (round((x - plane.lo[0]) / plane.res) for x in (x0, x1))
    r0, r1 = (round((y - plane.lo[1]) / plane.res) for y in (y0, y1))
    if c0 < 0 or r0 < 0 or c1 > plane.shape[1] or r1 > plane.shape[0]:
        return None
    return slice(r0, r1), slice(c0, c1)


def _touches(region, box, plane, fit):
    grow = max(1, int(round(0.3 * min(fit.pitch) / plane.res)))
    rows, cols = box
    near = (
        slice(max(0, rows.start - grow), rows.stop + grow),
        slice(max(0, cols.start - grow), cols.stop + grow),
    )
    return bool(region[near].any())


def _sample(lab, fit, i, j, scale):
    """(mean Lab colour of the cell's interior, joint-band minus interior lightness) or None."""
    x0, y0, x1, y1 = _cell_rect(fit, i, j)
    (px, py), (cw, ch) = fit.pitch, fit.cell
    inner = _polygon(fit, x0 + INSET * px, y0 + INSET * py, x1 - INSET * px, y1 - INSET * py)
    joint_outer = _polygon(fit, x0, y0, x1, y1)
    joint_inner = _polygon(
        fit, x0 + (px - cw) / 2 + 0.06 * cw, y0 + (py - ch) / 2 + 0.06 * ch,
        x1 - (px - cw) / 2 - 0.06 * cw, y1 - (py - ch) / 2 - 0.06 * ch,
    )  # fmt: skip
    height, width = lab.shape[:2]
    points = [p * scale for p in (inner, joint_outer, joint_inner)]
    if any(not np.isfinite(p).all() for p in points):
        return None
    inside = np.zeros((height, width), np.uint8)
    cv2.fillPoly(inside, [np.round(points[0]).astype(np.int32)], 1)
    if inside.sum() < 12:
        return None
    expected = abs(cv2.contourArea(points[0].astype(np.float32)))
    if inside.sum() < 0.5 * max(expected, 1):  # mostly outside the photo
        return None
    band = np.zeros((height, width), np.uint8)
    cv2.fillPoly(band, [np.round(points[1]).astype(np.int32)], 1)
    cv2.fillPoly(band, [np.round(points[2]).astype(np.int32)], 0)
    colour = lab[inside.astype(bool)].mean(axis=0)
    if band.sum() < 6:
        return colour, 0.0
    return colour, float(lab[band.astype(bool)][:, 0].mean() - colour[0])


def _polygon(fit, x0, y0, x1, y1):
    return fit.to_image([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
