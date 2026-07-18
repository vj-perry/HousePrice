"""One-time builder for the local OS Open UPRN lookup database.

Downloads OS Open UPRN (free, Open Government Licence) from Ordnance
Survey's public downloads API and loads it into an SQLite database that
uprn_db.py queries. Roughly a 700MB download and a ~2GB database; the
build takes 10-20 minutes depending on the machine.

Usage:
    python3 build_uprn_db.py                # download and build
    python3 build_uprn_db.py path/to.zip    # build from an already-
                                            # downloaded OS Open UPRN zip

If the automatic download fails, fetch the CSV zip manually from
https://osdatahub.os.uk/downloads/open/OpenUPRN and pass its path.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import sys
import zipfile

import requests

from uprn_db import DB_PATH

DOWNLOAD_LIST_URL = "https://api.os.uk/downloads/v1/products/OpenUPRN/downloads?format=CSV"
BATCH = 50000


def find_download_url():
    print("Asking Ordnance Survey for the current OS Open UPRN download...")
    resp = requests.get(DOWNLOAD_LIST_URL, timeout=60)
    resp.raise_for_status()
    items = resp.json()
    for item in items:
        if "CSV" in str(item.get("format", "")).upper():
            return item["url"]
    raise RuntimeError(f"No CSV download listed at {DOWNLOAD_LIST_URL}")


def download_zip(target_path):
    url = find_download_url()
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=120, allow_redirects=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        next_report = 5
        with open(target_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total and done * 100 // total >= next_report:
                    print(f"  downloaded {done // (1 << 20)}MB ({done * 100 // total}%)")
                    next_report += 5
    print(f"Download complete ({done // (1 << 20)}MB).")


def build_db(zip_path):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    tmp_db = DB_PATH + ".building"
    if os.path.exists(tmp_db):
        os.remove(tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("CREATE TABLE uprn (uprn INTEGER PRIMARY KEY, lat REAL, lng REAL) WITHOUT ROWID")

    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError(f"No CSV found inside {zip_path}")
        name = csv_names[0]
        print(f"Loading {name} into {DB_PATH} ...")
        with zf.open(name) as raw:
            # utf-8-sig strips the byte-order mark OS ships at the start
            # of the file (it otherwise corrupts the first column name)
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            header = [h.strip().lstrip("﻿").upper() for h in next(reader)]
            try:
                i_uprn = header.index("UPRN")
                i_lat = header.index("LATITUDE")
                i_lng = header.index("LONGITUDE")
            except ValueError:
                raise RuntimeError(f"Unexpected CSV columns: {header}")

            batch = []
            count = 0
            for row in reader:
                try:
                    batch.append((int(row[i_uprn]), float(row[i_lat]), float(row[i_lng])))
                except (ValueError, IndexError):
                    continue
                if len(batch) >= BATCH:
                    conn.executemany("INSERT OR REPLACE INTO uprn VALUES (?,?,?)", batch)
                    conn.commit()
                    count += len(batch)
                    batch = []
                    if count % 2000000 == 0:
                        print(f"  {count // 1000000}M rows loaded...")
            if batch:
                conn.executemany("INSERT OR REPLACE INTO uprn VALUES (?,?,?)", batch)
                conn.commit()
                count += len(batch)

    conn.close()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.rename(tmp_db, DB_PATH)
    print(f"Done — {count:,} properties indexed at {DB_PATH}")


def main():
    if len(sys.argv) > 1:
        zip_path = sys.argv[1]
        if not os.path.exists(zip_path):
            sys.exit(f"File not found: {zip_path}")
        build_db(zip_path)
        return

    # Keep the download next to the database so a failed build never
    # costs a re-download; it is only removed after a successful build.
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    kept_zip = os.path.join(os.path.dirname(DB_PATH), "os_open_uprn_download.zip")
    if os.path.exists(kept_zip):
        print(f"Reusing previously downloaded {kept_zip}")
    else:
        download_zip(kept_zip)
    build_db(kept_zip)
    os.remove(kept_zip)


if __name__ == "__main__":
    main()
