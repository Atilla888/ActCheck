"""Regression tests for source geometry and duplicate/adjacent-instance distinction."""

from types import SimpleNamespace

import numpy as np
import pytest

from measure import crop_merge as cm


def record(monkeypatch, mask, bounds, confidence=0.8):
    monkeypatch.setattr(cm.msp, "decode_mask_to_raster", lambda _: mask.astype(np.uint8).tobytes())
    return SimpleNamespace(
        object_id="7",
        confidence=confidence,
        mask=SimpleNamespace(width=mask.shape[1], height=mask.shape[0]),
        bounds=SimpleNamespace(left=bounds[0], top=bounds[1], right=bounds[2], bottom=bounds[3]),
    )


def rectangle(identity, box, *, run="r1", truncated=False, confidence=0.8):
    x, y, right, bottom = box
    return {
        "id": identity,
        "run_id": run,
        "box": box,
        "contours": [
            {
                "points": [
                    [x + 0.5, y + 0.5],
                    [right - 0.5, y + 0.5],
                    [right - 0.5, bottom - 0.5],
                    [x + 0.5, bottom - 0.5],
                ],
                "hole": False,
            }
        ],
        "area_px": (right - x) * (bottom - y),
        "rectangularity": 1,
        "confidence": confidence,
        "edge_truncated": truncated,
        "crop_boundary": truncated,
        "candidate": True,
    }


def test_mapping_uses_independent_resize_scales_and_half_open_extents(monkeypatch):
    mask = np.ones((10, 20), np.uint8)
    r = record(monkeypatch, mask, (10, 20, 30, 30))
    d = cm.convert_record(r, (100, 50), (100, 200, 500, 350), (1000, 1000), "crop")
    assert d["box"] == [140, 260, 220, 290]
    assert d["area_px"] == 2400
    assert d["id"] == "crop:7"
    assert not d["edge_truncated"]
    assert d["candidate"]


def test_box_raster_size_difference_is_scaled_not_assumed_equal(monkeypatch):
    r = record(monkeypatch, np.ones((5, 10), np.uint8), (10, 20, 30, 30))
    d = cm.convert_record(r, (100, 50), (100, 200, 500, 350), (1000, 1000), "crop")
    assert d["box"] == [140, 260, 220, 290]
    assert d["area_px"] == 2400


def test_internal_crop_boundary_is_not_original_image_boundary(monkeypatch):
    r = record(monkeypatch, np.ones((10, 10), np.uint8), (0, 0, 10, 10))
    d = cm.convert_record(r, (100, 100), (100, 100, 500, 500), (1000, 1000), "crop")
    assert d["crop_boundary"] and not d["image_boundary"]
    d = cm.convert_record(r, (100, 100), (0, 0, 1000, 1000), (1000, 1000), "full")
    assert not d["crop_boundary"] and d["image_boundary"]


def test_outside_input_pixels_are_clipped_before_mapping(monkeypatch):
    r = record(monkeypatch, np.ones((10, 10), np.uint8), (-5, 10, 5, 20))
    d = cm.convert_record(r, (100, 100), (0, 0, 100, 100), (100, 100), "full")
    assert d["box"] == [0, 10, 5, 20]
    assert d["area_px"] == 50
    assert min(p[0] for c in d["contours"] for p in c["points"]) >= 0


@pytest.mark.parametrize("gap", [3, 5])
def test_near_seam_mask_is_not_mistaken_for_complete_tile(monkeypatch, gap):
    # Observed SAM masks stopped 3–5 input pixels before an internal bottom seam.
    r = record(monkeypatch, np.ones((100, 70), np.uint8), (200, 1080 - gap, 270, 1180 - gap))
    d = cm.convert_record(
        r, (1600, 1180), (2887, 901, 4608, 2170), (4608, 3072), "crop"
    )
    assert d["crop_boundary"] and d["edge_truncated"]
    assert not d["image_boundary"]


def test_hole_is_not_counted_as_overlapping_tile(monkeypatch):
    raster = np.ones((100, 100), np.uint8)
    raster[20:80, 20:80] = 0
    r = record(monkeypatch, raster, (100, 100, 200, 200))
    ring = cm.convert_record(r, (400, 400), (0, 0, 400, 400), (400, 400), "r")
    inside = rectangle("inside", [130, 130, 170, 170], run="r2")
    assert any(c["hole"] for c in ring["contours"])
    assert cm.mask_overlap(ring, inside)[0] == 0


def test_shifted_same_tile_is_one_detection_but_adjacent_tiles_survive():
    first = rectangle("a", [0, 0, 50, 50])
    shifted = rectangle("b", [2, 1, 52, 51], run="r2")
    adjacent = rectangle("c", [55, 0, 105, 50])
    kept, diagnostic = cm.merge_detections([first, shifted, adjacent])
    assert len(kept) == 2
    assert any(d["id"] == "c" for d in kept)
    assert diagnostic["suppressed"][0]["reason"] == "mask_overlap"


def test_high_confidence_seam_fragment_does_not_replace_complete_tile():
    full = rectangle("full", [0, 0, 50, 50], confidence=0.55)
    fragment = rectangle("fragment", [0, 0, 10, 50], run="r2", truncated=True, confidence=0.99)
    kept, diagnostic = cm.merge_detections([fragment, full])
    assert [d["id"] for d in kept] == ["full"]
    assert kept[0]["duplicate_ids"] == ["fragment"]
    assert diagnostic["suppressed"][0]["reason"] == "contained_crop_fragment"


def test_broad_spanning_mask_does_not_suppress_two_valid_tile_instances():
    left = rectangle("left", [0, 0, 49, 50], run="fine", confidence=0.6)
    right = rectangle("right", [51, 0, 100, 50], run="fine", confidence=0.6)
    broad = rectangle("broad", [0, 0, 100, 50], run="coarse", confidence=0.99)
    kept, diagnostic = cm.merge_detections([broad, left, right])
    assert {d["id"] for d in kept} == {"left", "right"}
    assert (
        next(r for r in diagnostic["suppressed"] if r["id"] == "broad")["reason"]
        == "spans_multiple_instances"
    )


def test_two_crop_fragments_do_not_falsely_disqualify_full_tile():
    full = rectangle("full", [0, 0, 100, 50], run="coarse")
    left = rectangle("left", [0, 0, 49, 50], run="fine", truncated=True)
    right = rectangle("right", [51, 0, 100, 50], run="fine", truncated=True)
    kept, _ = cm.merge_detections([left, right, full])
    assert [d["id"] for d in kept] == ["full"]


def test_same_bounding_box_with_disjoint_masks_is_not_a_duplicate():
    a = rectangle("a", [0, 0, 100, 100])
    b = rectangle("b", [0, 0, 100, 100], run="r2")
    a["contours"][0]["points"] = [[0, 0], [100, 0], [0, 100]]
    b["contours"][0]["points"] = [[100, 100], [100, 10], [10, 100]]
    kept, _ = cm.merge_detections([a, b])
    assert len(kept) == 2


def test_duplicate_provenance_ids_are_rejected():
    a = rectangle("a", [0, 0, 100, 100])
    with pytest.raises(ValueError, match="unique"):
        cm.merge_detections([a, a])


def test_larger_edge_fragment_wins_when_no_complete_observation_exists():
    large = rectangle("large", [0, 0, 50, 50], run="a", truncated=True, confidence=0.6)
    large["rectangularity"] = 0.9
    fragment = rectangle("fragment", [0, 0, 10, 50], run="b", truncated=True, confidence=0.99)
    kept, _ = cm.merge_detections([fragment, large])
    assert [d["id"] for d in kept] == ["large"]
