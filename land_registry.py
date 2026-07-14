"""Client for HM Land Registry's Price Paid Data linked-data SPARQL endpoint.

Docs: https://landregistry.data.gov.uk/app/doc/ppd/
Query console (useful for double-checking query shape by hand):
https://landregistry.data.gov.uk/qonsole
"""
import os
import re

import requests

SPARQL_ENDPOINT = os.environ.get(
    "LAND_REGISTRY_SPARQL_ENDPOINT",
    "https://landregistry.data.gov.uk/landregistry/query",
)

PREFIXES = """
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
OUTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_RESULTS = 3000
REQUEST_TIMEOUT = 30


class LandRegistryError(Exception):
    """Raised for anything that goes wrong talking to the Land Registry API."""


def _escape_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_query(query: str) -> list:
    try:
        resp = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query, "output": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise LandRegistryError(f"Could not reach the Land Registry API: {exc}") from exc
    except ValueError as exc:
        raise LandRegistryError(f"Land Registry API returned an unreadable response: {exc}") from exc

    try:
        return data["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise LandRegistryError("Land Registry API response was missing expected fields") from exc


def _value(binding: dict, key: str):
    cell = binding.get(key)
    return cell.get("value") if cell else None


def _property_type_label(uri: str | None) -> str | None:
    if not uri:
        return None
    slug = uri.rstrip("/").rsplit("/", 1)[-1]
    return {
        "detached": "Detached",
        "semi-detached": "Semi-detached",
        "terraced": "Terraced",
        "flat-maisonette": "Flat/Maisonette",
        "other": "Other",
    }.get(slug, slug.replace("-", " ").title())


def _row_from_binding(binding: dict) -> dict:
    amount = _value(binding, "amount")
    tx_date = _value(binding, "date")
    address_parts = [
        _value(binding, key) for key in ("saon", "paon", "street", "town", "county")
    ]
    address = ", ".join(part for part in address_parts if part)
    return {
        "date": (tx_date or "")[:10],
        "price": float(amount) if amount is not None else None,
        "address": address,
        "paon": _value(binding, "paon"),
        "saon": _value(binding, "saon"),
        "street": _value(binding, "street"),
        "town": _value(binding, "town"),
        "postcode": _value(binding, "postcode"),
        "property_type": _property_type_label(_value(binding, "propertyType")),
    }


_SELECT_FIELDS = """
    ?paon ?saon ?street ?town ?county ?postcode ?amount ?date ?propertyType
"""

_OPTIONAL_FIELDS = """
      OPTIONAL { ?addr lrcommon:paon ?paon }
      OPTIONAL { ?addr lrcommon:saon ?saon }
      OPTIONAL { ?addr lrcommon:street ?street }
      OPTIONAL { ?addr lrcommon:town ?town }
      OPTIONAL { ?addr lrcommon:county ?county }
      OPTIONAL { ?transx lrppi:propertyType ?propertyType }
"""


def search_property_sales(postcode: str, house: str | None = None) -> list:
    """All recorded sales for a postcode, optionally narrowed to one house/flat."""
    postcode = postcode.strip().upper()
    if not POSTCODE_RE.match(postcode):
        raise LandRegistryError(f"'{postcode}' does not look like a valid UK postcode")

    query = f"""
    {PREFIXES}
    SELECT {_SELECT_FIELDS}
    WHERE {{
      ?transx lrppi:propertyAddress ?addr ;
              lrppi:pricePaid ?amount ;
              lrppi:transactionDate ?date .
      ?addr lrcommon:postcode ?postcode .
      FILTER(?postcode = "{_escape_literal(postcode)}")
      {_OPTIONAL_FIELDS}
    }}
    ORDER BY ?date
    LIMIT {MAX_RESULTS}
    """

    rows = [_row_from_binding(b) for b in _run_query(query)]

    if house:
        needle = house.strip().lower()
        rows = [r for r in rows if r["paon"] and needle in r["paon"].lower()]

    return rows


def search_area_sales(
    area: str | None = None,
    town: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list:
    """Sales across a postcode area/district (e.g. 'SW1A') or a town, over time."""
    if not area and not town:
        raise LandRegistryError("Provide either a postcode area or a town")

    filters = []

    if area:
        area = area.strip().upper()
        if not OUTCODE_RE.match(area):
            raise LandRegistryError(
                f"'{area}' does not look like a valid UK postcode area/district (e.g. 'SW1A')"
            )
        filters.append(f'FILTER(STRSTARTS(STR(?postcode), "{_escape_literal(area)}"))')

    if town:
        filters.append(f'FILTER(LCASE(STR(?town)) = LCASE("{_escape_literal(town.strip())}"))')

    for label, value in (("date_from", date_from), ("date_to", date_to)):
        if value and not DATE_RE.match(value):
            raise LandRegistryError(f"{label} must be in YYYY-MM-DD format")

    if date_from:
        filters.append(f'FILTER(?date >= "{date_from}"^^xsd:date)')
    if date_to:
        filters.append(f'FILTER(?date <= "{date_to}"^^xsd:date)')

    query = f"""
    {PREFIXES}
    SELECT {_SELECT_FIELDS}
    WHERE {{
      ?transx lrppi:propertyAddress ?addr ;
              lrppi:pricePaid ?amount ;
              lrppi:transactionDate ?date .
      ?addr lrcommon:postcode ?postcode .
      {_OPTIONAL_FIELDS}
      {' '.join(filters)}
    }}
    ORDER BY ?date
    LIMIT {MAX_RESULTS}
    """

    return [_row_from_binding(b) for b in _run_query(query)]
