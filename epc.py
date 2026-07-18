"""Room counts and floor areas from the EPC open-data register.

Bedroom counts are not published in any open dataset. The closest openly
available figures are the EPC register's *habitable rooms* count and
*total floor area*.

The register moved in May 2026: epc.opendatacommunities.org was retired
and replaced by https://get-energy-performance-data.communities.gov.uk.
The new API is quite different from the old one:

- host:    https://api.get-energy-performance-data.communities.gov.uk
           (the PUBLISHED_DWH_API_URL of the epb-data-frontend service)
- auth:    "Authorization: Bearer <token>" — the token shown on your
           My Account page on the data service
- search:  GET /api/domestic/search?postcode=... returns light metadata
           (certificate number + address) per certificate
- detail:  GET /api/certificate?certificate_number=... returns the full
           certificate, which carries floor area / habitable rooms

Set EPC_AUTH to your bearer token (a legacy "email:token" value also
works — the part after the colon is used). EPC_API_URL overrides the
API host if it ever moves again.
"""
from __future__ import annotations

import os
import re

import requests

API_BASE = (os.environ.get("EPC_API_URL") or
            "https://api.get-energy-performance-data.communities.gov.uk").rstrip("/")
SEARCH_URL = f"{API_BASE}/api/domestic/search"
CERT_URL = f"{API_BASE}/api/certificate"
REQUEST_TIMEOUT = 30
# Full-certificate fetches are one request each; cap them so a big search
# can't fire hundreds of API calls.
MAX_CERT_FETCHES = 30


class EpcError(Exception):
    pass


_postcode_rows_cache = {}
_cert_cache = {}

BAD_CREDENTIALS_HINT = (
    "The EPC API rejected the token. epc_auth.txt should contain the bearer "
    "token shown on your My Account page at "
    "get-energy-performance-data.communities.gov.uk (the part after the colon "
    "is used if the file still has the old email:key format)."
)


def configured() -> bool:
    return bool(os.environ.get("EPC_AUTH"))


def _token() -> str:
    raw = (os.environ.get("EPC_AUTH") or "").strip()
    if ":" in raw:
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        raise EpcError("EPC_AUTH is empty — put your bearer token in epc_auth.txt")
    return raw


