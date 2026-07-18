# UK House Price Explorer

A small Flask app that plots sold-price history from HM Land Registry's
[Price Paid Data](https://landregistry.data.gov.uk/app/doc/ppd/), with date of
sale on the x-axis and price on the y-axis.

One free-text search box that accepts any mix of postcode (full `SW1A 2AA`
or district `SW1A`), street name, and house number — e.g. `10 Downing
Street SW1A 2AA`, or just a street name on its own (street-only searches
match the exact full street name; adding a postcode allows partial names).
Results cover 2008 (when EPCs began, so every row can carry rooms,
floor-area, and energy-band data) up to the latest published data —
override with LAND_REGISTRY_FROM=YYYY-MM-DD to reach back to the
dataset's 1995 start.

- Scatter chart with a distinct marker shape and colour per property type,
  and the house number labelled beside each point (up to 250 visible points).
- Zoomable chart, like the map: scroll to zoom around the cursor, drag to
  pan, double-click or the reset button to fit; +/- buttons top-right.
- Clickable legend: toggle property types on/off; the chart, table, and map
  all filter together.
- Linked table below the chart — hovering a point highlights its row and
  every other recorded sale of the same property (chart and table).
- Sales above 5x the median price are excluded from the chart (they would
  squash the y-axis) and greyed out in the table.
- Toggleable map (Leaflet, vendored locally; OpenStreetMap tiles) plotting
  each property. Three precision tiers, best available per property:
  (1) rooftop-exact via the property's UPRN from its EPC joined against a
  local OS Open UPRN database — build it once with
  `python3 build_uprn_db.py` (~700MB download, ~2GB SQLite, free OGL data);
  (2) OSM Nominatim house-level lookup for searches with <= 25 unique
  properties; (3) postcodes.io postcode centroids. The note under the map
  states the precision mix.
- 12-month rolling median trend line on the chart (toggleable from the
  legend; shown when there's at least two years of history).
- Optional EPC-powered extras (register free at
  https://get-energy-performance-data.communities.gov.uk/ and set
  EPC_AUTH to the bearer token from your My Account page before starting
  the app; a legacy "email:token" value also works):
  a Rooms column (habitable rooms — no open dataset publishes bedroom
  counts), a £/m² column (price ÷ EPC internal floor area), an EPC energy
  band column, £/m² in the tooltip, a Price / £-per-m² chart mode toggle,
  and UPRNs for exact map positions.

Data is fetched live from Land Registry's public SPARQL endpoint — nothing is
downloaded or stored locally.

## Running it

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Then open http://127.0.0.1:5000.

## How it works

- `land_registry.py` builds SPARQL queries against
  `https://landregistry.data.gov.uk/landregistry/query` and parses the
  SPARQL-JSON results into plain rows (`date`, `price`, `address`,
  `property_type`, ...).
- `app.py` exposes `/api/sales?q=…` (free-text search; `land_registry.py`
  parses out postcode/street/house number), `POST /api/geocode`
  (Nominatim house-level + postcodes.io fallback, see `geocode.py`), and
  `POST /api/epc` (EPC habitable rooms + floor area, see `epc.py`).
- The frontend (`templates/index.html`, `static/js/app.js`) is plain
  HTML/CSS/JS — a hand-rolled SVG scatter chart with per-type marker shapes,
  hover tooltips, a crosshair, a legend, and a chart-linked data table, no
  charting library dependency.

If the SPARQL endpoint URL ever changes, override it without touching code:

```bash
export LAND_REGISTRY_SPARQL_ENDPOINT="https://landregistry.data.gov.uk/landregistry/query"
```

## Known limitation

This was built and validated (SPARQL query shape, error handling, the whole
request/response path) inside a sandboxed session whose network egress policy
blocks `landregistry.data.gov.uk`, so the actual live query could not be
executed end-to-end from here — only exercised down to the point where the
HTTP request leaves the process. The query follows Land Registry's documented
`lrppi`/`lrcommon` vocabulary, but please double check the first real search
once you run this somewhere with normal internet access. If the endpoint
returns a 404 or an unexpected shape, the most likely fix is adjusting
`SPARQL_ENDPOINT` in `land_registry.py` (or the env var above) — the query
console at https://landregistry.data.gov.uk/qonsole is useful for confirming
the exact query shape by hand.
