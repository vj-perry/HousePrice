from flask import Flask, jsonify, render_template, request

from land_registry import LandRegistryError, search_sales

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/sales")
def sales():
    postcode = request.args.get("postcode", "").strip()
    street = request.args.get("street", "").strip()
    if not postcode:
        return jsonify({"error": "postcode is required"}), 400
    try:
        results = search_sales(postcode, street or None)
    except LandRegistryError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"sales": results})


if __name__ == "__main__":
    app.run(debug=True)
