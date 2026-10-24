"""Ingest your genuine timezone-aware CSV through local GraphQL mutations."""
import argparse
import csv
import os

import httpx

QUERY = '''mutation($input: MeasurementInput!) {
 createMeasurement(input: $input) { id replica_id }
}'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--url", required=True, help="Target node origin, e.g. http://localhost:8081")
    args = parser.parse_args()
    token = os.environ["SYNCMESH_TOKEN"]
    count = 0
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}, follow_redirects=False, trust_env=False) as client:
        with open(args.csv, newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                values = dict(sensor_id=row["sensor_id"], timestamp=row["timestamp"])
                for field in ("temperature", "humidity", "pressure"):
                    values[field] = float(row[field]) if row.get(field, "").strip() else None
                response = client.post(args.url.rstrip("/")+"/request", json=dict(query=QUERY, variables={"input": values}))
                response.raise_for_status()
                if response.json().get("mode") != "mutation":
                    raise RuntimeError("Unexpected mutation response")
                count += 1
    print(f"Inserted {count} rows. Re-running imports duplicates rows; this is not an idempotent bulk loader.")


if __name__ == "__main__":
    main()
