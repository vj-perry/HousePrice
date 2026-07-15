from flask import Flask, jsonify, render_template, request

from geocode import GeocodeError, geocode_postcodes
from land_registry import LandRegistryError, parse_query, search_sales

app = Flask(__name__)

MAX_GEOCODE_POSTCODES = 500


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


@app.post("/api/geocode")
def geocode():
    body = request.get_json(silent=True) or {}
    postcodes = body.get("postcodes")
    if not isinstance(postcodes, list) or not postcodes:
        return jsonify({"error": "postcodes (non-empty list) is required"}), 400
    if len(postcodes) > MAX_GEOCODE_POSTCODES:
        postcodes = postcodes[:MAX_GEOCODE_POSTCODES]
    try:
        coords = geocode_postcodes(postcodes)
    except GeocodeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"coords": coords})


if __name__ == "__main__":
    app.run(debug=True)
