"""Room counts from the EPC (Energy Performance Certificate) open register.

Bedroom counts are not published in any open dataset. The closest openly
available figure is the EPC register's *habitable rooms* count (bedrooms +
living/dining rooms, excluding kitchens/bathrooms). The register's API is
free but requires registration: https://epc.opendatacommunities.org/

Set the EPC_AUTH environment variable to "your-email:your-api-key" to
enable the lookup; without it the app simply leaves the column blank.
"""
from __future__ import annotations

import base64
import os
import re

import requests

EPC_URL = "https://epc.opendatacommunities.org/api/v1/domestic/search"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 200


class EpcError(Exception):
    pass


_postcode_rows_cache = {}


def configured() -> bool:
    return bool(os.environ.get("EPC_AUTH"))


def _auth_header():
    token = base64.b64encode(os.environ["EPC_AUTH"].encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {token}"}


def _rows_for_postcode(postcode: str) -> list:
    if postcode in _postcode_rows_cache:
        return _postcode_rows_cache[postcode]
    try:
        resp = requests.get(
            EPC_URL,
            params={"postcode": postcode, "size": PAGE_SIZE},
            headers=_auth_header(),
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 401:
            raise EpcError("The EPC API rejected the EPC_AUTH credentials")
        resp.raise_for_status()
        rows = (resp.json() or {}).get("rows", []) if resp.text.strip() else []
    except requests.RequestException as exc:
        raise EpcError(f"Could not reach the EPC register: {exc}") from exc
    except ValueError as exc:
        raise EpcError("EPC register returned an unreadable response") from exc
    _postcode_rows_cache[postcode] = rows
    return rows


def rooms_for_properties(properties: list) -> dict:
    """Map property id -> habitable-room count (int) from the most recent
    EPC whose address matches the property's PAON (and SAON if present).
    Properties without a confident match are absent from the result."""
    if not configured():
        return {}

    by_postcode = {}
    for p in properties:
        pc = " ".join((p.get("postcode") or "").split()).upper()
        if pc:
            by_postcode.setdefault(pc, []).append(p)

    rooms = {}
    for pc, plist in by_postcode.items():
        rows = _rows_for_postcode(pc)
        if not rows:
            continue
        for p in plist:
            paon = (p.get("paon") or "").strip().lower()
            saon = (p.get("saon") or "").strip().lower()
            if not paon:
                continue
            best = None
            for row in rows:
                addr = " ".join(
                    str(row.get(k) or "") for k in ("address1", "address2", "address3")
                ).lower()
                if not re.search(rf"(?<![\w]){re.escape(paon)}(?![\w])", addr):
                    continue
                if saon and saon not in addr:
                    continue
                count = row.get("number-habitable-rooms")
                lodged = str(row.get("lodgement-date") or "")
                if count and (best is None or lodged > best[0]):
                    best = (lodged, count)
            if best:
                try:
                    rooms[p["id"]] = int(float(best[1]))
                except (TypeError, ValueError):
                    pass
    return rooms
