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


def _credentials():
    raw = os.environ["EPC_AUTH"]
    if ":" not in raw:
        raise EpcError(
            "EPC_AUTH/epc_auth.txt must be 'your-email:your-api-key' — no colon found"
        )
    email, key = raw.split(":", 1)
    return email.strip(), key.strip()


BAD_CREDENTIALS_HINT = (
    "Check that the email before the colon in epc_auth.txt is exactly the "
    "address you registered with at epc.opendatacommunities.org, and that the "
    "key matches the one shown on your account page."
)


def _rows_for_postcode(postcode: str) -> list:
    if postcode in _postcode_rows_cache:
        return _postcode_rows_cache[postcode]
    try:
        resp = requests.get(
            EPC_URL,
            params={"postcode": postcode, "size": PAGE_SIZE},
            headers={"Accept": "application/json"},
            auth=_credentials(),
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            raise EpcError(
                f"The EPC API rejected the credentials (HTTP {resp.status_code}). "
                + BAD_CREDENTIALS_HINT
            )
        if resp.status_code >= 400:
            snippet = " ".join((resp.text or "")[:200].split())
            raise EpcError(f"EPC register returned HTTP {resp.status_code}: {snippet}")
        body = (resp.text or "").strip()
        if not body:
            rows = []
        elif body[0] in "<":
            # An HTML page with a 200 status is the register's sign-in page —
            # in practice this means the email/key pair wasn't accepted.
            raise EpcError(
                "The EPC register returned its sign-in page instead of data, "
                "which means the credentials were not accepted. " + BAD_CREDENTIALS_HINT
            )
        else:
            rows = (resp.json() or {}).get("rows", [])
    except requests.RequestException as exc:
        raise EpcError(f"Could not reach the EPC register: {exc}") from exc
    except ValueError as exc:
        raise EpcError(
            "EPC register returned an unreadable response (not JSON). " + BAD_CREDENTIALS_HINT
        ) from exc
    _postcode_rows_cache[postcode] = rows
    return rows


def epc_for_properties(properties: list) -> dict:
    """Map property id -> {'rooms': int|None, 'floor_area': float|None}
    from the most recent EPC whose address matches the property's PAON
    (and SAON if present). floor_area is the certificate's total internal
    floor area in square metres. Properties without a confident match are
    absent from the result."""
    if not configured():
        return {}

    by_postcode = {}
    for p in properties:
        pc = " ".join((p.get("postcode") or "").split()).upper()
        if pc:
            by_postcode.setdefault(pc, []).append(p)

    results = {}
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
                lodged = str(row.get("lodgement-date") or "")
                if best is None or lodged > best[0]:
                    best = (lodged, row)
            if not best:
                continue
            row = best[1]
            entry = {"rooms": None, "floor_area": None}
            try:
                entry["rooms"] = int(float(row.get("number-habitable-rooms")))
            except (TypeError, ValueError):
                pass
            try:
                area = float(row.get("total-floor-area"))
                if area > 0:
                    entry["floor_area"] = area
            except (TypeError, ValueError):
                pass
            if entry["rooms"] is not None or entry["floor_area"] is not None:
                results[p["id"]] = entry
    return results
