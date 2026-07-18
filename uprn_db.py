"""Local UPRN -> coordinates lookup built from OS Open UPRN.

OS Open UPRN is Ordnance Survey's free, openly licensed dataset of exact
coordinates for every UPRN (unique property reference number) in Great
Britain. EPC records carry a property's UPRN, so joining the two gives
rooftop-accurate map positions without any paid geocoding service.

Build the database once with:  python3 build_uprn_db.py
(see that script for download details; ~700MB download, ~2GB database)

Contains OS data © Crown copyright and database right; licensed under
the Open Government Licence v3.0.
"""
from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get("UPRN_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "os_open_uprn.sqlite"
)


def available() -> bool:
    return os.path.exists(DB_PATH)


def lookup(uprns: list) -> dict:
    """Map each valid UPRN (str or int) to {'lat': .., 'lng': ..}.
    Unknown UPRNs are absent from the result."""
    if not uprns or not available():
        return {}

    clean = []
    for u in uprns:
        try:
            clean.append(int(str(u).strip()))
        except (TypeError, ValueError):
            continue
    if not clean:
        return {}

    out = {}
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        for i in range(0, len(clean), 500):
            chunk = clean[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            for uprn, lat, lng in cur.execute(
                f"SELECT uprn, lat, lng FROM uprn WHERE uprn IN ({placeholders})",
                chunk,
            ):
                out[str(uprn)] = {"lat": lat, "lng": lng}
    finally:
        conn.close()
    return out
