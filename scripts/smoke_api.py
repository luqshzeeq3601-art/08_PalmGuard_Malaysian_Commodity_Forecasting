"""Smoke test script for PalmGuard REST API.

Checks /health, /ready, /forecast, /history, and /monitoring.
Usage:
    python scripts/smoke_api.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def run_smoke_test(base_url: str, max_retries: int = 10, delay: float = 2.0) -> int:
    base = base_url.rstrip("/")
    print(f"[*] Starting PalmGuard API Smoke Test against: {base}")

    client = httpx.Client(timeout=10.0)

    # 1. Health & Readiness polling (tolerates container cold starts)
    ready = False
    for attempt in range(1, max_retries + 1):
        try:
            r = client.get(f"{base}/health")
            if r.status_code == 200:
                print(f"[*] /health responded: {r.status_code} (attempt {attempt})")
                r_ready = client.get(f"{base}/ready")
                if r_ready.status_code == 200:
                    print(f"[*] /ready responded: {r_ready.status_code} -> {r_ready.json()}")
                    ready = True
                    break
        except httpx.RequestError as exc:
            print(
                f"[-] Connection attempt {attempt}/{max_retries} failed ({exc}). Retrying in {delay}s..."
            )
        time.sleep(delay)

    if not ready:
        print("[!] Service did not become ready in time.")
        return 1

    # 2. Check /forecast
    r_fc = client.get(f"{base}/forecast")
    if r_fc.status_code != 200:
        print(f"[!] /forecast failed with status {r_fc.status_code}")
        return 1
    fc_data = r_fc.json()
    forecasts = fc_data.get("forecasts", [])
    print(f"[*] /forecast returned {len(forecasts)} forecasts.")
    if len(forecasts) < 2:
        print("[!] /forecast returned fewer than expected forecasts.")
        return 1

    # 3. Check /forecast with parameters
    r_fc_param = client.get(f"{base}/forecast?series=palm_wb_myr&horizon=1")
    if r_fc_param.status_code != 200:
        print(
            f"[!] /forecast?series=palm_wb_myr&horizon=1 failed with status {r_fc_param.status_code}"
        )
        return 1
    print("[*] Parameterized /forecast test PASS.")

    # 4. Check /history
    r_hist = client.get(f"{base}/history?limit=5")
    if r_hist.status_code != 200:
        print(f"[!] /history failed with status {r_hist.status_code}")
        return 1
    print(f"[*] /history returned count={r_hist.json().get('count')}")

    # 5. Check /monitoring
    r_mon = client.get(f"{base}/monitoring")
    if r_mon.status_code != 200:
        print(f"[!] /monitoring failed with status {r_mon.status_code}")
        return 1
    print("[*] /monitoring test PASS.")

    print("=== All API Smoke Tests PASSED ===")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="PalmGuard API Smoke Test")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Base URL of PalmGuard API"
    )
    parser.add_argument(
        "--retries", type=int, default=10, help="Max retry attempts for cold starts"
    )
    args = parser.parse_args()

    sys.exit(run_smoke_test(args.base_url, max_retries=args.retries))


if __name__ == "__main__":
    main()
