"""Pick a real train of evenly spaced bright peaks from the current radial samples.

Every selected crest keeps its own original pixel plus the two darker neighbour
pixels that attest it.  All adjacent crest gaps share one suggested spacing
inside the user's range and the allowed pixel error; at most one gap may be
checked as the doubled spacing with a single missing crest left blank.
"""
from bisect import bisect_left

from image_lab.validation import Invalid, number, object_value


EVIDENCE_LOW = 1
EVIDENCE_HIGH = 254
MIN_PEAKS = 4
EPSILON = 1e-9


def parameters(value):
    body = object_value(value, "波距参数")
    low = number(body.get("spacing_min", 5), "波距下限", .001, 10000)
    high = number(body.get("spacing_max", 100), "波距上限", .001, 10000)
    if high < low:
        raise Invalid("波距上限不能小于下限")
    return {"spacing_min": low, "spacing_max": high,
            "tolerance": number(body.get("tolerance", 2), "允许误差", 0, 500)}


def _sample(point):
    return {"r_px": int(point["r_px"]), "x": int(point["x"]), "y": int(point["y"]),
            "rgb": [int(channel) for channel in point["rgb"]],
            "brightness": float(point["brightness"])}


def _usable(sample):
    return all(EVIDENCE_LOW <= channel <= EVIDENCE_HIGH for channel in sample["rgb"])


def candidates(samples):
    """Local bright peaks whose two darker neighbours are three distinct usable pixels."""
    result = []
    for index in range(1, len(samples) - 1):
        before, centre, after = samples[index - 1:index + 2]
        pixels = {(before["x"], before["y"]), (centre["x"], centre["y"]), (after["x"], after["y"])}
        if len(pixels) != 3 or not all(_usable(item) for item in (before, centre, after)):
            continue
        if centre["brightness"] <= before["brightness"] or centre["brightness"] <= after["brightness"]:
            continue
        result.append({**_sample(centre), "before": _sample(before), "after": _sample(after)})
    return result


def _offer(states, key, fresh):
    count, lo, hi, _ = fresh
    group = states.setdefault(key, [])
    if any(other[0] >= count and other[1] <= lo and other[2] >= hi for other in group):
        return
    group[:] = [other for other in group
                if not (count >= other[0] and lo <= other[1] and hi >= other[2])]
    group.append(fresh)


def _chains(found, params):
    """Pareto states (peak count, spacing low, spacing high, steps); at most one doubled gap."""
    low, high, tolerance = params["spacing_min"], params["spacing_max"], params["tolerance"]
    slots = [peak["r_px"] for peak in found]
    nearest = max(EPSILON, low - tolerance)
    furthest = 2 * high + tolerance
    states = {}
    for index in range(len(found)):
        _offer(states, (index, 0), (1, low, high, ((index, False),)))
    for end in range(len(found)):
        for used in (0, 1):
            incoming = states.get((end, used))
            if not incoming:
                continue
            start = bisect_left(slots, slots[end] + nearest - EPSILON, end + 1)
            stop = bisect_left(slots, slots[end] + furthest + EPSILON, start)
            for count, lo, hi, chain in list(incoming):
                for following in range(start, stop):
                    gap = slots[following] - slots[end]
                    nlo, nhi = max(lo, gap - tolerance), min(hi, gap + tolerance)
                    if nlo <= nhi + EPSILON:
                        _offer(states, (following, used),
                               (count + 1, nlo, nhi, chain + ((following, False),)))
                    if used == 0:
                        nlo, nhi = max(lo, (gap - tolerance) / 2), min(hi, (gap + tolerance) / 2)
                        if nlo <= nhi + EPSILON:
                            _offer(states, (following, 1),
                                   (count + 1, nlo, nhi, chain + ((following, True),)))
    return states


