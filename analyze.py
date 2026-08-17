#!/usr/bin/env python3
"""
Analysis of SEPTA delay data.

Reads septa.db (built by rebuild_db.py) and prints four sections:
  1. Coverage and sampling
  2. Weekday vs weekend by route
  3. Delay by hour of day, per route
  4. The route 47 question: is evening delay about traffic or about service level?

All times converted from UTC to Philadelphia local (EDT, UTC-4).
Sentinel values (>= 900) and ghost vehicle records are excluded.
"""

import sqlite3
import sys

DB = "septa.db"

# Shared filter: drop sentinel delays and placeholder vehicle records.
CLEAN = """
    minutes_late IS NOT NULL
    AND minutes_late < 900
    AND vehicle_id NOT IN ('0', '', 'None')
"""

# collected_at is UTC; Philadelphia is UTC-4 in August.
LOCAL = "datetime(collected_at, '-4 hours')"


def q(conn, sql):
    return conn.execute(sql).fetchall()


def rule(title):
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def main():
    try:
        conn = sqlite3.connect(DB)
    except sqlite3.Error as e:
        sys.exit(f"could not open {DB}: {e}")

    # ---------------------------------------------------------------
    rule("1. COVERAGE AND SAMPLING")

    total = q(conn, "SELECT COUNT(*) FROM vehicle_observations")[0][0]
    clean = q(conn, f"SELECT COUNT(*) FROM vehicle_observations WHERE {CLEAN}")[0][0]
    print(f"\nTotal observations:      {total:,}")
    print(f"After cleaning:          {clean:,}  ({100*clean/total:.1f}%)")
    print(f"Dropped:                 {total-clean:,}")

    print("\nWhat got dropped, and why:")
    rows = q(conn, """
        SELECT
          SUM(CASE WHEN minutes_late >= 900 THEN 1 ELSE 0 END),
          SUM(CASE WHEN vehicle_id IN ('0','','None') THEN 1 ELSE 0 END),
          SUM(CASE WHEN minutes_late IS NULL THEN 1 ELSE 0 END)
        FROM vehicle_observations
    """)[0]
    print(f"  sentinel delay (>=900):     {rows[0] or 0:,}")
    print(f"  ghost vehicle record:       {rows[1] or 0:,}")
    print(f"  null delay:                 {rows[2] or 0:,}")
    print("  (categories overlap, so these will not sum to the dropped total)")

    print("\nObservations per day — uneven sampling is a GitHub scheduling artifact:")
    print(f"\n  {'date':<12} {'day':<5} {'obs':>7}")
    print("  " + "-" * 26)
    for day, dow, n in q(conn, f"""
        SELECT date({LOCAL}),
               CASE strftime('%w', {LOCAL})
                 WHEN '0' THEN 'Sun' WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue'
                 WHEN '3' THEN 'Wed' WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri'
                 ELSE 'Sat' END,
               COUNT(*)
        FROM vehicle_observations
        WHERE {CLEAN}
        GROUP BY 1 ORDER BY 1
    """):
        print(f"  {day:<12} {dow:<5} {n:>7,}")

    # ---------------------------------------------------------------
    rule("2. WEEKDAY VS WEEKEND")

    print(f"\n  {'route':<7} {'period':<9} {'avg late':>9} {'median':>8} {'p90':>7} {'obs':>7}")
    print("  " + "-" * 50)
    for route, period, avg, med, p90, n in q(conn, f"""
        WITH tagged AS (
          SELECT route,
                 CASE WHEN strftime('%w', {LOCAL}) IN ('0','6')
                      THEN 'weekend' ELSE 'weekday' END AS period,
                 minutes_late
          FROM vehicle_observations
          WHERE {CLEAN}
        ),
        ranked AS (
          SELECT route, period, minutes_late,
                 ROW_NUMBER() OVER (PARTITION BY route, period ORDER BY minutes_late) AS rn,
                 COUNT(*)    OVER (PARTITION BY route, period) AS n
          FROM tagged
        )
        SELECT route, period,
               ROUND(AVG(minutes_late), 2),
               ROUND(MAX(CASE WHEN rn = (n+1)/2 THEN minutes_late END), 1),
               ROUND(MAX(CASE WHEN rn = (n*9)/10 THEN minutes_late END), 1),
               MAX(n)
        FROM ranked
        GROUP BY route, period
        ORDER BY route, period
    """):
        print(f"  {route:<7} {period:<9} {avg:>9} {med:>8} {p90:>7} {n:>7,}")

    print("\n  Median is the typical trip. p90 is the bad day — the 1-in-10 that")
    print("  makes someone late for work. The gap between them is the real story.")

    # ---------------------------------------------------------------
    rule("3. DELAY BY HOUR OF DAY (weekdays only)")

    for route in ('21', '42', '47'):
        print(f"\n  Route {route}")
        print(f"  {'hour':<6} {'avg late':>9} {'obs':>6}  {'':<30}")
        print("  " + "-" * 55)
        rows = q(conn, f"""
            SELECT CAST(strftime('%H', {LOCAL}) AS INTEGER),
                   ROUND(AVG(minutes_late), 2),
                   COUNT(*)
            FROM vehicle_observations
            WHERE {CLEAN}
              AND route = '{route}'
              AND strftime('%w', {LOCAL}) NOT IN ('0','6')
            GROUP BY 1 ORDER BY 1
        """)
        peak = max((abs(r[1]) for r in rows), default=1) or 1
        for hour, avg, n in rows:
            bar = "#" * int(round(20 * abs(avg) / peak))
            flag = " (thin)" if n < 30 else ""
            print(f"  {hour:02d}:00 {avg:>9} {n:>6}  {bar}{flag}")

    # ---------------------------------------------------------------
    rule("4. ROUTE 47: TRAFFIC, OR SERVICE LEVEL?")

    print("""
  The puzzle: route 47 looked best during afternoon rush and worst late
  at night. Two explanations fit.

    (a) Schedule padding. Rush-hour timetables build in slack, so buses
        beat a generous schedule. Evening timetables are tighter, so
        ordinary variation registers as "late."

    (b) Thin service. Fewer buses at night means longer headways and no
        spare vehicle to absorb a problem, so one delay propagates.

  These make different predictions about vehicle counts. Under (b), the
  worst hours should be the hours with the fewest buses running. Under
  (a), delay and vehicle count should not track each other closely.
""")
    print(f"  {'hour':<6} {'avg late':>9} {'buses':>7} {'obs':>7}")
    print("  " + "-" * 33)
    for hour, avg, buses, n in q(conn, f"""
        SELECT CAST(strftime('%H', {LOCAL}) AS INTEGER),
               ROUND(AVG(minutes_late), 2),
               ROUND(COUNT(DISTINCT vehicle_id) * 1.0
                     / COUNT(DISTINCT date({LOCAL})), 1),
               COUNT(*)
        FROM vehicle_observations
        WHERE {CLEAN}
          AND route = '47'
          AND strftime('%w', {LOCAL}) NOT IN ('0','6')
        GROUP BY 1 ORDER BY 1
    """):
        print(f"  {hour:02d}:00 {avg:>9} {buses:>7} {n:>7}")

    print("\n  'buses' = distinct vehicles seen in that hour, averaged per day.")

    # ---------------------------------------------------------------
    rule("5. POLLING BIAS CHECK")

    print("""
  A stuck bus shows up in more consecutive snapshots than a moving one,
  so averaging every row overweights delayed vehicles. Below: the naive
  average against one-observation-per-vehicle-per-trip. If these differ
  much, the raw number is inflated and the analysis has to say so.
""")
    print(f"  {'route':<7} {'all rows':>10} {'deduped':>10} {'diff':>8}")
    print("  " + "-" * 38)
    for route, naive, dedup in q(conn, f"""
        WITH d AS (
          SELECT route, trip_id, vehicle_id, AVG(minutes_late) AS trip_avg
          FROM vehicle_observations
          WHERE {CLEAN} AND trip_id IS NOT NULL AND trip_id != ''
          GROUP BY route, trip_id, vehicle_id
        )
        SELECT v.route,
               ROUND(AVG(v.minutes_late), 2),
               ROUND((SELECT AVG(trip_avg) FROM d WHERE d.route = v.route), 2)
        FROM vehicle_observations v
        WHERE {CLEAN}
        GROUP BY v.route ORDER BY v.route
    """):
        if naive is None or dedup is None:
            print(f"  {route:<7} {'n/a':>10} {'n/a':>10} {'':>8}")
        else:
            print(f"  {route:<7} {naive:>10} {dedup:>10} {dedup-naive:>+8.2f}")

    conn.close()
    print()


if __name__ == "__main__":
    main()
