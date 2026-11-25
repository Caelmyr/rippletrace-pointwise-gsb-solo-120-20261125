"""Read actual source pixels and peak positions in a photographed ripple field."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer, number

from . import ringfit
from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126, 0.7152, 0.0722])
ANGLE_INTERVAL = 5


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


def point(image, x, y, config, marks=None, fit=None):
    rgb = image[y, x]
    dx = x - config["center_x"]
    dy = y - config["center_y"]
    radius = math.hypot(dx, dy)
    result = {"x": x, "y": y, "rgb": rgb.tolist(),
              "original_rgb": rgb.tolist(),
              "brightness": float(rgb @ LUMA),
              "distance_px": radius, "distance_mm": radius * config["mm_per_px"]}
    if marks is not None or fit is not None:
        result.update(ringfit.evaluate_probe(
            result["rgb"], x, y, config, marks or [], fit))
    return result


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


def profile(image, config):
    radii, xs, ys = source_ray(image, config, config["angle"])
    result = []
    for radius, x, y in zip(radii, xs, ys):
        point_data = point(image, int(x), int(y), config)
        result.append({"r_px": int(radius), **point_data})
    return result


def report(image, config):
    return {
        "reading": peak(image, config, config["angle"]),
        "profile": profile(image, config),
        "angular": [{"angle": angle, "peak": peak(image, config, angle)}
                    for angle in range(0, 360, ANGLE_INTERVAL)],
        "focus": config["angle"],
    }


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
