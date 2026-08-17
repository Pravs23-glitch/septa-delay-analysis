# SEPTA bus delay analysis

Collecting real-time vehicle data from SEPTA's TransitView API to look at how bus
delay varies by route, stop, and time of day across Philadelphia.

**Status:** collecting, unattended, with a first round of analysis below. A GitHub
Actions job polls on a schedule and commits results back to this repo.

## Why

Most transit delay reporting is aggregate — a system-wide on-time percentage, published
monthly. That average hides the thing riders actually experience, which is that a
specific bus at a specific stop at a specific hour is unreliable. This project collects
vehicle-level observations continuously so that question can be asked directly.

SEPTA publishes this data in real time but keeps no public archive of it. The feed shows
you where the buses are right now, and that's all. Anything historical has to be captured
as it goes by, which is what this repo is: an archive that only exists because something
was running when the data was live.

## How it works

`septa_collect.py` polls the TransitView endpoint for a set of routes and records every
vehicle observation. It has two output modes.

```
python3 septa_collect.py                     # one snapshot -> SQLite
python3 septa_collect.py --loop 900          # every 15 minutes -> SQLite
python3 septa_collect.py --routes 21 42 47   # pick routes
python3 septa_collect.py --jsonl data        # append raw records to data/YYYY-MM-DD.jsonl
```

`rebuild_db.py` reconstructs the SQLite database from the JSONL files:

```
python3 rebuild_db.py
```

No dependencies beyond the Python standard library.

### Architecture: JSONL is the source of truth

The scheduled job runs on an ephemeral runner — a fresh machine every 15 minutes, wiped
when the job ends. Nothing survives except what gets committed back to the repo, and a
binary SQLite file is a poor thing to version control: every write rewrites the file, so
each run would commit a full copy and conflicts would be unresolvable.

So the cloud collector appends newline-delimited JSON instead. Appending is the only
operation, which makes conflicts rare and diffs readable, and the database becomes a
derived artifact that can be rebuilt from scratch at any time. If the schema needs to
change, the raw records are still there to rebuild from.

### Schema

`vehicle_observations` — one row per vehicle per snapshot. Vehicle ID, route, direction,
position, minutes late, next stop, trip and block IDs, seat availability, plus the full
raw JSON payload in a `raw` column.

`collection_runs` — one row per route per polling pass, recording success or failure and
the exception detail when a fetch fails. Without this, gaps in the observation table are
ambiguous: no way to distinguish "no buses running" from "the API timed out".

## Data quality notes

Several problems showed up in the first hours of collection. All are documented here
rather than silently filtered, because they change how the data has to be read.

**Sentinel values and ghost records are the same problem.** Values of 998 and 999 appear
in the `late` field regularly. These
are not delays — no bus is sixteen hours behind schedule. They appear to indicate that
no prediction is available for that vehicle. Their effect is severe: on one early
snapshot, route 21 averaged 275 minutes late. Excluding values above 900 brought the same
route in line with the others, in the 2–5 minute range. Any analysis has to filter these
or the results are meaningless.

Separately, some rows arrive with a vehicle ID of `0`, an empty string, or the literal
string `None`, with no next stop. Over twelve days these two categories turned out to be
almost entirely the same rows: 4,493 sentinel delays and 4,424 ghost IDs out of 4,494
records dropped. They are one phenomenon — placeholder entries the feed emits when it has
nothing real to report — and together they are 39% of everything collected.

**Negative delays are real.** A `late` value of -1 or -2 means the bus is running ahead of
schedule. This is a genuine phenomenon and arguably worse for riders than a late bus,
since an early bus is one you miss entirely. These are kept.

**Snapshot polling oversamples slow vehicles.** A bus stuck in traffic appears in more
consecutive snapshots than one moving normally, so a naive average over all rows weights
delayed vehicles more heavily. This is a real bias, not a bug, and there are two honest
ways to handle it: deduplicate to one observation per vehicle per trip, or frame the
metric as "delay experienced by a rider arriving at a random moment," which is arguably
what a rider cares about anyway. Whichever is used has to be stated.

