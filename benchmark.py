"""Measure real client RTT and decoded response sizes; not packet-level traffic."""
import argparse
import csv
import json
import os
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--request-json", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1 or args.warmup < 0:
        parser.error("count >= 1 and warmup >= 0 are required")
    payload = json.loads(args.request_json.read_text())
    rows = []
    with httpx.Client(timeout=180, headers={"Authorization": f'Bearer {os.environ["SYNCMESH_TOKEN"]}'},
                      follow_redirects=False, trust_env=False) as client:
        for iteration in range(-args.warmup, args.count):
            start = time.perf_counter()
            status, size, partial, error = None, None, None, None
            try:
                response = client.post(args.url.rstrip("/") + "/request", json=payload)
                status, size = response.status_code, len(response.content)
                response.raise_for_status()
                partial = response.json().get("partial")
            except Exception as exc:
                error = type(exc).__name__
            elapsed = (time.perf_counter()-start)*1000
            if iteration >= 0:
                rows.append(dict(request_index=iteration, rtt_ms=elapsed, status=status,
                                 decoded_response_bytes=size, partial=partial, error=error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} actual request observations. No paper benchmark result is implied.")


if __name__ == "__main__":
    main()
