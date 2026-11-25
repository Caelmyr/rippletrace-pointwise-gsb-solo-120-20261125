"""Export actual measurements and their original water image."""
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image, ImageDraw

from .photo import png


def trace_table(result):
    target = StringIO()
    writer = csv.writer(target)
    writer.writerow(("r_px", "x_px", "y_px", "red", "green", "blue", "luma"))
    for point in result["profile"]:
        writer.writerow((point["r_px"], point["x"], point["y"], *point["rgb"], f'{point["brightness"]:.3f}'))
    return target.getvalue().encode()


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(430, width), height + 64), "#101e34")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    cx, cy = cfg["center_x"], cfg["center_y"]
    for radius in (cfg["inner"], cfg["outer"]):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#669aad", width=1)
    draw.line((cx - 5, cy, cx + 5, cy), fill="#b5ebcc", width=2)
    draw.line((cx, cy - 5, cx, cy + 5), fill="#b5ebcc", width=2)
    fit = card.get("ring_fit") if isinstance(card, dict) else None
    if fit and fit.get("feasible") and fit.get("radius_px") is not None:
        fcx = int(fit.get("center_x", cx))
        fcy = int(fit.get("center_y", cy))
        fit_radius = float(fit["radius_px"])
        draw.ellipse((fcx - fit_radius, fcy - fit_radius,
                      fcx + fit_radius, fcy + fit_radius),
                     outline="#ffd166", width=2)
        draw.line((fcx - 7, fcy, fcx + 7, fcy), fill="#ffd166", width=1)
        draw.line((fcx, fcy - 7, fcx, fcy + 7), fill="#ffd166", width=1)
    fit_points = {
        (int(point["x"]), int(point["y"])): point
        for point in (fit or {}).get("points", [])
        if isinstance(point, dict) and "x" in point and "y" in point
    }
    marks = card.get("ring_marks", []) if isinstance(card, dict) else []
    for index, mark in enumerate(marks, 1):
        x, y = int(mark["x"]), int(mark["y"])
        status = fit_points.get((x, y), {})
        if status.get("rgb_clipped"):
            color = "#9aa7b4"
        elif status.get("adopted"):
            color = "#7dffb0"
        elif status.get("adopted") is False:
            color = "#ff7b7b"
        else:
            color = "#f5e5e9"
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=color, width=2)
        draw.text((x + 7, y - 7), str(index), fill=color)
    if result["profile"]:
        draw.line([(p["x"], p["y"]) for p in result["profile"]], fill="#9be2d5", width=1)
    reading = result["reading"]
    if reading:
        x, y = reading["x"], reading["y"]
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline="#e6a66d", width=3)
        detail = f'Source ({x}, {y}) | radius {reading["r_px"]} px / {reading["r_mm"]:.2f} mm'
    else:
        detail = "No original image support for this ray"
    draw.text((14, height + 13), f'Source center ({cx}, {cy}) / ray {cfg["angle"]} deg', fill="#d9eaf3")
    draw.text((14, height + 35), detail, fill="#efc29f")
    return png(output)


def package(card, original, image, result):
    memory = BytesIO()
    with ZipFile(memory, "w", ZIP_DEFLATED) as stream:
        stream.writestr("ripple.png", original)
        stream.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"]},
                                                 ensure_ascii=False, indent=2))
        stream.writestr("ripple-profile.csv", trace_table(result))
        stream.writestr("ripple-proof.png", proof(image, card, result))
    return memory.getvalue()