### Design decision: raw in, clean downstream

The collector writes exactly what the API returns, including the malformed rows. Cleaning
happens in a separate modeled layer rather than at collection time. Data that gets
filtered at ingest is unrecoverable, and the malformed rows are themselves worth
analyzing — how often the feed degrades is a question about the system.

## Findings

Twelve days of collection, 11,377 observations, 6,883 after cleaning.

### Route 47 is on time exactly when traffic is worst

Average weekday delay, in minutes:

| hour | route 21 | route 42 | route 47 |
|------|---------:|---------:|---------:|
| 07:00 | 0.50 | 2.47 | **0.29** |
| 08:00 | 2.66 | 3.34 | **0.26** |
| 12:00 | 1.85 | 3.81 | 5.72 |
| 15:00 | 2.88 | 3.99 | **1.12** |
| 16:00 | 3.20 | 4.49 | **1.18** |
| 19:00 | 2.63 | 4.20 | 7.07 |

Routes 21 and 42 drift between roughly 1 and 4.5 minutes with no strong daily
structure. Route 47 does something different: it is close to perfectly on time at
both rush peaks and worst at midday and in the evening.

### It is not a service-level effect

The obvious explanation is that fewer buses run off-peak, so a single delay has
nothing to absorb it. The vehicle counts rule that out for most of the day:

| hour | buses running | avg late |
|------|--------------:|---------:|
| 16:00 | 14.5 | 1.18 |
| 17:00 | 14.5 | 3.22 |
| 18:00 | 14.0 | 5.44 |

Service is flat across those three hours while delay rises more than fourfold.
Midday says the same thing — 12.4 buses, near the daily maximum, and 5.72 minutes
late. Thin service cannot be what is driving this.

What remains is schedule padding. Rush-hour timetables appear to carry enough
slack that buses beat them, and off-peak timetables do not. On that reading, this
metric is not measuring congestion. It is measuring how honest the published
schedule is at a given hour, which is a different question and arguably a more
useful one.

The 21:00–00:00 window is the one place thin service may genuinely matter — delay
runs 7 to 10 minutes on 3 to 7 vehicles — but there are only 7 to 26 observations
per hour there, which is not enough to claim anything.

### Caveats, quantified

**Sampling is uneven.** Scheduled runs on shared GitHub infrastructure are
best-effort. Against a requested 15-minute cadence, actual intervals averaged
closer to 30–60 minutes and varied by day. Per-hour observation counts are
reported alongside every average so thin cells are visible rather than hidden.

**Polling bias is real but small.** A stuck bus appears in more consecutive
snapshots than a moving one, which should inflate the naive average.
Deduplicating to one observation per vehicle per trip moves route 47 from 4.42 to
4.04 minutes, route 21 from 2.55 to 2.33, and route 42 from 3.39 to 3.30 — around
9% at most, in the predicted direction. Worth reporting; changes no conclusion.

**Weekend behaviour is unexplained.** Route 47 averages 6.0 minutes on weekends
against 3.42 on weekdays, and route 21 is also worse, while route 42 is flat.
Weekend timetables are usually more generous, not less, so this cuts against the
padding explanation and has not been resolved.

## Roadmap

- [x] Collector writing to SQLite
- [x] Scheduling moved off a laptop and into GitHub Actions
- [x] First analysis: delay by hour, weekday/weekend, bias check
- [ ] dbt models: clean observations, delay by stop, delay by hour
- [ ] Tests for nulls, duplicates, and sentinel leakage
- [ ] Dashboard

## Data source

SEPTA TransitView API — `https://www3.septa.org/api/TransitView/index.php?route={route}`.
Public, no key required. Documentation via
[OpenDataPhilly](https://opendataphilly.org/organizations/septa/).
