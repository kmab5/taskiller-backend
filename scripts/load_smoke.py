"""Tiny dependency-free HTTP concurrency smoke test for a deployed Taskiller API."""

from __future__ import annotations

import argparse
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _request(url: str, timeout: float) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    return status, (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description="Taskiller deployment smoke-load check")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        raise SystemExit("--requests and --concurrency must be positive")
    url = args.base_url.rstrip("/") + "/health/live"
    statuses: list[int] = []
    durations: list[float] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(_request, url, args.timeout) for _ in range(args.requests)]
        for future in as_completed(futures):
            status, duration = future.result()
            statuses.append(status)
            durations.append(duration)

    failures = sum(status != 200 for status in statuses)
    sorted_durations = sorted(durations)
    p95_index = max(0, min(len(sorted_durations) - 1, round(0.95 * len(sorted_durations)) - 1))
    print(
        f"requests={len(statuses)} failures={failures} "
        f"mean_ms={statistics.fmean(durations):.2f} p95_ms={sorted_durations[p95_index]:.2f}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
