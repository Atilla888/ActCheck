"""Map SAM masks to original pixels and conservatively deduplicate crop observations.

Counts remain detections, not reliable tiles. No floor/wall/mirror semantics are inferred.
The official parser supplies half-open box-local bounds. Source coordinates here refer to
an EXIF-oriented image; the caller must crop only after applying that orientation.
"""

from collections import defaultdict
from math import ceil, floor, isfinite

import cv2
import meta_sam_parser as msp
import numpy as np


def convert_record(record, input_size, crop_box, source_size, run_id):
    """Return one JSON-serializable detection, with source-space contours and provenance.

    Contours describe pixel centres, whereas ``box`` is the tight half-open pixel extent.
    ``area_px`` is the binary mask area mapped into source coordinates, not physical area.
    Rounding of resized crop dimensions is handled independently in x and y.
    """
    iw, ih = map(int, input_size)
    sw, sh = map(int, source_size)
    left, top, right, bottom = map(float, crop_box)
    if min(iw, ih, sw, sh) <= 0 or not (0 <= left < right <= sw and 0 <= top < bottom <= sh):
        raise ValueError("Invalid image dimensions or crop bounds")
    bounds = record.bounds
    bx, by, br, bb = map(float, (bounds.left, bounds.top, bounds.right, bounds.bottom))
    if not all(map(isfinite, (bx, by, br, bb))) or br <= bx or bb <= by:
        raise ValueError("Invalid mask bounds")
    mw, mh = record.mask.width, record.mask.height
    if mw <= 0 or mh <= 0:
        raise ValueError("Invalid mask raster dimensions")
    raster = np.frombuffer(msp.decode_mask_to_raster(record.mask), np.uint8).reshape(mh, mw)
    raster = (raster != 0).astype(np.uint8)
    # The raster can have different dimensions from its box; its own dimensions
    # must not be confused with the full API-input image dimensions.
    rx, ry = (br - bx) / mw, (bb - by) / mh
    xx = bx + (np.arange(mw) + 0.5) * rx
    yy = by + (np.arange(mh) + 0.5) * ry
    raster[:, (xx < 0) | (xx >= iw)] = 0
    raster[(yy < 0) | (yy >= ih), :] = 0
    ys, xs = np.nonzero(raster)
    sx, sy = (right - left) / iw, (bottom - top) / ih
    contours, hierarchy = cv2.findContours(raster, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    mapped = []
    for index, contour in enumerate(contours):
        # At most half an API-input pixel of simplification; scale does not hide seams.
        contour = cv2.approxPolyDP(contour, 0.5, True)
        if len(contour) < 3:
            continue
        depth, parent = 0, int(hierarchy[0, index, 3])
        while parent >= 0:
            depth += 1
            parent = int(hierarchy[0, parent, 3])
        # Transform entire contours in NumPy; scalar np.clip for every vertex is costly
        # on detailed grout boundaries and does not change the underlying operation.
        points = contour[:, 0, :].astype(np.float64)
        points[:, 0] = np.clip(left + (bx + (points[:, 0] + 0.5) * rx) * sx, 0, sw)
        points[:, 1] = np.clip(top + (by + (points[:, 1] + 0.5) * ry) * sy, 0, sh)
        points = np.round(points, 3).tolist()
        mapped.append({"points": points, "hole": bool(depth % 2), "depth": depth})
    if len(xs):
        input_box = [
            max(0, bx + int(xs.min()) * rx),
            max(0, by + int(ys.min()) * ry),
            min(iw, bx + (int(xs.max()) + 1) * rx),
            min(ih, by + (int(ys.max()) + 1) * ry),
        ]
        box = [
            left + input_box[0] * sx,
            top + input_box[1] * sy,
            left + input_box[2] * sx,
            top + input_box[3] * sy,
        ]
    else:
        input_box, box = [0, 0, 0, 0], [left, top, left, top]
    # Masks can stop several pixels before a crop seam. Conservatively flag that
    # margin so a clipped fragment cannot qualify as a complete tile.
    edge_margin = max(2.0, 0.005 * min(iw, ih))
    touches = (
        bool(len(xs) and input_box[0] <= edge_margin),
        bool(len(xs) and input_box[1] <= edge_margin),
        bool(len(xs) and input_box[2] >= iw - edge_margin),
        bool(len(xs) and input_box[3] >= ih - edge_margin),
    )
    internal = (left > 0, top > 0, right < sw, bottom < sh)
    crop_boundary = any(touch and inner for touch, inner in zip(touches, internal, strict=True))
    image_boundary = any(
        touch and not inner for touch, inner in zip(touches, internal, strict=True)
    )
    area = float(len(xs) * rx * ry * sx * sy)
    external = (
        [c for c, h in zip(contours, hierarchy[0], strict=True) if h[3] == -1]
        if len(contours)
        else []
    )
    rectangularity = 0.0
    if external:
        # Use all component points: disconnected fragments must not each claim a full rectangle.
        points = np.concatenate(external).astype(np.float32)
        points[:, :, 0] *= rx * sx
        points[:, :, 1] *= ry * sy
        rect = cv2.minAreaRect(points)
        rect_area = max(1, (rect[1][0] + rx * sx) * (rect[1][1] + ry * sy))
        rectangularity = min(1.0, area / rect_area)
    confidence = record.confidence
    if confidence is not None and not isfinite(confidence):
        confidence = None
    candidate = bool(
        len(xs) >= 25
        and area <= sw * sh * 0.1
        and rectangularity >= 0.65
        and confidence is not None
        and confidence >= 0.5
        and mapped
    )
    return {
        "id": f"{run_id}:{record.object_id}",
        "run_id": str(run_id),
        "object_id": str(record.object_id),
        "box": [round(v, 3) for v in box],
        "contours": mapped,
        "confidence": confidence,
        "area_px": round(area, 3),
        "rectangularity": round(rectangularity, 6),
        "edge_truncated": crop_boundary or image_boundary,
        "crop_boundary": crop_boundary,
        "image_boundary": image_boundary,
        "candidate": candidate,
        "input_size": [iw, ih],
        "crop_box": list(crop_box),
        "source_size": [sw, sh],
    }


def _rasterize(detection, region, scale):
    left, top, right, bottom = region
    width = max(1, ceil((right - left) * scale) + 2)
    height = max(1, ceil((bottom - top) * scale) + 2)
    raster = np.zeros((height, width), np.uint8)
    # Tree order restores islands within holes instead of erasing them.
    for contour in sorted(detection["contours"], key=lambda c: c.get("depth", int(c["hole"]))):
        points = np.asarray(contour["points"], np.float64)
        points -= (left, top)
        points *= scale
        points = np.rint(points).astype(np.int32)
        cv2.fillPoly(raster, [points], 0 if contour["hole"] else 1)
    return raster


def mask_overlap(a, b):
    """Return raster-mask IoU, coverage of A, coverage of B, and raster areas.

    Fast bounding-box rejection precedes rasterization. Work is bounded to a 512-pixel
    longest side; overlap thresholds are intentionally far from single boundary pixels.
    """
    ax, ay, ar, ab = a["box"]
    bx, by, br, bb = b["box"]
    if min(ar, br) <= max(ax, bx) or min(ab, bb) <= max(ay, by):
        return 0.0, 0.0, 0.0, 0, 0
    region = (floor(min(ax, bx)), floor(min(ay, by)), ceil(max(ar, br)), ceil(max(ab, bb)))
    scale = min(1.0, 512 / max(region[2] - region[0], region[3] - region[1], 1))
    ra, rb = _rasterize(a, region, scale), _rasterize(b, region, scale)
    aa, ba = int(np.count_nonzero(ra)), int(np.count_nonzero(rb))
    intersection = int(np.count_nonzero(ra & rb))
    return (
        intersection / max(1, aa + ba - intersection),
        intersection / max(1, aa),
        intersection / max(1, ba),
        aa,
        ba,
    )


def _quality(detection):
    # Complete observations beat seam fragments, even when the fragment has higher confidence.
    return (
        not detection.get("crop_boundary", detection.get("edge_truncated", False)),
        not detection.get("edge_truncated", False),
        float(detection.get("area_px", 0)) if detection.get("edge_truncated", False) else 0,
        float(detection.get("rectangularity", 0)),
        float(detection.get("confidence") or 0),
        float(detection.get("area_px", 0)),
        str(detection["id"]),
    )


def merge_detections(detections):
    """Return (unique candidate detections, suppression diagnostics).

    Complete objects overlapping at mask IoU ≥0.60 are duplicate observations. A crop-edge
    fragment contained ≥90% in another observation is also suppressed, across requests only.
    A broad mask spanning multiple tiles is removed only with evidence from two disjoint,
    complete smaller instances from one other request. This avoids keeping an inflated
    super-mask while suppressing the legitimate tiles beneath it.
    """
    accepted, suppressed = [], []
    ids = set()
    for detection in detections:
        if detection["id"] in ids:
            raise ValueError("Detection IDs must be unique within an image")
        ids.add(detection["id"])
        if not detection.get("candidate", True) or not detection.get("contours"):
            suppressed.append({"id": detection["id"], "kept_id": None, "reason": "not_candidate"})
        else:
            accepted.append(detection)
    overlap_cache = {}

    def overlap(a, b):
        # Do not retain O(N²) zero-overlap cache entries on dense mosaic images.
        ax, ay, ar, ab = a["box"]
        bx, by, br, bb = b["box"]
        if min(ar, br) <= max(ax, bx) or min(ab, bb) <= max(ay, by):
            return 0.0, 0.0, 0.0, 0, 0
        key = (a["id"], b["id"])
        if key not in overlap_cache:
            result = mask_overlap(a, b)
            overlap_cache[key] = result
            overlap_cache[(b["id"], a["id"])] = (
                result[0],
                result[2],
                result[1],
                result[4],
                result[3],
            )
        return overlap_cache[key]

    merged_ids = set()
    for broad in accepted:
        children = defaultdict(list)
        for child in accepted:
            if child is broad or child.get("edge_truncated") or child["run_id"] == broad["run_id"]:
                continue
            ratio = child["area_px"] / max(1, broad["area_px"])
            if not 0.08 <= ratio <= 0.75:
                continue
            _, _, covered, _, _ = overlap(broad, child)
            if covered >= 0.90:
                children[child["run_id"]].append(child)
        witnesses = None
        for group in children.values():
            independent = []
            for child in sorted(group, key=_quality, reverse=True):
                if all(overlap(child, other)[0] < 0.10 for other in independent):
                    independent.append(child)
            area = sum(child["area_px"] for child in independent)
            if len(independent) >= 2 and area >= broad["area_px"] * 0.60:
                witnesses = [child["id"] for child in independent]
                break
        if witnesses:
            merged_ids.add(broad["id"])
            suppressed.append(
                {
                    "id": broad["id"],
                    "kept_id": None,
                    "reason": "spans_multiple_instances",
                    "witness_ids": witnesses,
                }
            )
    kept = []
    for detection in sorted(accepted, key=_quality, reverse=True):
        if detection["id"] in merged_ids:
            continue
        duplicate = None
        reason = None
        for other in kept:
            iou, covered, _, _, _ = overlap(detection, other)
            if iou >= 0.60:
                duplicate, reason = other, "mask_overlap"
                break
            if detection["run_id"] != other["run_id"]:
                if (
                    detection.get("crop_boundary", detection.get("edge_truncated", False))
                    and covered >= 0.90
                ):
                    duplicate, reason = other, "contained_crop_fragment"
                    break
        if duplicate:
            duplicate["duplicate_ids"].append(detection["id"])
            suppressed.append({"id": detection["id"], "kept_id": duplicate["id"], "reason": reason})
        else:
            kept.append({**detection, "duplicate_ids": []})
    kept.sort(key=lambda d: (d["box"][1], d["box"][0], d["id"]))
    return kept, {
        "input_count": len(detections),
        "candidate_count": len(accepted),
        "kept_count": len(kept),
        "suppressed": suppressed,
        "method": "mask_iou_0.60_or_cross_crop_fragment_coverage_0.90",
        "reliability": "unvalidated_candidate_detections",
    }
