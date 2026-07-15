import os

from flask import Flask, jsonify, render_template, request

import epc
from geocode import GeocodeError, geocode_properties
from land_registry import LandRegistryError, parse_query, search_sales

app = Flask(__name__)

MAX_GEOCODE_PROPERTIES = 500


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/sales")
def sales():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q (search text) is required"}), 400
    try:
        postcode, street, paon = parse_query(q)
        results = search_sales(postcode, street, paon)
    except LandRegistryError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({
        "sales": results,
        "postcode": postcode,
        "street": street,
        "paon": paon,
    })


def _property_list(body):
    properties = (body or {}).get("properties")
    if not isinstance(properties, list) or not properties:
        return None
    return properties[:MAX_GEOCODE_PROPERTIES]


@app.post("/api/geocode")
def geocode():
    properties = _property_list(request.get_json(silent=True))
    if properties is None:
        return jsonify({"error": "properties (non-empty list) is required"}), 400
    try:
        coords = geocode_properties(properties)
    except GeocodeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"coords": coords})


@app.post("/api/epc")
def epc_lookup():
    if not epc.configured():
        return jsonify({"configured": False, "properties": {}})
    properties = _property_list(request.get_json(silent=True))
    if properties is None:
        return jsonify({"error": "properties (non-empty list) is required"}), 400
    try:
        result = epc.epc_for_properties(properties)
    except epc.EpcError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"configured": True, "properties": result})


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "5000")))
