"""Read actual source pixels and peak positions in a photographed ripple field."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer, number

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
ANGLE_INTERVAL = 5
TRACE_ANGLE_STEP = 5
TRACE_MAX_TURN = 90
TRACE_MAX_RADIUS_STEP = 2
MIN_FOLLOW_DIRECTIONS = 3


def settings(value, size):
    width, height = size
    max_radius = math.ceil(math.hypot(width - 1, height - 1))
    inner = integer(value.get("inner"), "内半径", 1, max_radius)
    return {
        "center_x": integer(value.get("center_x"), "中心 X", 0, width - 1),
        "center_y": integer(value.get("center_y"), "中心 Y", 0, height - 1),
        "inner": inner, "outer": integer(value.get("outer"), "外半径", inner, max_radius),
        "angle": integer(value.get("angle"), "方向角度", 0, 359),
        "mm_per_px": number(value.get("mm_per_px"), "标尺", 0.001, 500),
    }


def defaults(size):
    width, height = size
    return settings({"center_x": width // 2, "center_y": height // 2, "inner": 12,
                     "outer": max(12, min(width, height) // 3), "angle": 0, "mm_per_px": 1}, size)


def point(image, x, y, config):
    rgb = image[y, x]
    dx = x - config["center_x"]
    dy = y - config["center_y"]
    radius = math.hypot(dx, dy)
    return {"x": x, "y": y, "rgb": rgb.tolist(), "brightness": float(rgb @ LUMA),
            "distance_px": radius, "distance_mm": radius * config["mm_per_px"]}


def source_ray(image, config, angle):
    height, width = image.shape[:2]
    radians = math.radians(angle)
    radii = np.arange(config["inner"], config["outer"] + 1)
    xs = np.floor(config["center_x"] + radii * math.cos(radians) + 0.5).astype(int)
    ys = np.floor(config["center_y"] + radii * math.sin(radians) + 0.5).astype(int)
    inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    return radii[inside], xs[inside], ys[inside]


def peak(image, config, angle):
    radii, xs, ys = source_ray(image, config, angle)
    if not len(radii):
        return None
    scores = image[ys, xs] @ LUMA
    index = int(np.argmax(scores))
    radius = int(radii[index])
    return {"r_px": radius, "r_mm": radius * config["mm_per_px"],
            "x": int(xs[index]), "y": int(ys[index]), "brightness": float(scores[index])}


def radial_source(image, config, angle, radius):
    """Return the one nearest source pixel for an integer radius step."""
    height, width = image.shape[:2]
    radians = math.radians(angle)
    x = int(math.floor(config["center_x"] + radius * math.cos(radians) + 0.5))
    y = int(math.floor(config["center_y"] + radius * math.sin(radians) + 0.5))
    if not (0 <= x < width and 0 <= y < height):
        return None
    rgb = [int(channel) for channel in image[y, x]]
    brightness = float(np.asarray(rgb, dtype="float64") @ LUMA)
    return {"angle": int(angle) % 360, "r_px": int(radius),
            "r_mm": float(radius * config["mm_per_px"]),
            "x": x, "y": y, "rgb": rgb, "brightness": brightness}


def evaluate_local_peak(image, config, angle, radius):
    """Validate a radius step against its two actual radial source pixels."""
    radius = int(radius)
    left = radial_source(image, config, angle, radius - 1)
    center = radial_source(image, config, angle, radius)
    right = radial_source(image, config, angle, radius + 1)
    result = {"angle": int(angle) % 360, "r_px": radius, "valid": False,
              "peak": None, "left": left, "right": right, "reasons": []}
    if center is None or left is None or right is None:
        result["reasons"].append("outside_source_image")
        return result
    result["peak"] = center
    coordinates = {(point["x"], point["y"]) for point in (left, center, right)}
    if len(coordinates) != 3:
        result["reasons"].append("source_pixels_not_distinct")
    clipped = any(channel in (0, 255)
                  for point in (left, center, right) for channel in point["rgb"])
    result["clipped"] = clipped
    if clipped:
        result["reasons"].append("rgb_limit")
    if not (center["brightness"] > left["brightness"]
            and center["brightness"] > right["brightness"]):
        result["reasons"].append("not_local_peak")
    result["left_ratio"] = center["brightness"] / max(left["brightness"], 1e-12)
    result["right_ratio"] = center["brightness"] / max(right["brightness"], 1e-12)
    result["both_ratio"] = min(result["left_ratio"], result["right_ratio"])
    result["peak_ratio"] = result["both_ratio"]
    result["peak_to_side_ratio"] = result["both_ratio"]
    result["left_margin"] = center["brightness"] - left["brightness"]
    result["right_margin"] = center["brightness"] - right["brightness"]
    result["min_margin"] = min(result["left_margin"], result["right_margin"])
    result["contrast"] = result["min_margin"]
    if not result["reasons"]:
        result["valid"] = True
        result.update(center)
    return result


def local_peak(image, config, angle, radius):
    checked = evaluate_local_peak(image, config, angle, radius)
    return _peak_summary(checked) if checked["valid"] else None


def _peak_summary(checked):
    peak = dict(checked["peak"])
    peak.update({
        "valid": True,
        "left": checked["left"], "right": checked["right"],
        "left_ratio": checked["left_ratio"], "right_ratio": checked["right_ratio"],
        "peak_ratio": checked["both_ratio"], "both_ratio": checked["both_ratio"],
        "peak_to_side_ratio": checked["both_ratio"],
        "left_margin": checked["left_margin"], "right_margin": checked["right_margin"],
        "contrast": checked["min_margin"], "min_margin": checked["min_margin"],
        "side_contrast": checked["min_margin"],
        "clipped": False,
    })
    return peak


def local_peaks(image, config, angle):
    peaks = []
    # The candidate itself must be in the configured radial window.  Its two
    # comparison steps are still read directly from the original image, even
    # when one lies immediately beyond a window boundary.
    for radius in range(config["inner"], config["outer"] + 1):
        checked = evaluate_local_peak(image, config, angle, radius)
        if checked["valid"]:
            peaks.append(_peak_summary(checked))
    return peaks


def _path_key(state):
    ratios = [node["peak_ratio"] for node in state["nodes"]]
    margins = [node["contrast"] for node in state["nodes"]]
    # Longer continuity is primary; on equal reach use the weaker side's
    # ratio and then total ratio/contrast.  This avoids choosing a ring merely
    # because one side happens to be very dark.
    return (len(state["nodes"]), min(ratios), sum(math.log(r) for r in ratios),
            min(margins), sum(margins))


def trace_ripple(image, config, start_radius=None, angle=None, **options):
    """Follow one contiguous local-peak trail clockwise in 5 degree steps."""
    if start_radius is None:
        start_radius = options.get("r_px", options.get("radius",
                       options.get("start_r", options.get("start",
                       options.get("seed_radius", options.get("seed",
                       options.get("anchor_radius", options.get("start_r_px",
                       config.get("trace_radius")))))))))
    if start_radius is None:
        current = peak(image, config, config["angle"])
        if current is None:
            start_radius = config["inner"]
        else:
            start_radius = current["r_px"]
    start_radius = int(start_radius)
    start_angle = int(config["angle"] if angle is None else angle) % 360
    step_degrees = int(options.get("step_degrees", TRACE_ANGLE_STEP))
    max_turn = int(options.get("max_turn", TRACE_MAX_TURN))
    max_radius_step = int(options.get("max_radius_step", TRACE_MAX_RADIUS_STEP))
    max_steps = max_turn // step_degrees

    anchor_check = evaluate_local_peak(image, config, start_angle, start_radius)
    anchor = _peak_summary(anchor_check) if anchor_check["valid"] else None
    start_source = radial_source(image, config, start_angle, start_radius)
    start_slot = {"angle": start_angle, "turn_deg": 0, "step_index": 0,
                  "r_px": start_radius, "radius": start_radius,
                  "peak": anchor, "source": start_source}

    layers = [{
        "radius": start_radius,
        "nodes": [],
        "slots": [start_slot],
    }]
    best_by_length = {}
    all_paths = []

    for step_index in range(1, max_steps + 1):
        turn = step_index * step_degrees
        angle = (start_angle + turn) % 360
        peaks = local_peaks(image, config, angle)
        next_layer = []
        for old in layers:
            for candidate in peaks:
                if abs(candidate["r_px"] - old["radius"]) > max_radius_step:
                    continue
                node = dict(candidate)
                node.update({"turn_deg": turn, "step_index": step_index})
                slot = {"angle": angle, "turn_deg": turn,
                        "step_index": step_index,
                        "r_px": node["r_px"], "radius": node["r_px"],
                        "peak": node, "source": {key: node[key] for key in
                                                 ("angle", "r_px", "r_mm", "x", "y",
                                                  "rgb", "brightness")}}
                next_layer.append({"radius": node["r_px"],
                                   "nodes": old["nodes"] + [node],
                                   "slots": old["slots"] + [slot]})
        if not next_layer:
            break

        # Several histories can reach the same radius at this same angle.
        # Only the best history can be relevant to identical future choices.
        by_radius = {}
        for state in next_layer:
            old = by_radius.get(state["radius"])
            if old is None or _path_key(state)[1:] > _path_key(old)[1:]:
                by_radius[state["radius"]] = state
        layers = list(by_radius.values())
        for state in layers:
            length = len(state["nodes"])
            old_best = best_by_length.get(length)
            if old_best is None or _path_key(state) > _path_key(old_best):
                best_by_length[length] = state

    for length, state in best_by_length.items():
        if length >= MIN_FOLLOW_DIRECTIONS:
            all_paths.append(_suggestion_from_state(start_angle, start_radius,
                                                     start_slot, state, step_degrees))
    all_paths.sort(key=_suggestion_rank, reverse=True)
    suggestion = all_paths[0] if all_paths else None

    selected_state = None
    if suggestion is not None:
        selected_state = next(state for length, state in best_by_length.items()
                              if length == suggestion["followed_directions"]
                              and state["slots"] == suggestion["steps"])
    elif best_by_length:
        longest = max(best_by_length)
        selected_state = best_by_length[longest]

    directions = [_empty_direction(start_angle, 0, 0)] * (max_steps + 1)
    directions[0] = start_slot
    if selected_state is not None:
        for slot in selected_state["slots"][1:]:
            directions[slot["step_index"]] = slot
    for index in range(max_steps + 1):
        if directions[index].get("step_index") != index:
            turn = index * step_degrees
            directions[index] = _empty_direction(
                (start_angle + turn) % 360, turn, index)

    followed = len(selected_state["nodes"]) if selected_state else 0
    return {
        "start_angle": start_angle,
        "angle": start_angle,
        "focus": start_angle,
        "start_r_px": start_radius,
        "r_px": start_radius,
        "radius": start_radius,
        "angle_step_deg": step_degrees,
        "max_turn_deg": max_turn,
        "max_radius_step_px": max_radius_step,
        "minimum_follow_directions": MIN_FOLLOW_DIRECTIONS,
        "anchor": anchor,
        "start": start_slot,
        "angles": [item["angle"] for item in directions],
        "angular": directions,
        "peaks": [item["peak"] for item in directions],
        "radius_series": [item["r_px"] for item in directions],
        "directions": directions,
        "slots": directions,
        "followed_directions": followed,
        "followed": followed,
        "can_suggest": suggestion is not None,
        "suggestion": suggestion,
        "recommendation": suggestion,
        "trace": suggestion,
        "best": suggestion,
        "tracked_trace": suggestion,
        "paths": all_paths,
        "alternatives": all_paths[1:],
        "points": suggestion["points"] if suggestion is not None else
                  [slot["peak"] for slot in directions if slot.get("peak")],
        "radii": suggestion["radii"] if suggestion is not None else
                 [slot["r_px"] for slot in directions if slot.get("peak")],
    }


def _empty_direction(angle, turn, index):
    return {"angle": int(angle) % 360, "turn_deg": turn, "step_index": index,
            "r_px": None, "radius": None, "peak": None, "source": None}


def _suggestion_from_state(start_angle, start_radius, start_slot, state, step_degrees):
    nodes = state["nodes"]
    slots = state["slots"]
    ratios = [node["peak_ratio"] for node in nodes]
    return {
        "adoptable": len(nodes) >= MIN_FOLLOW_DIRECTIONS,
        "start_angle": start_angle,
        "angle_start": start_angle,
        "start_r_px": start_radius,
        "r_px_start": start_radius,
        "angle_step_deg": step_degrees,
        "followed_directions": len(nodes),
        "followed": len(nodes),
        "subsequent_directions": len(nodes),
        "point_count": len(slots),
        "turn_degrees": len(nodes) * step_degrees,
        "length_deg": len(nodes) * step_degrees,
        "angles": [slot["angle"] for slot in slots],
        "radii": [start_radius] + [node["r_px"] for node in nodes],
        "r_px_values": [start_radius] + [node["r_px"] for node in nodes],
        "steps": slots,
        "directions": slots,
        "tracked": slots,
        "chain": [start_radius] + [node["r_px"] for node in nodes],
        "points": [peak for peak in [start_slot.get("peak")] + nodes if peak],
        "track_points": nodes,
        "peak_ratio_min": min(ratios),
        "peak_ratio_geomean": math.exp(sum(math.log(r) for r in ratios) / len(ratios)),
        "score": _path_key(state),
    }


def _suggestion_rank(suggestion):
    return tuple(suggestion["score"])


# Common descriptive aliases used by callers and tests.
trace = trace_ripple
follow = trace_ripple
track = trace_ripple
suggest_trace = trace_ripple
find_trace = trace_ripple
follow_ripple = trace_ripple
track_ripple = trace_ripple
suggest_ripple_trace = trace_ripple
ripple_trace = trace_ripple


def profile(image, config):
    radii, xs, ys = source_ray(image, config, config["angle"])
    result = []
    for radius, x, y in zip(radii, xs, ys):
        point_data = point(image, int(x), int(y), config)
        result.append({"r_px": int(radius), **point_data})
    return result


def report(image, config, angle=None, trace_radius=None):
    focus = config["angle"] if angle is None else int(angle) % 360
    focus_config = {**config, "angle": focus}
    result = {
        "reading": peak(image, focus_config, focus),
        "profile": profile(image, focus_config),
        "angular": [{"angle": item_angle, "peak": peak(image, config, item_angle)}
                    for item_angle in range(0, 360, ANGLE_INTERVAL)],
        "focus": focus,
    }
    if trace_radius is not None:
        result["trace"] = trace_ripple(image, focus_config, trace_radius, angle=focus)
    return result


def practice():
    width, height = 774, 468
    cfg = settings({"center_x": 385, "center_y": 236, "inner": 28, "outer": 184,
                    "angle": 0, "mm_per_px": 0.35}, (width, height))
    y, x = np.indices((height, width))
    dx = x - cfg["center_x"]
    dy = y - cfg["center_y"]
    r = np.hypot(dx, dy)
    u = dx / np.maximum(r, 1)
    v = dy / np.maximum(r, 1)
    noise = 2.2 * np.sin(0.1 * x + 0.18 * y) + 1.5 * np.sin(0.67 * x - 0.41 * y)
    waves = np.zeros_like(r)
    for pos, amp in ((37, 29 + 6 * v), (69, 38 + 8 * u), (101, 54 + 23 * u),
                     (137, 55 + 27 * v), (172, 33 + 12 * v)):
        waves += amp * np.exp(-((r - pos) / 2.6) ** 2)
        waves -= 9 * np.exp(-((r - pos - 5) / 3.4) ** 2)
    scatter = -17 * np.exp(-((dx + 173) / 63) ** 2 - ((dy + 47) / 32) ** 2)
    tonal = 60 + 11 * np.exp(-(r / 164)**2) + noise + waves + scatter
    photo = Image.fromarray((tonal[..., None] + np.array([-12, 1, 27])).clip(0, 255).astype("uint8"), "RGB")
    draw = ImageDraw.Draw(photo)
    draw.text((37, 31), "OVERHEAD RIPPLE LIGHT BANDS", fill="#bdd5e4", font=ImageFont.load_default(size=14))
    draw.text((38, 432), "SIMULATED WATER PHOTO", fill="#b3c7da", font=ImageFont.load_default(size=12))
    draw.line((570, 429, 630, 429), fill="#d3e9f1", width=2)
    for ix in (570, 600, 630):
        draw.line((ix, 429, ix, 421), fill="#d3e9f1", width=2)
    draw.text((639, 423), "21 mm", fill="#d3e9f1", font=ImageFont.load_default(size=11))
    return photo.size, png(photo), cfg
