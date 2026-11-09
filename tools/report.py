#!/usr/bin/env python3
"""Summarize Taxile append-only CSV as local-day mileage and per-trip mileage."""
import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def summarize(paths, tz_name="America/Chicago"):
    tz = ZoneInfo(tz_name)
    daily = defaultdict(float)
    trips = defaultdict(float)
    invalid_time_miles = 0.0
    rows = 0
    duplicates = 0
    seen = set()
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as fp:
            for row in csv.DictReader(fp):
                if row.get("event", row.get("type")) != "SAMPLE":
                    continue
                try:
                    miles = float(row["delta_miles"])
                    epoch = int(row["epoch_utc"] or 0)
                    valid = row.get("time_valid", "1" if epoch else "0") == "1"
                    boot = row["boot_id"]
                    trip = row["trip_id"]
                    uptime = row["uptime_ms"]
                    if not 0 <= miles < 10:  # sanity bound per 2-sec interval
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
                device = row.get("device_id", "legacy")
                vin = row.get("vin", "")
                vehicle = row.get("vehicle_id") or vin or f"legacy-{device}-{boot}"
                key = (device, row.get("event_id") or (boot, trip, uptime))
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                rows += 1
                trips[(vehicle, device, boot, trip)] += miles
                if valid and epoch >= 1704067200:
                    day = datetime.fromtimestamp(epoch, timezone.utc).astimezone(tz).date().isoformat()
                    daily[(vehicle, day)] += miles
                else:
                    invalid_time_miles += miles
    return daily, trips, invalid_time_miles, rows, duplicates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="+", help="Downloaded Taxile CSV files")
    parser.add_argument("--tz", default="America/Chicago", help="IANA local timezone")
    parser.add_argument("--out", type=Path, help="Write daily totals to a CSV")
    args = parser.parse_args()
    daily, trips, unknown, n, duplicates = summarize(args.csv, args.tz)
    print(f"Accepted samples: {n}; repeated rows skipped: {duplicates}")
    print("Daily mileage estimates:")
    for (vehicle, day), miles in sorted(daily.items()):
        print(f"  {vehicle} / {day}: {miles:.3f} miles")
    print(f"Distance without valid UTC time: {unknown:.3f} miles (excluded from daily totals)")
    print(f"Trips found: {len(trips)}; total estimated distance: {sum(trips.values()):.3f} miles")
    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as fp:
            w = csv.writer(fp)
            w.writerow(["vehicle_id", "date", "estimated_miles"])
            w.writerows((vehicle, day, f"{miles:.5f}") for (vehicle, day), miles in sorted(daily.items()))
        print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
