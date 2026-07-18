"""Geocoding for property locations.

Two tiers:

1. House-level via OpenStreetMap's Nominatim (free, no key). Its usage
   policy caps us at ~1 request/second, so house-level lookup only runs
   when a search has a modest number of unique properties; coverage also
   varies — not every UK address has a mapped house number in OSM.
2. Postcode centroids via postcodes.io (free, no key, bulk) — accurate to
   a few doors — as the fallback for everything else.

Results are cached in memory for the life of the server process.
"""
from __future__ import annotations

import threading
import time

import requests

import uprn_db

POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "HousePriceExplorer/1.0 (personal local app)"
BULK_CHUNK = 100
REQUEST_TIMEOUT = 30
# Nominatim allows ~1 req/s; past this many unique properties we skip
# house-level lookup entirely rather than make the user wait.
HOUSE_LEVEL_LIMIT = 25
NOMINATIM_MIN_INTERVAL = 1.1  # seconds


class GeocodeError(Exception):
    pass


_postcode_cache = {}
_address_cache = {}
_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]


def geocode_postcodes(postcodes: list) -> dict:
    """Map each valid postcode to {'lat': .., 'lng': ..}. Unknown or
    invalid postcodes are simply absent from the result."""
    seen = []
    for pc in postcodes:
        if isinstance(pc, str):
            pc = " ".join(pc.split()).upper()
            if pc and pc not in seen:
                seen.append(pc)

    missing = [pc for pc in seen if pc not in _postcode_cache]
    for i in range(0, len(missing), BULK_CHUNK):
        chunk = missing[i:i + BULK_CHUNK]
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
                _postcode_cache[item["query"].upper()] = {
                    "lat": result["latitude"],
                    "lng": result["longitude"],
                }
            else:
                _postcode_cache[item["query"].upper()] = None

    return {pc: _postcode_cache[pc] for pc in seen if _postcode_cache.get(pc)}


def _nominatim_lookup(paon, street, town, postcode):
    """One structured Nominatim query, throttled to the usage policy."""
    with _nominatim_lock:
        wait = _nominatim_last[0] + NOMINATIM_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _nominatim_last[0] = time.monotonic()

    params = {
        "street": f"{paon} {street}".strip(),
        "postalcode": postcode or "",
        "country": "United Kingdom",
        "format": "jsonv2",
        "limit": 1,
    }
    if town:
        params["city"] = town
    resp = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json()
    if results:
        return {
            "lat": float(results[0]["lat"]),
            "lng": float(results[0]["lon"]),
            "precision": "address",
        }
    return None


def geocode_properties(properties: list) -> dict:
    """Map property id -> {'lat', 'lng', 'precision'} where precision is
    'uprn' (rooftop-exact, OS Open UPRN), 'address' (house-level, OSM),
    or 'postcode' (centroid fallback)."""
    postcodes = [p.get("postcode") for p in properties if p.get("postcode")]
    pc_coords = geocode_postcodes(postcodes)

    # Tier 1: exact positions from the local OS Open UPRN database for
    # properties whose EPC gave us a UPRN.
    uprn_coords = uprn_db.lookup([p.get("uprn") for p in properties if p.get("uprn")])

    house_level = len(properties) <= HOUSE_LEVEL_LIMIT
    results = {}

    for p in properties:
        pid = p.get("id")
        if pid is None:
            continue

        uprn = str(p.get("uprn") or "").strip()
        if uprn and uprn in uprn_coords:
            results[pid] = {
                "lat": uprn_coords[uprn]["lat"],
                "lng": uprn_coords[uprn]["lng"],
                "precision": "uprn",
            }
            continue
        paon = (p.get("paon") or "").strip()
        street = (p.get("street") or "").strip()
        postcode = " ".join((p.get("postcode") or "").split()).upper()
        cache_key = "|".join([paon.lower(), street.lower(), postcode])

        coord = _address_cache.get(cache_key)
        if coord is None and cache_key not in _address_cache:
            if house_level and paon and street:
                try:
                    coord = _nominatim_lookup(paon, street, (p.get("town") or "").strip(), postcode)
                except (requests.RequestException, ValueError, KeyError):
                    # Nominatim being down or odd shouldn't kill the map —
                    # everything falls back to postcode centroids.
                    house_level = False
                    coord = None
            _address_cache[cache_key] = coord

        if not coord:
            centroid = pc_coords.get(postcode)
            if centroid:
                coord = {"lat": centroid["lat"], "lng": centroid["lng"], "precision": "postcode"}

        if coord:
            results[pid] = coord

    return results
