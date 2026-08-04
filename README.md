# SEPTA bus delay analysis

Collecting real-time vehicle data from SEPTA's TransitView API to look at how bus
delay varies by route, stop, and time of day across Philadelphia.

**Status:** collecting. Analysis and dashboard to follow once there's enough history
to say anything with a straight face.

## Why

Most transit delay reporting is aggregate — a system-wide on-time percentage, published
monthly. That average hides the thing riders actually experience, which is that a
specific bus at a specific stop at a specific hour is unreliable. This project collects
vehicle-level observations continuously so that question can be asked directly.

## How it works

`septa_collect.py` polls the TransitView endpoint for a set of routes and appends every
vehicle observation to a local SQLite database.

```
python3 septa_collect.py                    # one snapshot
python3 septa_collect.py --loop 900         # every 15 minutes
python3 septa_collect.py --routes 21 42 47  # pick routes
```

No dependencies beyond the Python standard library.

### Schema

`vehicle_observations` — one row per vehicle per snapshot. Vehicle ID, route, direction,
position, minutes late, next stop, trip and block IDs, seat availability, plus the full
raw JSON payload in a `raw` column.

`collection_runs` — one row per route per polling pass, recording success or failure and
the exception detail when a fetch fails. Without this, gaps in the observation table are
ambiguous: no way to distinguish "no buses running" from "the API timed out".

## Data quality notes

Two problems showed up in the first hour of collection. Both are documented here rather
than silently filtered, because they change how the data has to be read.

**Sentinel values in the `late` field.** Values of 998 and 999 appear regularly. These
are not delays — no bus is sixteen hours behind schedule. They appear to indicate that
no prediction is available for that vehicle. Their effect is severe: on one early
snapshot, route 21 averaged 275 minutes late. Excluding values above 900 brought the same
route in line with the others, in the 2–5 minute range. Any analysis has to filter these
or the results are meaningless.

**Ghost vehicle records.** Some rows arrive with a vehicle ID of `0`, an empty string, or
the literal string `None`. These records generally have no next stop and carry a sentinel
`late` value. They appear to be placeholder entries rather than real vehicles.

**Negative delays are real.** A `late` value of -1 or -2 means the bus is running ahead of
schedule. This is a genuine phenomenon and arguably worse for riders than a late bus,
since an early bus is one you miss entirely. These are kept.

### Design decision: raw in, clean downstream

The collector writes exactly what the API returns, including the malformed rows. Cleaning
happens in a separate modeled layer rather than at collection time. Data that gets
filtered at ingest is unrecoverable, and the malformed rows are themselves worth
analyzing — how often the feed degrades is a question about the system.

## Roadmap

- [x] Collector writing to SQLite
- [ ] Move scheduling off a laptop and into GitHub Actions
- [ ] dbt models: clean observations, delay by stop, delay by hour
- [ ] Tests for nulls, duplicates, and sentinel leakage
- [ ] Dashboard

## Data source

SEPTA TransitView API — `https://www3.septa.org/api/TransitView/index.php?route={route}`.
Public, no key required. Documentation via
[OpenDataPhilly](https://opendataphilly.org/organizations/septa/).
