"""
Poll SEPTA TransitView for a set of routes and append each snapshot to a local
SQLite database.

Week 1 goal: run this by hand, confirm rows land, then let it run on a schedule.
Snowflake comes later -- SQLite first so nothing depends on a cloud account
while the shape of the data is still being figured out.

Usage:
    python septa_collect.py
    python septa_collect.py --routes 21 42 47 --db septa.db
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://www3.septa.org/api/TransitView/index.php?route={route}"
DEFAULT_ROUTES = ["21", "42", "47"]


def fetch_route(route, timeout=15):
    """Return the raw list of vehicle dicts for one route."""
    url = API.format(route=route)
    req = urllib.request.Request(url, headers={"User-Agent": "septa-delay-study/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)

    # TransitView has returned both a bare list and {"bus": [...]} over the years.
    # Handle both rather than assuming.
    if isinstance(payload, dict):
        for key in ("bus", "vehicles", "routes"):
            if key in payload:
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"unexpected payload shape for route {route}: {type(payload)}")
    return payload


def to_row(route, vehicle, collected_at):
    """Flatten one vehicle observation into the columns we care about."""
    def num(key):
        v = vehicle.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return (
        collected_at,
        route,
        str(vehicle.get("VehicleID") or vehicle.get("label") or ""),
        vehicle.get("Direction"),
        vehicle.get("destination"),
        num("lat"),
        num("lng"),
        num("late"),
        str(vehicle.get("next_stop_id") or ""),
        vehicle.get("next_stop_name"),
        num("next_stop_sequence"),
        str(vehicle.get("trip") or ""),
        str(vehicle.get("BlockID") or ""),
        vehicle.get("estimated_seat_availability"),
        num("Offset_sec"),
        json.dumps(vehicle, sort_keys=True),
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle_observations (
    collected_at            TEXT NOT NULL,
    route                   TEXT NOT NULL,
    vehicle_id              TEXT NOT NULL,
    direction               TEXT,
    destination             TEXT,
    lat                     REAL,
    lng                     REAL,
    minutes_late            REAL,
    next_stop_id            TEXT,
    next_stop_name          TEXT,
    next_stop_sequence      REAL,
    trip_id                 TEXT,
    block_id                TEXT,
    seat_availability       TEXT,
    offset_sec              REAL,
    raw                     TEXT,
    PRIMARY KEY (collected_at, route, vehicle_id)
);

CREATE TABLE IF NOT EXISTS collection_runs (
    started_at   TEXT NOT NULL,
    route        TEXT NOT NULL,
    status       TEXT NOT NULL,
    row_count    INTEGER,
    detail       TEXT
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def collect(conn, routes):
    """One pass over all routes. Returns total rows written."""
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = 0

    for route in routes:
        try:
            vehicles = fetch_route(route)
        except (urllib.error.URLError, ValueError, json.JSONDecodeError, TimeoutError) as e:
            # Log the failure and keep going -- one bad route shouldn't kill the run.
            conn.execute(
                "INSERT INTO collection_runs VALUES (?,?,?,?,?)",
                (started_at, route, "error", 0, f"{type(e).__name__}: {e}"),
            )
            conn.commit()
            print(f"  route {route}: FAILED ({type(e).__name__}: {e})", file=sys.stderr)
            continue

        rows = [to_row(route, v, started_at) for v in vehicles]
        conn.executemany(
            "INSERT OR IGNORE INTO vehicle_observations VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "INSERT INTO collection_runs VALUES (?,?,?,?,?)",
            (started_at, route, "ok", len(rows), None),
        )
        conn.commit()
        total += len(rows)
        print(f"  route {route}: {len(rows)} vehicles")

    return total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--routes", nargs="+", default=DEFAULT_ROUTES)
    p.add_argument("--db", default="septa.db")
    p.add_argument("--loop", type=int, metavar="SECONDS",
                   help="poll repeatedly every N seconds instead of once")
    args = p.parse_args()

    conn = connect(args.db)

    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] collecting {', '.join(args.routes)}")
        total = collect(conn, args.routes)
        print(f"  wrote {total} rows -> {args.db}")

        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
