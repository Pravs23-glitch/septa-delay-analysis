"""
Rebuild the SQLite database from the raw JSON-lines log in data/.

The JSONL files are the source of truth -- they hold exactly what the API
returned. This script derives a queryable database from them. Because the raw
log is preserved, parsing can change and the database can simply be rebuilt
rather than re-collected.

Usage:
    python3 rebuild_db.py                      # data/ -> septa.db
    python3 rebuild_db.py --data data --db septa.db
"""

import argparse
import glob
import json
import os
import sqlite3

import septa_collect as sc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data")
    p.add_argument("--db", default="septa.db")
    args = p.parse_args()

    if os.path.exists(args.db):
        os.remove(args.db)

    conn = sc.connect(args.db)
    files = sorted(glob.glob(os.path.join(args.data, "*.jsonl")))
    if not files:
        print(f"no .jsonl files found in {args.data}/")
        return

    total, errors = 0, 0
    for path in files:
        rows, run_rows = [], []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)

                if rec.get("status") == "error":
                    run_rows.append((rec["collected_at"], rec["route"], "error", 0,
                                     rec.get("detail")))
                    errors += 1
                    continue

                rows.append(sc.to_row(rec["route"], rec["vehicle"], rec["collected_at"]))

        conn.executemany(sc.INSERT_SQL, rows)
        conn.executemany("INSERT INTO collection_runs VALUES (?,?,?,?,?)", run_rows)
        conn.commit()
        total += len(rows)
        print(f"  {os.path.basename(path)}: {len(rows)} observations")

    print(f"\nrebuilt {args.db}: {total} observations, {errors} failed fetches")


if __name__ == "__main__":
    main()
