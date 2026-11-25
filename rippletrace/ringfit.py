"""Constrained integer-circle fitting for user-confirmed bright-ring points.

The fitting contract is intentionally explicit:

* centers are integer coordinates in the original image;
* the fitted radius stays inside the card's current ``inner``..``outer`` band;
* a point whose original RGB has an exact 0 or 255 channel is never used;
* every adopted point satisfies ``abs(distance - radius) <= tolerance``;
* adopted points must cover all four sign quadrants around the center.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Iterable

import numpy as np

from image_lab.validation import Invalid, integer, list_value, number, object_value, text

EPS = 1e-9
MAX_MARKS = 100
# Small cards and the usual "refine the current center" case are searched
# exactly. Larger feasible boxes use a coarse-to-fine search plus geometric
# seeds so a request cannot spend minutes in Python loops.
EXHAUSTIVE_AREA = 300_000
COARSE_TARGETS = 90_000
SEED_RADIUS = 8

QUADRANTS = ("right_down", "left_down", "left_up", "right_up")
QUADRANT_LABELS = {
    "right_down": "右下 Q1（0°–90°）",
    "left_down": "左下 Q2（90°–180°）",
    "left_up": "左上 Q3（180°–270°）",
    "right_up": "右上 Q4（270°–360°）",
    "axis": "坐标轴上（不计入象限）",
}


def _mark_id(value: Any, index: int, x: int, y: int) -> str:
    raw = value.get("id") if isinstance(value, dict) else None
    if raw is None or raw == "":
        return f"mark-{index + 1}-{x}-{y}"
    return text(raw, "标点编号", 80, False)


def normalize_marks(value: Any, width: int, height: int) -> list[dict[str, Any]]:
    """Validate user marks.  RGB is deliberately not trusted from clients."""
    if value is None:
        return []
    raw_marks = list_value(value, "明纹标点", MAX_MARKS)
    marks: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for index, raw in enumerate(raw_marks):
        item = object_value(raw, f"第{index + 1}个明纹标点")
        x = integer(item.get("x"), f"第{index + 1}个标点 X", 0, width - 1)
        y = integer(item.get("y"), f"第{index + 1}个标点 Y", 0, height - 1)
        tolerance_raw = item.get(
            "tolerance_px",
            item.get("tolerance", item.get("max_error_px", item.get("limit_px", 2))),
        )
        tolerance = number(tolerance_raw, f"第{index + 1}个标点的最大像素差", 0, 1_000_000)
        mark_id = _mark_id(item, index, x, y)
        # Exact duplicate clicks do not represent another physical point.
        # Keep the looser tolerance if the same coordinate is submitted twice.
        key = (x, y)
        if key in seen:
            for existing in marks:
                if (existing["x"], existing["y"]) == key:
                    existing["tolerance_px"] = max(existing["tolerance_px"], tolerance)
                    if item.get("adopted") is not None:
                        existing["adopted"] = bool(item.get("adopted"))
                    break
            continue
        seen.add(key)
        mark = {"id": mark_id, "x": x, "y": y, "tolerance_px": tolerance}
        # Helpful for offline callers; server responses always replace this
        # with the pixels read from the immutable original capture.
        rgb = item.get("rgb", item.get("original_rgb"))
        if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
            try:
                mark["rgb"] = [int(v) for v in rgb]
            except (TypeError, ValueError, OverflowError):
                pass
        if "adopted" in item and not isinstance(item["adopted"], bool):
            raise Invalid("采用状态必须是布尔值")
        if "adopted" in item:
            mark["adopted"] = item["adopted"]
        marks.append(mark)
    return marks


def rgb_is_clipped(rgb: Iterable[int]) -> bool:
    return any(int(channel) == 0 or int(channel) == 255 for channel in rgb)


def read_rgb(image: np.ndarray, x: int, y: int) -> list[int]:
    return [int(v) for v in image[y, x, :3]]


def quadrant_of(cx: int, cy: int, x: int, y: int) -> str:
    if x > cx and y > cy:
        return "right_down"
    if x < cx and y > cy:
        return "left_down"
    if x < cx and y < cy:
        return "left_up"
    if x > cx and y < cy:
        return "right_up"
    return "axis"


def _center_bounds(points: list[dict[str, Any]], outer: int | float,
                   width: int, height: int) -> tuple[int, int, int, int] | None:
    x0, x1 = 0, width - 1
    y0, y1 = 0, height - 1
    for point in points:
        reach = float(outer) + float(point["tolerance_px"])
        # Integer centers c satisfy |c - p| <= reach.  EPS protects exact
        # integral bounds from floating-point representation error.
        x0 = max(x0, math.ceil(point["x"] - reach - EPS))
        x1 = min(x1, math.floor(point["x"] + reach + EPS))
        y0 = max(y0, math.ceil(point["y"] - reach - EPS))
        y1 = min(y1, math.floor(point["y"] + reach + EPS))
        if x0 > x1 or y0 > y1:
            return None
    return x0, x1, y0, y1


def _exact_radius(entries: list[dict[str, Any]], mean_radius: float,
                  inner: int, outer: int) -> float | None:
    """Find a radius satisfying the caller's inequalities with plain floats.

    Interval arithmetic is used for the search, but the final candidate is
    checked with the same ``abs(distance-radius) <= tolerance`` expression
    that callers/tests use.  A few ``nextafter`` steps absorb ulp rounding at
    an exact feasibility boundary.
    """
    low = max(float(inner), max(entry["distance"] - entry["point"]["tolerance_px"]
                                for entry in entries))
    high = min(float(outer), min(entry["distance"] + entry["point"]["tolerance_px"]
                                 for entry in entries))
    if low > high:
        return None

    def valid(radius: float) -> bool:
        if not (float(inner) <= radius <= float(outer)):
            return False
        return all(abs(entry["distance"] - radius) <=
                   float(entry["point"]["tolerance_px"]) for entry in entries)

    start = min(max(mean_radius, low), high)
    attempts = [start, low, high, (low + high) / 2.0]
    radius = start
    for _ in range(32):
        if valid(radius):
            return radius
        need_larger = any(entry["distance"] - radius >
                          float(entry["point"]["tolerance_px"]) for entry in entries)
        need_smaller = any(radius - entry["distance"] >
                           float(entry["point"]["tolerance_px"]) for entry in entries)
        if need_larger == need_smaller:
            break
        radius = math.nextafter(radius, math.inf if need_larger else -math.inf)
        attempts.append(radius)

    # At a singleton boundary the directional walk can start on the wrong side
    # of the interval; explicitly test inward ulps from both ends.
    for boundary, direction in ((low, math.inf), (high, -math.inf)):
        candidate = boundary
        for _ in range(32):
            if valid(candidate):
                return candidate
            candidate = math.nextafter(candidate, direction)
    for candidate in attempts:
        if valid(candidate):
            return candidate
    return None


def _score_center(cx: int, cy: int, points: list[dict[str, Any]],
                  inner: int, outer: int) -> dict[str, Any] | None:
    entries: list[dict[str, Any]] = []
    for point in points:
        distance = math.hypot(point["x"] - cx, point["y"] - cy)
        low = max(float(inner), distance - point["tolerance_px"])
        high = min(float(outer), distance + point["tolerance_px"])
        if low <= high + EPS:
            entries.append({"point": point, "distance": distance, "low": low, "high": high})

    if len(entries) < 4:
        return None

    radius_queries = {float(inner), float(outer)}
    for entry in entries:
        radius_queries.add(entry["low"])
        radius_queries.add(entry["high"])

    best: dict[str, Any] | None = None
    for query in radius_queries:
        members = [entry for entry in entries
                   if entry["low"] - EPS <= query <= entry["high"] + EPS]
        if len(members) < 4:
            continue
        quadrants = {quadrant_of(cx, cy, entry["point"]["x"], entry["point"]["y"])
                     for entry in members}
        if not all(name in quadrants for name in QUADRANTS):
            continue

        mean_radius = sum(entry["distance"] for entry in members) / len(members)
        radius = _exact_radius(members, mean_radius, inner, outer)
        if radius is None:
            continue

        residuals = [entry["distance"] - radius for entry in members]
        abs_errors = [abs(value) for value in residuals]
        sse = sum(value * value for value in residuals)
        rmse = math.sqrt(sse / len(members))
        mae = sum(abs_errors) / len(members)
        max_error = max(abs_errors)
        score = {
            "center_x": int(cx),
            "center_y": int(cy),
            "radius_px": float(radius),
            "adopted": members,
            "adopted_count": len(members),
            "sse_px2": float(sse),
            "rmse_px": float(rmse),
            "mae_px": float(mae),
            "max_error_px": float(max_error),
        }
        if best is None:
            best = score
            continue
        # More adopted real points first; least-squares error second;
        # worst point error third.
        if (score["adopted_count"], -score["sse_px2"], -score["max_error_px"]) > \
           (best["adopted_count"], -best["sse_px2"], -best["max_error_px"]):
            best = score
    return best


def _kasa_center(points: list[dict[str, Any]]) -> tuple[float, float] | None:
    if len(points) < 3:
        return None
    xs = np.array([p["x"] for p in points], dtype=float)
    ys = np.array([p["y"] for p in points], dtype=float)
    matrix = np.column_stack((xs, ys, np.ones_like(xs)))
    rhs = -(xs * xs + ys * ys)
    try:
        coeff, *_ = np.linalg.lstsq(matrix, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return None
    d, e, _ = (float(v) for v in coeff)
    return -d / 2.0, -e / 2.0


def _circumcenter(p1: dict[str, Any], p2: dict[str, Any],
                  p3: dict[str, Any]) -> tuple[float, float] | None:
    x1, y1 = float(p1["x"]), float(p1["y"])
    x2, y2 = float(p2["x"]), float(p2["y"])
    x3, y3 = float(p3["x"]), float(p3["y"])
    determinant = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(determinant) < 1e-10:
        return None
    a1 = x1 * x1 + y1 * y1
    a2 = x2 * x2 + y2 * y2
    a3 = x3 * x3 + y3 * y3
    cx = (a1 * (y2 - y3) + a2 * (y3 - y1) + a3 * (y1 - y2)) / determinant
    cy = (a1 * (x3 - x2) + a2 * (x1 - x3) + a3 * (x2 - x1)) / determinant
    if not (math.isfinite(cx) and math.isfinite(cy)):
        return None
    return cx, cy


def _better(candidate: dict[str, Any], best: dict[str, Any] | None,
            current_center: tuple[int, int] | None) -> bool:
    if best is None:
        return True
    if candidate["adopted_count"] != best["adopted_count"]:
        return candidate["adopted_count"] > best["adopted_count"]
    # Use exact SSE first.  Tiny numerical differences should not cause an
    # unstable choice between effectively identical fits, so round only the
    # comparison key at a much finer scale than a clicked pixel.
    candidate_key = (round(candidate["sse_px2"], 9), round(candidate["max_error_px"], 9),
                     round(candidate["mae_px"], 9))
    best_key = (round(best["sse_px2"], 9), round(best["max_error_px"], 9),
                round(best["mae_px"], 9))
    if candidate_key != best_key:
        return candidate_key < best_key
    if current_center is not None:
        cx0, cy0 = current_center
        movement_new = (candidate["center_x"] - cx0) ** 2 + (candidate["center_y"] - cy0) ** 2
        movement_old = (best["center_x"] - cx0) ** 2 + (best["center_y"] - cy0) ** 2
        if movement_new != movement_old:
            return movement_new < movement_old
    return (candidate["center_x"], candidate["center_y"]) < \
           (best["center_x"], best["center_y"])


def suggest_ring_fit(image: np.ndarray | None, raw_marks: Any, inner: int, outer: int,
                     current_center: tuple[int, int] | None = None,
                     width: int | None = None, height: int | None = None) -> dict[str, Any]:
    """Return the best feasible integer center and constrained radius."""
    if image is not None:
        img_height, img_width = image.shape[:2]
    else:
        if width is None or height is None:
            raise Invalid("拟合需要原片尺寸")
        img_width, img_height = int(width), int(height)

    inner = integer(inner, "内半径", 1)
    outer = integer(outer, "外半径", inner)
    marks = normalize_marks(raw_marks, img_width, img_height)

    annotated: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for mark in marks:
        if image is not None:
            rgb = read_rgb(image, mark["x"], mark["y"])
        else:
            rgb = mark.get("rgb", [])
        clipped = bool(rgb) and rgb_is_clipped(rgb)
        item = {**mark, "rgb": rgb, "original_rgb": list(rgb), "rgb_clipped": clipped,
                "clipped": clipped, "usable": not clipped, "eligible": not clipped}
        annotated.append(item)
        if not clipped:
            eligible.append(item)

    bounds = _center_bounds(eligible, outer, img_width, img_height) if eligible else None
    if bounds is None:
        # An outlier must not be allowed to make the search region empty.
        bounds = (0, img_width - 1, 0, img_height - 1)
        bounds_fallback = True
    else:
        bounds_fallback = False
    best: dict[str, Any] | None = None
    searched = 0
    candidate_mode = "exact-grid"

    x0, x1, y0, y1 = bounds
    area = (x1 - x0 + 1) * (y1 - y0 + 1)

    def consider(cx: int, cy: int) -> None:
        nonlocal best, searched
        if not (0 <= cx < img_width and 0 <= cy < img_height):
            return
        searched += 1
        candidate = _score_center(cx, cy, eligible, inner, outer)
        if candidate is not None and _better(candidate, best, current_center):
            best = candidate

    coarse_neighborhoods: set[tuple[int, int]] = set()
    if area <= EXHAUSTIVE_AREA and not bounds_fallback:
        for cy in range(y0, y1 + 1):
            for cx in range(x0, x1 + 1):
                consider(cx, cy)
    elif area <= EXHAUSTIVE_AREA and bounds_fallback and img_width * img_height <= EXHAUSTIVE_AREA:
        # The all-point annulus bound failed, but the whole small image is cheap.
        for cy in range(img_height):
            for cx in range(img_width):
                consider(cx, cy)
    else:
        candidate_mode = "coarse-to-fine+geometric-seeds"
        step = max(2, math.ceil(math.sqrt(area / COARSE_TARGETS)))
        coarse: list[dict[str, Any]] = []
        for cy in range(y0, y1 + 1, step):
            for cx in range(x0, x1 + 1, step):
                searched += 1
                candidate = _score_center(cx, cy, eligible, inner, outer)
                if candidate is not None:
                    coarse.append(candidate)
                    if best is None or _better(candidate, best, current_center):
                        best = candidate
        coarse.sort(key=lambda c: (-c["adopted_count"], c["sse_px2"], c["max_error_px"]))
        local_radius = max(2, (step + 1) // 2 + 1)
        for candidate in coarse[:30]:
            ccx, ccy = candidate["center_x"], candidate["center_y"]
            for dy in range(-local_radius, local_radius + 1):
                for dx in range(-local_radius, local_radius + 1):
                    coarse_neighborhoods.add((ccx + dx, ccy + dy))

    # Geometric seeds rescue the search when an unadopted outlier narrowed the
    # all-point square bounds away from the circle supported by the inliers.
    seed_centers: set[tuple[int, int]] = set(coarse_neighborhoods)
    seeds: list[tuple[float, float]] = []
    if current_center is not None:
        seeds.append((float(current_center[0]), float(current_center[1])))
    if eligible:
        seeds.append((sum(p["x"] for p in eligible) / len(eligible),
                      sum(p["y"] for p in eligible) / len(eligible)))
        kasa = _kasa_center(eligible)
        if kasa is not None:
            seeds.append(kasa)
    if 3 <= len(eligible) <= 18:
        for p1, p2, p3 in combinations(eligible, 3):
            seed = _circumcenter(p1, p2, p3)
            if seed is not None:
                seeds.append(seed)
    seed_radius = max(SEED_RADIUS, math.ceil(max(
        (float(p["tolerance_px"]) for p in eligible), default=0)) + 2)
    seed_radius = min(seed_radius, 16)
    for sx, sy in seeds:
        if not (math.isfinite(sx) and math.isfinite(sy)):
            continue
        ix, iy = round(sx), round(sy)
        for dy in range(-seed_radius, seed_radius + 1):
            for dx in range(-seed_radius, seed_radius + 1):
                seed_centers.add((ix + dx, iy + dy))
    for cx, cy in seed_centers:
        consider(cx, cy)

    result_points = _annotate_results(annotated, best, inner, outer)
    quadrant_summary = _quadrant_summary(best, result_points)

    if best is None:
        return {
            "feasible": False,
            "success": False,
            "center_x": None,
            "center_y": None,
            "radius_px": None,
            "inner": inner,
            "outer": outer,
            "width": img_width,
            "height": img_height,
            "marked_count": len(marks),
            "eligible_count": len(eligible),
            "excluded_count": len(marks) - len(eligible),
            "adopted_count": 0,
            "used_count": 0,
            "points": result_points,
            "quadrants": quadrant_summary,
            "searched_centers": searched,
            "search_mode": candidate_mode,
            "message": "找不到同时满足径段、容差和四象限覆盖的整数圆心。",
        }

    adopted_ids = {entry["point"]["id"] for entry in best["adopted"]}
    return {
        "feasible": True,
        "success": True,
        "center_x": best["center_x"],
        "center_y": best["center_y"],
        "center": [best["center_x"], best["center_y"]],
        "radius_px": best["radius_px"],
        "radius": best["radius_px"],
        "radius_round_px": int(min(outer, max(inner, math.floor(best["radius_px"] + 0.5)))),
        "inner": inner,
        "outer": outer,
        "width": img_width,
        "height": img_height,
        "marked_count": len(marks),
        "eligible_count": len(eligible),
        "excluded_count": len(marks) - len(eligible),
        "adopted_count": best["adopted_count"],
        "used_count": best["adopted_count"],
        "rmse_px": best["rmse_px"],
        "mae_px": best["mae_px"],
        "max_error_px": best["max_error_px"],
        "sse_px2": best["sse_px2"],
        "error_px": best["rmse_px"],
        "points": result_points,
        "adopted_ids": sorted(adopted_ids),
        "quadrants": quadrant_summary,
        "searched_centers": searched,
        "search_mode": candidate_mode,
        "message": (f"建议圆心 ({best['center_x']}, {best['center_y']})，"
                    f"拟合半径 {best['radius_px']:.2f} px，"
                    f"采用 {best['adopted_count']} 点。"),
    }


def _annotate_results(annotated: list[dict[str, Any]], best: dict[str, Any] | None,
                      inner: int, outer: int) -> list[dict[str, Any]]:
    adopted_by_id: dict[str, dict[str, Any]] = {}
    if best is not None:
        for entry in best["adopted"]:
            adopted_by_id[entry["point"]["id"]] = entry

    result: list[dict[str, Any]] = []
    for item in annotated:
        x, y = item["x"], item["y"]
        row = {key: value for key, value in item.items() if key != "adopted"}
        row.update({
            "marked": True,
            "inner": inner,
            "outer": outer,
            "adopted": False,
            "used": False,
            "accepted": False,
            "within_tolerance": False,
            "distance_px": None,
            "fit_distance_px": None,
            "radius_px": best["radius_px"] if best else None,
            "radius_delta_px": None,
            "delta_px": None,
            "signed_radius_difference_px": None,
            "signed_radius_diff_px": None,
            "radius_difference_px": None,
            "radius_diff_px": None,
            "difference_px": None,
            "absolute_difference_px": None,
            "absolute_radius_difference_px": None,
            "abs_radius_difference_px": None,
            "radius_error_px": None,
            "quadrant": None,
            "axis": False,
            "reject_reason": None,
        })
        if item["rgb_clipped"]:
            row["reject_reason"] = "rgb_endpoint"
            result.append(row)
            continue

        if best is None:
            row["reject_reason"] = "no_feasible_fit"
            result.append(row)
            continue

        cx, cy = best["center_x"], best["center_y"]
        distance = math.hypot(x - cx, y - cy)
        delta = distance - best["radius_px"]
        error = abs(delta)
        tolerance = float(item["tolerance_px"])
        quadrant = quadrant_of(cx, cy, x, y)
        within = error <= tolerance
        fit_entry = adopted_by_id.get(item["id"])
        adopted = fit_entry is not None and within
        row.update({
            "quadrant": quadrant,
            "axis": quadrant == "axis",
            "distance_px": distance,
            "fit_distance_px": distance,
            "radius_delta_px": delta,
            "delta_px": delta,
            "signed_radius_difference_px": delta,
            "signed_radius_diff_px": delta,
            "radius_difference_px": error,
            "radius_diff_px": error,
            "difference_px": error,
            "absolute_difference_px": error,
            "absolute_radius_difference_px": error,
            "abs_radius_difference_px": error,
            "radius_error_px": error,
            "within_tolerance": within,
            "adopted": adopted,
            "used": adopted,
            "accepted": adopted,
            "reject_reason": None if adopted else "radius_tolerance",
        })
        result.append(row)
    return result


def _quadrant_summary(best: dict[str, Any] | None,
                      points: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in (*QUADRANTS, "axis")}
    cx = best["center_x"] if best else None
    cy = best["center_y"] if best else None
    for point in points:
        if not point.get("adopted") or cx is None or cy is None:
            continue
        name = quadrant_of(cx, cy, point["x"], point["y"])
        groups[name].append({"id": point["id"], "x": point["x"], "y": point["y"]})

    summary: dict[str, Any] = {}
    covered = True
    counts = []
    for name in QUADRANTS:
        summary[name] = {
            "label": QUADRANT_LABELS[name],
            "count": len(groups[name]),
            "points": groups[name],
            "covered": bool(groups[name]),
        }
        counts.append(len(groups[name]))
        covered = covered and bool(groups[name])
    summary["axis"] = {"label": QUADRANT_LABELS["axis"], "count": len(groups["axis"]),
                       "points": groups["axis"], "covered": None}
    summary["counts"] = counts
    summary["all_covered"] = covered
    summary["complete"] = covered
    return summary


def normalize_fit(value: Any, width: int, height: int,
                  inner: int | None = None, outer: int | None = None) -> dict[str, Any] | None:
    """Validate a persisted suggestion/adoption without recomputing it."""
    if value is None:
        return None
    item = object_value(value, "明纹拟合结果")
    center = item.get("center")
    cx_raw = item.get("center_x", center[0] if isinstance(center, (list, tuple)) and center else None)
    cy_raw = item.get("center_y", center[1] if isinstance(center, (list, tuple)) and len(center) > 1 else None)
    cx = integer(cx_raw, "拟合圆心 X", 0, width - 1)
    cy = integer(cy_raw, "拟合圆心 Y", 0, height - 1)
    radius_raw = item.get("radius_px", item.get("radius"))
    radius = number(radius_raw, "拟合半径", 0, math.hypot(width - 1, height - 1))
    if inner is not None and radius + 1e-8 < inner:
        raise Invalid("拟合半径不在现有径段内")
    if outer is not None and radius - 1e-8 > outer:
        raise Invalid("拟合半径不在现有径段内")
    # Normalize through JSON-safe Python values and ensure required aliases.
    fit = dict(item)
    fit.update({"center_x": cx, "center_y": cy, "center": [cx, cy],
                "radius_px": radius, "radius": radius,
                "feasible": bool(item.get("feasible", True))})
    if "points" in fit and not isinstance(fit["points"], list):
        raise Invalid("拟合标点结果必须是列表")
    return fit


def evaluate_probe(rgb: list[int], x: int, y: int, config: dict[str, Any],
                   marks: list[dict[str, Any]] | None = None,
                   fit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add mark/adoption information to the normal source-pixel probe."""
    cx = int(config["center_x"])
    cy = int(config["center_y"])
    distance = math.hypot(x - cx, y - cy)
    clipped = rgb_is_clipped(rgb)
    mark = None
    if marks:
        for candidate in marks:
            if int(candidate["x"]) == x and int(candidate["y"]) == y:
                mark = candidate
                break

    result: dict[str, Any] = {
        "rgb": list(rgb),
        "original_rgb": list(rgb),
        "marked": mark is not None,
        "mark": None,
        "adopted": None,
        "used": None,
        "accepted": None,
        "rgb_clipped": clipped,
        "clipped": clipped,
        "rgb_endpoint_excluded": clipped,
        "fit_radius_px": None,
        "radius_px": None,
        "fit_distance_px": None,
        "radius_delta_px": None,
        "delta_px": None,
        "signed_radius_difference_px": None,
        "signed_radius_diff_px": None,
        "radius_difference_px": None,
        "radius_diff_px": None,
        "difference_px": None,
        "absolute_difference_px": None,
        "absolute_radius_difference_px": None,
        "abs_radius_difference_px": None,
        "radius_error_px": None,
        "tolerance_px": None,
        "quadrant": quadrant_of(cx, cy, x, y),
    }
    result["axis"] = result["quadrant"] == "axis"

    if mark is None:
        return result

    mark_id = str(mark.get("id", ""))
    fit_point = None
    if fit and isinstance(fit.get("points"), list):
        for candidate in fit["points"]:
            if (mark_id and str(candidate.get("id", "")) == mark_id) or \
               (int(candidate.get("x", -1)) == x and int(candidate.get("y", -1)) == y):
                fit_point = candidate
                break

    tolerance = mark.get("tolerance_px")
    if tolerance is None and fit_point is not None:
        tolerance = fit_point.get("tolerance_px")
    if tolerance is not None:
        result["tolerance_px"] = float(tolerance)

    radius = None
    fit_cx, fit_cy = cx, cy
    if fit and fit.get("radius_px") is not None:
        radius = float(fit["radius_px"])
        if fit.get("center_x") is not None and fit.get("center_y") is not None:
            fit_cx, fit_cy = int(fit["center_x"]), int(fit["center_y"])
    elif fit_point is not None and fit_point.get("radius_px") is not None:
        radius = float(fit_point["radius_px"])

    fit_distance = math.hypot(x - fit_cx, y - fit_cy)
    result["fit_distance_px"] = fit_distance
    if radius is not None:
        delta = fit_distance - radius
        error = abs(delta)
        result.update({
            "fit_radius_px": radius,
            "radius_px": radius,
            "radius_delta_px": delta,
            "delta_px": delta,
            "signed_radius_difference_px": delta,
            "signed_radius_diff_px": delta,
            "radius_difference_px": error,
            "radius_diff_px": error,
            "difference_px": error,
            "absolute_difference_px": error,
            "absolute_radius_difference_px": error,
            "abs_radius_difference_px": error,
            "radius_error_px": error,
        })
        if tolerance is not None:
            result["within_tolerance"] = error <= float(tolerance)

    adopted: bool | None
    if clipped:
        adopted = False
        result["reject_reason"] = "rgb_endpoint"
    elif fit_point is not None:
        adopted = bool(fit_point.get("adopted", fit_point.get("used", False)))
        if not adopted and fit_point.get("reject_reason"):
            result["reject_reason"] = fit_point["reject_reason"]
    elif "adopted" in mark:
        adopted = bool(mark["adopted"])
    else:
        adopted = None

    if adopted is not None and result.get("within_tolerance") is False:
        # A changed tolerance can make a stored adoption stale; report the
        # mathematical truth rather than a stale label.
        adopted = False
        result["reject_reason"] = result.get("reject_reason") or "radius_tolerance"

    result["adopted"] = adopted
    result["used"] = adopted
    result["accepted"] = adopted
    result["mark"] = {**mark, "rgb": rgb, "original_rgb": list(rgb),
                      "rgb_clipped": clipped}
    return result
