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


def train_table(result):
    train = result["train"]
    target = StringIO()
    writer = csv.writer(target)
    writer.writerow(("kind", "peak", "r_px", "r_mm", "x_px", "y_px", "red", "green", "blue", "luma",
                     "gap_from_px", "gap_px", "gap_mm", "deviation_px", "double", "note"))
    if not train["feasible"]:
        writer.writerow(("infeasible", "", "", "", "", "", "", "", "", "", "", "", "", "", "", train["reason"]))
        return target.getvalue().encode()
    for peak in train["peaks"]:
        gap = next((row for row in train["gaps"] if row["to_peak"] == peak["number"]), None)
        writer.writerow(("peak", peak["number"], peak["r_px"], f'{peak["r_mm"]:.4f}', peak["x"], peak["y"],
                         *peak["rgb"], f'{peak["brightness"]:.3f}',
                         gap["from_r_px"] if gap else "", gap["gap_px"] if gap else "",
                         f'{gap["gap_mm"]:.4f}' if gap else "", f'{gap["deviation_px"]:.4f}' if gap else "",
                         "yes" if gap and gap["double"] else "no", ""))
        if gap and gap.get("missing"):
            hole = gap["missing"]
            writer.writerow(("missing", "", hole["r_px"], f'{hole["r_mm"]:.4f}', hole["x"], hole["y"],
                             "", "", "", "", gap["from_r_px"], gap["gap_px"], f'{gap["gap_mm"]:.4f}',
                             f'{gap["deviation_px"]:.4f}', "yes", hole["note"]))
    writer.writerow(("spacing", "", "", f'{train["spacing_mm"]:.4f}', "", "", "", "", "", "",
                     "", "", "", f'{train["worst_deviation_px"]:.4f}', "", train["note"]))
    return target.getvalue().encode()


def _mark_train(draw, train):
    if not train["feasible"]:
        return
    for peak in train["peaks"]:
        x, y = peak["x"], peak["y"]
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline="#f2cf72", width=2)
        draw.text((x + 8, y - 7), str(peak["number"]), fill="#f7e6b4")
    for hole in train["missing"]:
        x, y = hole["x"], hole["y"]
        draw.line((x - 5, y - 5, x + 5, y + 5), fill="#f2a3a3", width=2)
        draw.line((x + 5, y - 5, x - 5, y + 5), fill="#f2a3a3", width=2)
        draw.text((x + 8, y + 4), f'missing {hole["r_px"]}px', fill="#f2a3a3")


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(430, width), height + 88), "#101e34")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    cx, cy = cfg["center_x"], cfg["center_y"]
    for radius in (cfg["inner"], cfg["outer"]):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#669aad", width=1)
    draw.line((cx - 5, cy, cx + 5, cy), fill="#b5ebcc", width=2)
    draw.line((cx, cy - 5, cx, cy + 5), fill="#b5ebcc", width=2)
    if result["profile"]:
        draw.line([(p["x"], p["y"]) for p in result["profile"]], fill="#9be2d5", width=1)
    reading = result["reading"]
    if reading:
        x, y = reading["x"], reading["y"]
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline="#e6a66d", width=3)
        detail = f'Source ({x}, {y}) | radius {reading["r_px"]} px / {reading["r_mm"]:.2f} mm'
    else:
        detail = "No original image support for this ray"
    _mark_train(draw, result["train"])
    draw.text((14, height + 13), f'Source center ({cx}, {cy}) / ray {cfg["angle"]} deg', fill="#d9eaf3")
    draw.text((14, height + 35), detail, fill="#efc29f")
    draw.text((14, height + 55), _train_caption(result["train"]), fill="#f2d79b")
    return png(output)


def _train_caption(train):
    if not train["feasible"]:
        return "Spacing check: " + train["reason"]
    text = (f'Spacing {train["spacing_mm"]:.3f} mm ({train["spacing_px"]:.2f} px) over '
            f'{train["peak_count"]} source peaks | worst dev {train["worst_deviation_px"]:.2f} px')
    if train["missing"]:
        text += " | one doubled gap, " + ", ".join(str(hole["r_px"]) for hole in train["missing"]) + " px left blank"
    return text


def package(card, original, image, result):
    memory = BytesIO()
    with ZipFile(memory, "w", ZIP_DEFLATED) as stream:
        stream.writestr("ripple.png", original)
        stream.writestr("reading.json", json.dumps(
            {"card": card, "reading": result["reading"], "train": result["train"]},
            ensure_ascii=False, indent=2))
        stream.writestr("ripple-profile.csv", trace_table(result))
        stream.writestr("ripple-train.csv", train_table(result))
        stream.writestr("ripple-proof.png", proof(image, card, result))
    return memory.getvalue()