def _spacing(lo, hi, chain, slots):
    """The one suggested spacing inside the surviving interval, nearest the median per-gap estimate."""
    ideals = []
    for previous, current in zip(chain, chain[1:]):
        gap = slots[current[0]] - slots[previous[0]]
        ideals.append(gap / 2 if current[1] else float(gap))
    options = {lo, hi} | {min(hi, max(lo, value)) for value in ideals}
    middle = sorted(ideals)[len(ideals) // 2] if ideals else (lo + hi) / 2

    def cost(value):
        deviations = [abs(slots[current[0]] - slots[previous[0]] - (2 * value if current[1] else value))
                      for previous, current in zip(chain, chain[1:])]
        return (max(deviations, default=0.0), sum(deviations), abs(value - middle))

    return min(options, key=cost)


def _deviations(chain, slots, spacing):
    return [abs(slots[current[0]] - slots[previous[0]] - (2 * spacing if current[1] else spacing))
            for previous, current in zip(chain, chain[1:])]


def _grade(state, slots):
    """Most retained peaks first, then the tightest shared spacing, then fewest doubled gaps."""
    count, lo, hi, chain = state
    spacing = _spacing(lo, hi, chain, slots)
    deviations = _deviations(chain, slots, spacing)
    doubles = sum(1 for item in chain if item[1])
    return (-count, max(deviations, default=0.0), sum(deviations), doubles), spacing


def _detected_gaps(found):
    slots = [peak["r_px"] for peak in found]
    return [second - first for first, second in zip(slots, slots[1:])]


def defaults(samples):
    """A nearby starting range from the median gap between usable bright peaks."""
    gaps = sorted(_detected_gaps(candidates(samples)))
    if len(gaps) < 2:
        return {"spacing_min": 5.0, "spacing_max": 100.0, "tolerance": 2.0}
    middle = gaps[len(gaps) // 2]
    tolerance = max(1.0, round(middle * .08, 1))
    return {"spacing_min": max(.001, round(middle * .85, 1)),
            "spacing_max": round(middle * 1.15, 1), "tolerance": tolerance}


def _blank_gap(found, chain):
    """A doubled gap is only blank when no usable crest sits anywhere strictly inside it."""
    for previous, current in zip(chain, chain[1:]):
        if current[1] and current[0] > previous[0] + 1:
            return False
    return True


def solve(samples, params, locate, scale):
    """Return the adopted train, or an explanation why these samples cannot support one."""
    found = candidates(samples)
    slots = [peak["r_px"] for peak in found]
    base = {"candidate_count": len(found), "parameters": params, "scale_mm_per_px": scale,
            "detected_gaps_px": _detected_gaps(found),
            "candidates": [{key: peak[key] for key in ("r_px", "x", "y", "rgb", "brightness")}
                           for peak in found]}
    low, high, tolerance = params["spacing_min"], params["spacing_max"], params["tolerance"]
    if len(found) < MIN_PEAKS:
        return {**base, "feasible": False,
                "reason": "当前径线上只有 %d 个可用亮峰，不足 %d 个" % (len(found), MIN_PEAKS)}
    states = _chains(found, params)
    ranked = []
    for state in (item for group in states.values() for item in group):
        if state[0] >= MIN_PEAKS and _blank_gap(found, state[3]):
            order, spacing = _grade(state, slots)
            ranked.append((order, spacing, state))
    if not ranked:
        gaps = _detected_gaps(found)
        detail = "；相邻候选峰距实测为 %d–%d px" % (min(gaps), max(gaps)) if gaps else ""
        return {**base, "feasible": False,
                "reason": "在 %.2f–%.2f px 容差 ±%.2f px 内凑不出 %d 个同间距亮峰%s"
                          % (low, high, tolerance, MIN_PEAKS, detail)}
    ranked.sort(key=lambda item: item[0])
    _, spacing, state = ranked[0]
    return _present(base, found, state[3], spacing, locate, scale)


def _present(base, found, chain, spacing, locate, scale):
    tolerance = base["parameters"]["tolerance"]
    peaks, gaps, missing = [], [], []
    for position, (index, doubled) in enumerate(chain):
        peak = found[index]
        entry = {key: peak[key] for key in ("r_px", "x", "y", "rgb", "brightness")}
        entry.update({"number": position + 1, "r_mm": peak["r_px"] * scale,
                      "before": peak["before"], "after": peak["after"]})
        peaks.append(entry)
        if position == 0:
            continue
        left = found[chain[position - 1][0]]
        gap = peak["r_px"] - left["r_px"]
        step = 2 * spacing if doubled else spacing
        row = {"from_peak": position, "to_peak": position + 1,
               "from_r_px": left["r_px"], "to_r_px": peak["r_px"],
               "gap_px": gap, "gap_mm": gap * scale, "step_px": step, "step_mm": step * scale,
               "deviation_px": abs(gap - step), "deviation_mm": abs(gap - step) * scale,
               "double": doubled}
        if doubled:
            expected = left["r_px"] + spacing
            radius = int(round(expected))
            spot = locate(radius)
            x, y = spot if spot else ((left["x"] + peak["x"]) // 2, (left["y"] + peak["y"]) // 2)
            hole = {"after_peak": position, "r_px": radius, "r_mm": radius * scale,
                    "x": x, "y": y,
                    "note": "两倍波距核对：第 %d 与第 %d 峰之间应有一峰，"
                            "但 ±%.2f px 内没有可用亮峰；此处留空，不计峰。"
                            % (position, position + 1, tolerance)}
            row["missing"] = hole
            missing.append(hole)
        gaps.append(row)
    worst = max((row["deviation_px"] for row in gaps), default=0.0)
    return {**base, "feasible": True, "peak_count": len(peaks), "peaks": peaks, "gaps": gaps,
            "missing": missing, "spacing_px": spacing, "spacing_mm": spacing * scale,
            "spacing_min_mm": spacing * scale - tolerance * scale,
            "spacing_max_mm": spacing * scale + tolerance * scale,
            "worst_deviation_px": worst, "worst_deviation_mm": worst * scale,
            "note": "同一波距 %.2f px / %.3f mm 核对了 %d 个原片亮峰；%s" % (
                spacing, spacing * scale, len(peaks),
                "其中一次按两倍波距核对，中间缺峰已留空。" if missing
                else "本次没有两倍间距，全部相邻峰距一致。")}
