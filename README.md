# UK House Price Explorer

A small Flask app that plots sold-price history from HM Land Registry's
[Price Paid Data](https://landregistry.data.gov.uk/app/doc/ppd/), with date of
sale on the x-axis and price on the y-axis.

Two search modes:

- **One property** — enter a postcode (optionally narrowed by house number/name)
  to see every recorded sale at that address.
- **Area trend** — enter a postcode area/district (e.g. `SW1A`) or a town, with
  an optional date range, to see a scatter of all sales in that area, coloured
  by property type.

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
- `app.py` exposes two JSON endpoints, `/api/property-sales` and
  `/api/area-sales`, that the frontend calls.
- The frontend (`templates/index.html`, `static/js/app.js`) is plain
  HTML/CSS/JS — a hand-rolled SVG chart with hover tooltips, a crosshair, a
  legend, and a toggleable data table, no charting library dependency.

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