def _get(url, params):
    """One authenticated GET. Returns parsed JSON, or None for a 404
    (which the API uses for 'no results')."""
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {_token()}",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EpcError(f"Could not reach the EPC register ({url}): {exc}") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code in (401, 403):
        raise EpcError(BAD_CREDENTIALS_HINT + f" (HTTP {resp.status_code})")
    if resp.status_code >= 400:
        snippet = " ".join((resp.text or "")[:200].split())
        raise EpcError(f"EPC register returned HTTP {resp.status_code}: {snippet}")

    body = (resp.text or "").strip()
    if not body:
        return None
    if body[0] == "<":
        raise EpcError(
            f"{url} returned a web page instead of JSON — if the API has moved, "
            "set EPC_API_URL to the new API host"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise EpcError("EPC register returned an unreadable (non-JSON) response") from exc


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _find_value(obj, targets):
    """Breadth-first search of nested dicts/lists for the first key whose
    normalised form is in `targets`. Tolerates camelCase, snake_case, and
    extra nesting. Breadth-first matters: certificates carry per-storey
    total_floor_area entries nested deeper than the whole-property figure,
    and the shallowest occurrence is the one we want."""
    queue = [(obj, 0)]
    index = 0
    while index < len(queue):
        current, depth = queue[index]
        index += 1
        if depth > 6:
            continue
        if isinstance(current, dict):
            for key, value in current.items():
                if _norm_key(key) in targets and value not in (None, ""):
                    return value
            for value in current.values():
                queue.append((value, depth + 1))
        elif isinstance(current, list):
            for item in current:
                queue.append((item, depth + 1))
    return None


def _extract_list(payload):
    """The search response wraps its certificate list somewhere ('data',
    'certificates', 'rows', ...) — find the first list of dicts."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            rows = _extract_list(value)
            if rows:
                return rows
    return []


_page_param = [None]  # which page-size parameter the API accepts, once learned


def _rows_for_postcode(postcode: str) -> list:
    if postcode in _postcode_rows_cache:
        return _postcode_rows_cache[postcode]

    # Ask for the maximum page in one go — the docs name the parameter
    # inconsistently ("page_size" in examples, "page" in the table), so
    # learn which one the API accepts; fall back to the default page size
    # rather than failing if both are rejected.
    payload = None
    if _page_param[0] is not None:
        candidates = [_page_param[0], None]
    else:
        candidates = ["page_size", "page", None]
    for param in candidates:
        params = {"postcode": postcode}
        if param:
            params[param] = 5000
        try:
            payload = _get(SEARCH_URL, params)
            _page_param[0] = param
            break
        except EpcError as exc:
            if "HTTP 400" in str(exc):
                continue
            raise

    rows = _extract_list(payload)
    _postcode_rows_cache[postcode] = rows
    return rows


_ADDR_KEYS = {"addressline1", "addressline2", "addressline3", "addressline4",
              "address1", "address2", "address3", "address"}
_RATING_KEYS = {"currentenergyefficiencyband", "currentenergyrating", "energyrating",
                "currentenergyefficiencyrating"}
_CERT_NO_KEYS = {"certificatenumber", "rrn", "lmkkey"}
_DATE_KEYS = {"registrationdate", "lodgementdate"}
_ROOMS_KEYS = {"habitableroomcount", "numberhabitablerooms", "habitablerooms",
               "numberofhabitablerooms"}
_AREA_KEYS = {"totalfloorarea", "floorarea"}


def _address_of(row: dict) -> str:
    parts = []
    for key, value in row.items():
        if _norm_key(key) in _ADDR_KEYS and value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _cert_details(cert_number):
    """Fetch one certificate and pull out rooms + floor area, wherever
    the schema put them."""
    if cert_number in _cert_cache:
        return _cert_cache[cert_number]
    payload = _get(CERT_URL, {"certificate_number": cert_number})
    entry = {"rooms": None, "floor_area": None}
    if payload is not None:
        rooms = _find_value(payload, _ROOMS_KEYS)
        area = _find_value(payload, _AREA_KEYS)
        try:
            if rooms is not None:
                entry["rooms"] = int(float(rooms))
        except (TypeError, ValueError):
            pass
        try:
            if area is not None and float(area) > 0:
                entry["floor_area"] = float(area)
        except (TypeError, ValueError):
            pass
    _cert_cache[cert_number] = entry
    return entry


def epc_for_properties(properties: list) -> dict:
    """Map property id -> {'rooms': int|None, 'floor_area': float|None}
    from the most recent EPC whose address matches the property's PAON
    (and SAON if present). Properties without a confident match are
    absent from the result."""
    if not configured():
        return {}

    by_postcode = {}
    for p in properties:
        pc = " ".join((p.get("postcode") or "").split()).upper()
        if pc:
            by_postcode.setdefault(pc, []).append(p)

    results = {}
    fetches = 0
    for pc, plist in by_postcode.items():
        rows = _rows_for_postcode(pc)
        if not rows:
            continue
        for p in plist:
            paon = (p.get("paon") or "").strip().lower()
            saon = (p.get("saon") or "").strip().lower()
            street = (p.get("street") or "").strip().lower()
            if not paon:
                continue
            best = None
            for row in rows:
                addr = _address_of(row)
                if not re.search(rf"(?<![\w]){re.escape(paon)}(?![\w])", addr):
                    continue
                if saon and saon not in addr:
                    continue
                # A postcode can span two streets; when we know the street,
                # require it so "20 X Road" never matches "20 Y Road".
                if street and street not in addr.replace(",", ""):
                    continue
                cert_no = _find_value(row, _CERT_NO_KEYS)
                if not cert_no:
                    continue
                reg_date = str(_find_value(row, _DATE_KEYS) or "")
                uprn = _find_value(row, {"uprn"})
                rating = _find_value(row, _RATING_KEYS)
                if best is None or reg_date > best[0]:
                    best = (reg_date, cert_no, str(uprn) if uprn else None,
                            str(rating).strip().upper() if rating else None)
            if not best:
                continue
            if fetches >= MAX_CERT_FETCHES:
                continue
            fetches += 1
            entry = dict(_cert_details(best[1]))
            entry["uprn"] = best[2]
            entry["rating"] = best[3]
            if any(entry.get(k) is not None for k in ("rooms", "floor_area", "uprn", "rating")):
                results[p["id"]] = entry
    return results
