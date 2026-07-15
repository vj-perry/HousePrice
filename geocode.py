"""Postcode geocoding via postcodes.io (free, no API key).

Full-address (house-level) geocoding for the UK needs a licensed dataset or
a heavyweight geocoder; postcode centroids are accurate to a few doors and
are what free services provide. The frontend spreads properties that share
a postcode so their markers don't stack.
"""
from __future__ import annotations

import requests

POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"
BULK_CHUNK = 100
REQUEST_TIMEOUT = 30


class GeocodeError(Exception):
    pass


def geocode_postcodes(postcodes: list) -> dict:
    """Map each valid postcode to {'lat': .., 'lng': ..}. Unknown or
    invalid postcodes are simply absent from the result."""
    seen = []
    for pc in postcodes:
        if isinstance(pc, str):
            pc = " ".join(pc.split()).upper()
            if pc and pc not in seen:
                seen.append(pc)

    coords = {}
    for i in range(0, len(seen), BULK_CHUNK):
        chunk = seen[i:i + BULK_CHUNK]
        try:
            resp = requests.post(
                POSTCODES_IO_URL,
                json={"postcodes": chunk},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise GeocodeError(f"Could not reach the geocoding service: {exc}") from exc
        except ValueError as exc:
            raise GeocodeError("Geocoding service returned an unreadable response") from exc

        for item in payload.get("result") or []:
            result = item.get("result")
            if result and result.get("latitude") is not None:
                coords[item["query"].upper()] = {
                    "lat": result["latitude"],
                    "lng": result["longitude"],
                }
    return coords
