"""Client for HM Land Registry's Price Paid Data linked-data SPARQL endpoint.

Docs: https://landregistry.data.gov.uk/app/doc/ppd/
Query console (useful for double-checking query shape by hand):
https://landregistry.data.gov.uk/qonsole
"""
from __future__ import annotations

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
_FULL_PC_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)
_OUTCODE_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b", re.IGNORECASE)

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


def parse_query(q: str):
    """Split a free-text search like 'Downing Street SW1A' or 'SW1A 2AA'
    into (postcode, street). The postcode may appear anywhere in the text;
    whatever remains is treated as the street name."""
    q = " ".join(q.split())
    if not q:
        raise LandRegistryError("Enter a search")

    match = _FULL_PC_IN_TEXT.search(q)
    if match:
        postcode = f"{match.group(1).upper()} {match.group(2).upper()}"
    else:
        match = _OUTCODE_IN_TEXT.search(q)
        if not match:
            raise LandRegistryError(
                "Include a postcode in your search — full like 'SW1A 2AA' "
                "or partial like 'SW1A'"
            )
        postcode = match.group(1).upper()

    street = (q[:match.start()] + " " + q[match.end():]).strip(" ,")
    street = " ".join(street.split())

    # A leading house number ("10 Downing Street") is a property filter,
    # not part of the street name.
    paon = None
    number_match = re.match(r"^(\d+[A-Z]?)\s+(.+)$", street, re.IGNORECASE)
    if number_match:
        paon = number_match.group(1)
        street = number_match.group(2)

    return postcode, (street or None), paon


def search_sales(postcode: str, street: str | None = None, paon: str | None = None) -> list:
    """All recorded sales for a postcode (full or district), optionally
    narrowed by street name and house number. Returns the full recorded
    history — the Price Paid dataset starts in January 1995 — up to the
    latest published data.
    """
    postcode = postcode.strip().upper()

    if POSTCODE_RE.match(postcode):
        postcode_filter = f'FILTER(?postcode = "{_escape_literal(postcode)}")'
    elif OUTCODE_RE.match(postcode):
        postcode_filter = (
            f'FILTER(STRSTARTS(STR(?postcode), "{_escape_literal(postcode)} "))'
        )
    else:
        raise LandRegistryError(
            f"'{postcode}' does not look like a UK postcode (e.g. 'SW1A 1AA') "
            "or district (e.g. 'SW1A')"
        )

    street_filter = ""
    if street:
        needle = _escape_literal(street.strip())
        street_filter = f'FILTER(CONTAINS(LCASE(STR(?street)), LCASE("{needle}")))'

    query = f"""
    {PREFIXES}
    SELECT {_SELECT_FIELDS}
    WHERE {{
      ?transx lrppi:propertyAddress ?addr ;
              lrppi:pricePaid ?amount ;
              lrppi:transactionDate ?date .
      ?addr lrcommon:postcode ?postcode .
      {_OPTIONAL_FIELDS}
      {postcode_filter}
      {street_filter}
    }}
    ORDER BY ?date
    LIMIT {MAX_RESULTS}
    """

    rows = [_row_from_binding(b) for b in _run_query(query)]

    if paon:
        needle = paon.strip().lower()
        rows = [r for r in rows if r["paon"] and r["paon"].lower() == needle]

    return rows
