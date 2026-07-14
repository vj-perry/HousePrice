from flask import Flask, jsonify, render_template, request

from land_registry import LandRegistryError, search_area_sales, search_property_sales

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/property-sales")
def property_sales():
    postcode = request.args.get("postcode", "").strip()
    house = request.args.get("house", "").strip()
    if not postcode:
        return jsonify({"error": "postcode is required"}), 400
    try:
        sales = search_property_sales(postcode, house or None)
    except LandRegistryError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"sales": sales})


@app.get("/api/area-sales")
def area_sales():
    area = request.args.get("area", "").strip()
    town = request.args.get("town", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    if not area and not town:
        return jsonify({"error": "either area (postcode district) or town is required"}), 400
    try:
        sales = search_area_sales(
            area=area or None,
            town=town or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
    except LandRegistryError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"sales": sales})


if __name__ == "__main__":
    app.run(debug=True)
