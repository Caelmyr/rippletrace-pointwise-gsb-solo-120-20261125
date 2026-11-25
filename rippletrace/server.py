"""Serve radial photo readings and the source preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, object_value

from . import exports, ripple, ringfit
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
        card = cards.read(key, request.args.get("revision"))
        image = ripple.pixels(cards.photo(key))
        return card, image, ripple.report(image, card["settings"])

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, image, result = measurement(key)
        marks = card.get("ring_marks", [])
        fit = card.get("ring_fit")
        ring_points = [
            ripple.point(image, mark["x"], mark["y"], card["settings"], marks, fit)
            for mark in marks
        ]
        ring = {"marks": marks, "fit": fit, "points": ring_points}
        return jsonify(revision=card["revision"], **result, ring=ring,
                       ring_marks=marks, ring_fit=fit)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        image = ripple.pixels(cards.photo(key))
        return jsonify(ripple.point(image, x, y, card["settings"],
                                   card.get("ring_marks"), card.get("ring_fit")))

    def json_body():
        value = request.get_json(silent=True)
        if value is None:
            return {}
        if isinstance(value, list):
            return {"ring_marks": value}
        return object_value(value, "请求内容")

    def fit_from_request(key, apply=False):
        body = json_body()
        revision = body.get("revision", request.args.get("revision"))
        card = cards.read(key, revision)
        image = ripple.pixels(cards.photo(key))
        raw_marks = body.get(
            "ring_marks",
            body.get("marked_points",
                     body.get("control_points",
                              body.get("bright_points",
                                       body.get("marks",
                                                body.get("points",
                                                         card.get("ring_marks", [])))))))
        config = card["settings"]
        fit = ringfit.suggest_ring_fit(
            image, raw_marks, config["inner"], config["outer"],
            current_center=(config["center_x"], config["center_y"]))
        if not apply:
            return fit, card, body

        if not fit.get("feasible"):
            raise Invalid(fit.get("message") or "没有满足全部约束的圆心")
        update_body = {
            "revision": card["revision"],
            "settings": {"center_x": fit["center_x"], "center_y": fit["center_y"]},
            "ring_marks": fit["points"],
            "ring_fit": fit,
        }
        updated = cards.update(key, update_body)
        return updated, card, body

    @api.post("/cards/<key>/ring-fit/suggest")
    @api.post("/cards/<key>/center-fit/suggest")
    @api.post("/cards/<key>/fit/suggest")
    def suggest_ring_fit(key):
        fit, _, _ = fit_from_request(key, apply=False)
        return jsonify(fit)

    @api.post("/cards/<key>/ring-fit/apply")
    @api.post("/cards/<key>/center-fit/apply")
    @api.post("/cards/<key>/fit/apply")
    def apply_ring_fit(key):
        updated, _, _ = fit_from_request(key, apply=True)
        return jsonify(updated)

    @api.post("/cards/<key>/ring-fit")
    @api.post("/cards/<key>/center-fit")
    @api.post("/cards/<key>/fit")
    def ring_fit(key):
        body = json_body()
        if body.get("apply") is True or request.args.get("apply") in {"1", "true", "yes"}:
            updated, _, _ = fit_from_request(key, apply=True)
            return jsonify(updated)
        fit, _, _ = fit_from_request(key, apply=False)
        return jsonify(fit)

    @api.route("/cards/<key>/ring-marks", methods=["GET", "POST", "PUT", "PATCH"])
    @api.route("/cards/<key>/ring-points", methods=["GET", "POST", "PUT", "PATCH"])
    @api.route("/cards/<key>/marked-points", methods=["GET", "POST", "PUT", "PATCH"])
    @api.route("/cards/<key>/control-points", methods=["GET", "POST", "PUT", "PATCH"])
    @api.route("/cards/<key>/points", methods=["GET", "POST", "PUT", "PATCH"])
    @api.route("/cards/<key>/marks", methods=["GET", "POST", "PUT", "PATCH"])
    def ring_marks(key):
        if request.method == "GET":
            card = cards.read(key, request.args.get("revision"))
            return jsonify(ring_marks=card.get("ring_marks", []),
                           ring_fit=card.get("ring_fit"), revision=card["revision"])
        body = json_body()
        if "ring_marks" not in body and "marks" not in body:
            body = {"revision": body.get("revision"), "ring_marks": body.get("points", [])}
        return jsonify(cards.update(key, body))

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
