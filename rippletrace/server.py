"""Serve radial photo readings and the source preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, object_value

from . import exports, ripple
from .store import Cards


def download(data, mime, filename):
    return send_file(BytesIO(data), mimetype=mime, max_age=0, download_name=filename, as_attachment=True)


def create_app(directory=None):
    root = Path(directory or os.environ.get("RIPPLETRACE_DATA", ".rippletrace-data")).resolve()
    desk = preparation_app(root / "prepare")
    cards = Cards(root / "cards")
    api = Blueprint("rippletrace", __name__, url_prefix="/rippletrace")

    @desk.get("/")
    def home():
        return render_template("rippletrace.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", app="rippletrace")

    @api.get("/cards")
    def listing():
        return jsonify(cards=cards.list())

    @api.post("/cards")
    def create():
        request.max_content_length = 20 * 1024 * 1024
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise Invalid("请选择水纹原照")
        size, image = ripple.decode(upload.stream.read(ripple.MAX_IMAGE_BYTES + 1))
        return jsonify(cards.create(request.form.get("name", ""), Path(upload.filename).name[:140],
                                    size, image, ripple.defaults(size))), 201

    @api.post("/practice")
    def practice():
        return jsonify(cards.demo()), 201

    @api.route("/cards/<key>", methods=["GET", "PATCH"])
    def card(key):
        return jsonify(cards.update(key, object_value(request.get_json(silent=True), "水纹卡设置"))
                       if request.method == "PATCH" else cards.read(key))

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        body = request.get_json(silent=True) if request.method == "POST" else None
        revision = request.args.get("revision")
        if revision is None and isinstance(body, dict):
            revision = body.get("revision")
        card = cards.read(key, revision)
        image = ripple.pixels(cards.photo(key))
        angle_value = request.args.get("angle")
        if angle_value is None and isinstance(body, dict):
            angle_value = body.get("angle")
        angle = integer(angle_value, "方向角度", 0, 359) if angle_value is not None else None
        radius_value = None
        for name in ("r_px", "start_radius", "radius", "start_r", "anchor_radius",
                     "seed_radius", "seed", "start", "follow"):
            radius_value = request.args.get(name)
            if radius_value is not None:
                break
        if radius_value is None and isinstance(body, dict):
            radius_value = body.get("r_px", body.get("start_radius",
                                    body.get("radius", body.get("anchor_radius",
                                    body.get("seed_radius", body.get("seed"))))))
        if radius_value is not None:
            radius = integer(radius_value, "起步半径", card["settings"]["inner"],
                             card["settings"]["outer"])
        else:
            radius = None
        return card, image, ripple.report(image, card["settings"], angle, radius)

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    def trace_request(key):
        body = request.get_json(silent=True) if request.method == "POST" else {}
        body = body if isinstance(body, dict) else {}
        revision = request.args.get("revision", body.get("revision"))
        card = cards.read(key, revision)
        image = ripple.pixels(cards.photo(key))

        def value(*names):
            for name in names:
                if name in request.args:
                    return request.args.get(name)
                if name in body and body[name] is not None:
                    return body[name]
            return None

        radius_value = value("r_px", "start_radius", "start_radius_px", "radius",
                             "start_r", "anchor_radius", "seed_radius",
                             "seed", "start", "r")
        radius = (integer(radius_value, "起步半径", card["settings"]["inner"],
                          card["settings"]["outer"])
                  if radius_value is not None else None)
        angle_value = value("angle", "start_angle", "angle_start")
        angle = (integer(angle_value, "方向角度", 0, 359)
                 if angle_value is not None else card["settings"]["angle"])
        result = ripple.trace_ripple(image, card["settings"], radius, angle=angle)
        return jsonify(revision=card["revision"], **result)

    @api.route("/cards/<key>/trace", methods=["GET", "POST"])
    def trace_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/follow", methods=["GET", "POST"])
    def follow_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/suggest", methods=["GET", "POST"])
    def suggest_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/suggestion", methods=["GET", "POST"])
    def suggestion_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/track", methods=["GET", "POST"])
    def track_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/ripple-trace", methods=["GET", "POST"])
    def ripple_trace_card(key):
        return trace_request(key)

    @api.route("/cards/<key>/follow-ripple", methods=["GET", "POST"])
    def follow_ripple_card(key):
        return trace_request(key)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        return jsonify(ripple.point(ripple.pixels(cards.photo(key)), x, y, card["settings"]))

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "ripple-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    def proof(key):
        card, image, result = measurement(key)
        return download(exports.proof(image, card, result), "image/png", "ripple-proof.png")

    @api.get("/cards/<key>/export/observation.zip")
    def bundle(key):
        card, image, result = measurement(key)
        package = exports.package(card, cards.photo(key).read_bytes(), image, result)
        return download(package, "application/zip", f"rippletrace-r{card['revision']}.zip")

    @api.post("/cards/<key>/prepare")
    def prepare(key):
        card = cards.read(key, request.args.get("revision"))
        image = ripple.pixels(cards.photo(key)).astype("float32") / 255
        services = desk.extensions
        asset = services["assets"].put(image, card["photo_name"])
        project = services["store"].create(f'{card["name"]} · 原片准备')
        services["frames"].add(project["id"], project["revision"], [asset["id"]])
        return jsonify(url=url_for("index", project=project["id"])), 201

    desk.register_blueprint(api)
    return desk
