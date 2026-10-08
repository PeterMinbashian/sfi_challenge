#!/usr/bin/env python3
"""
Full endpoint smoke test for Freight Challenge API (macOS, Linux, Windows).

Prerequisite: API already running, e.g.
  uvicorn app.main:app --host 127.0.0.1 --port 8000

Usage:
  python scripts/smoke_test.py
  python scripts/smoke_test.py --base-url http://127.0.0.1:8000
  python scripts/smoke_test.py --full-body          # no list truncation
  python scripts/smoke_test.py --no-body            # PASS/FAIL only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Callable

import httpx

try:
    import websockets
except ImportError:  # optional; WS check skipped if missing
    websockets = None  # type: ignore

# Module-level flags set in main()
PRINT_BODY = True
FULL_BODY = False
MAX_LIST_ITEMS = 3


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        extra = f"  {detail}" if detail else ""
        print(f"  PASS  {name}{extra}")

    def fail(self, name: str, detail: str = "") -> None:
        self.failed += 1
        extra = f"  {detail}" if detail else ""
        print(f"  FAIL  {name}{extra}")
        self.failures.append(f"{name}: {detail}" if detail else name)


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _truncate_for_display(value: Any, *, depth: int = 0) -> Any:
    """Shrink large lists/dicts for readable smoke-test output."""
    if FULL_BODY:
        return value
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS:
            head = [_truncate_for_display(v, depth=depth + 1) for v in value[:MAX_LIST_ITEMS]]
            return head + [f"... ({len(value) - MAX_LIST_ITEMS} more items, total={len(value)})"]
        return [_truncate_for_display(v, depth=depth + 1) for v in value]
    if isinstance(value, dict):
        # Nested unit lists inside snapshot can be huge
        out = {}
        for k, v in value.items():
            if k == "units" and isinstance(v, list) and len(v) > MAX_LIST_ITEMS and not FULL_BODY:
                out[k] = [
                    *[_truncate_for_display(x, depth=depth + 1) for x in v[:MAX_LIST_ITEMS]],
                    f"... ({len(v) - MAX_LIST_ITEMS} more units, total={len(v)})",
                ]
            else:
                out[k] = _truncate_for_display(v, depth=depth + 1)
        return out
    return value


def print_response(label: str, data: Any, *, status: int | None = None) -> None:
    if not PRINT_BODY:
        return
    header = f"  → response"
    if status is not None:
        header += f" (HTTP {status})"
    if label:
        header += f" [{label}]"
    print(header)
    if data is None or data == "":
        print("    (empty body)")
        return
    if isinstance(data, str):
        lines = data.splitlines()
        preview = lines[:5] if not FULL_BODY else lines
        for line in preview:
            print(f"    {line}")
        if not FULL_BODY and len(lines) > 5:
            print(f"    ... ({len(lines) - 5} more lines, {len(data)} chars total)")
        return
    try:
        text = json.dumps(_truncate_for_display(data), indent=2, default=str)
    except TypeError:
        text = str(data)
    for line in text.splitlines():
        print(f"    {line}")


def expect(
    check: Checker,
    client: httpx.Client,
    name: str,
    method: str,
    path: str,
    *,
    expected: set[int] | None = None,
    json_body: dict | None = None,
    extra: Callable[[Any, httpx.Response], str | None] | None = None,
) -> Any:
    expected = expected or {200}
    if PRINT_BODY:
        req = f"  → {method.upper()} {path}"
        if json_body is not None:
            req += f"  body={json.dumps(json_body, default=str)}"
        print(req)
    try:
        if method.upper() == "GET":
            resp = client.get(path)
        elif method.upper() == "POST":
            resp = client.post(path, json=json_body if json_body is not None else {})
        else:
            resp = client.request(method, path, json=json_body)
    except httpx.HTTPError as exc:
        check.fail(name, str(exc))
        return None

    data: Any = None
    if resp.content:
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            try:
                data = resp.json()
            except json.JSONDecodeError:
                check.fail(name, "invalid JSON")
                print_response(name, resp.text[:500], status=resp.status_code)
                return None
        else:
            data = resp.text

    print_response(name, data if data is not None else resp.text, status=resp.status_code)

    if resp.status_code not in expected:
        check.fail(name, f"HTTP {resp.status_code} (expected {sorted(expected)}); body={resp.text[:200]}")
        return None

    detail = f"HTTP {resp.status_code}"
    if extra:
        msg = extra(data, resp)
        if msg and msg.startswith("FAIL:"):
            check.fail(name, f"{detail}; {msg}")
            return data
        if msg:
            detail = f"{detail}; {msg}"
    check.ok(name, detail)
    return data


def wait_for_order(
    client: httpx.Client,
    *,
    order_type: str | None = None,
    timeout: float = 200.0,
    exclude: set[str] | None = None,
) -> dict:
    exclude = exclude or set()
    deadline = time.time() + timeout
    params: dict[str, str] = {"status": "open"}
    if order_type:
        params["order_type"] = order_type
    while time.time() < deadline:
        orders = as_list(client.get("/orders", params=params).json())
        for order in orders:
            ext = str(order.get("external_id") or "")
            if ext and ext not in exclude:
                return order
        print("  waiting for open order...")
        time.sleep(2)
    label = order_type or "any"
    raise TimeoutError(f"Timed out waiting for open {label} order ({timeout:.0f}s)")


def main() -> int:
    global PRINT_BODY, FULL_BODY

    parser = argparse.ArgumentParser(description="Freight Challenge API full smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--no-body",
        action="store_true",
        help="Do not print request/response bodies (PASS/FAIL lines only)",
    )
    parser.add_argument(
        "--full-body",
        action="store_true",
        help="Print full JSON arrays (default truncates long lists)",
    )
    args = parser.parse_args()
    PRINT_BODY = not args.no_body
    FULL_BODY = bool(args.full_body)
    check = Checker()

    print()
    print("Freight Challenge API - full endpoint smoke test")
    print(f"Base URL: {args.base_url}")
    print("Turbo mode: short order interval + spawn burst so the test finishes quickly.")
    if PRINT_BODY:
        mode = "full JSON" if FULL_BODY else f"JSON (lists capped at {MAX_LIST_ITEMS} items)"
        print(f"Printing API responses: {mode}")
    print()

    saved_interval = 60.0
    saved_speed = 1.0

    try:
        with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
            # --- System ---
            print("--- System ---")
            expect(
                check, client, "GET /health", "GET", "/health",
                extra=lambda j, r: (
                    "FAIL: status not ok" if not j or j.get("status") != "ok" else f"app={j.get('app')}"
                ),
            )

            # --- Turbo board for a fast smoke run ---
            print("\n--- Smoke-test turbo (temporary) ---")
            current = expect(
                check, client, "GET /simulation/settings", "GET", "/simulation/settings",
                extra=lambda j, r: (
                    f"interval={j.get('order_interval_seconds')}s speed={j.get('simulation_speed')}"
                    if j else "FAIL: no settings"
                ),
            )
            if current:
                saved_interval = float(current.get("order_interval_seconds") or 60)
                saved_speed = float(current.get("simulation_speed") or 1)

            expect(
                check,
                client,
                "POST /simulation/settings (fast interval)",
                "POST",
                "/simulation/settings",
                json_body={"order_interval_seconds": 2, "simulation_speed": 1},
                extra=lambda j, r: (
                    "FAIL: interval not updated"
                    if not j or float(j.get("order_interval_seconds", 99)) > 2.01
                    else f"interval={j.get('order_interval_seconds')}s"
                ),
            )
            spawn = expect(
                check,
                client,
                "POST /simulation/spawn-orders",
                "POST",
                "/simulation/spawn-orders",
                json_body={"count": 6},
                extra=lambda j, r: (
                    "FAIL: did not create enough orders"
                    if not j or int(j.get("created") or 0) < 2
                    else f"created={j.get('created')} fixed={j.get('fixed_rate')} open_bid={j.get('open_bid')}"
                ),
            )
            if spawn:
                print(
                    f"  seeded orders: {spawn.get('external_ids', [])[:6]}"
                )

            # --- Terminals ---
            print("\n--- Terminals ---")
            terminals = expect(
                check, client, "GET /terminals", "GET", "/terminals",
                extra=lambda j, r: (
                    "FAIL: empty terminal list" if len(as_list(j)) < 1 else f"count={len(as_list(j))}"
                ),
            )
            sample_code = "ATL"
            tlist = as_list(terminals)
            if tlist and tlist[0].get("code"):
                sample_code = str(tlist[0]["code"])

            expect(
                check, client, "GET /terminals/{code}", "GET", f"/terminals/{sample_code}",
                extra=lambda j, r: (
                    "FAIL: code mismatch"
                    if not j or str(j.get("code")) != sample_code
                    else f"code={j.get('code')} city={j.get('city')}"
                ),
            )
            expect(
                check, client, "GET /terminals/{bad}", "GET", "/terminals/ZZZ",
                expected={404},
            )

            # --- Fleet ---
            print("\n--- Fleet ---")
            expect(
                check, client, "GET /fleet/availability", "GET", "/fleet/availability",
                extra=lambda j, r: (
                    "FAIL: empty"
                    if len(as_list(j)) < 1
                    else f"terminals={len(as_list(j))} first_available={as_list(j)[0].get('available_units')}"
                ),
            )
            expect(
                check,
                client,
                "GET /fleet/availability?terminal_code=",
                "GET",
                f"/fleet/availability?terminal_code={sample_code}",
                extra=lambda j, r: (
                    "FAIL: expected 1 row"
                    if len(as_list(j)) != 1
                    else f"available_units={as_list(j)[0].get('available_units')}"
                ),
            )
            expect(
                check, client, "GET /fleet/units", "GET", "/fleet/units",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )
            expect(
                check,
                client,
                "GET /fleet/units?terminal_code=&status=available",
                "GET",
                f"/fleet/units?terminal_code={sample_code}&status=available",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )
            expect(
                check, client, "GET /fleet/drivers", "GET", "/fleet/drivers",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )
            expect(
                check, client, "GET /fleet/snapshot", "GET", "/fleet/snapshot",
                extra=lambda j, r: (
                    "FAIL: empty snapshot"
                    if len(as_list(j)) < 1
                    else f"terminals={len(as_list(j))}"
                ),
            )

            # --- History ---
            print("\n--- History ---")
            expect(
                check, client, "GET /history/shipments", "GET", "/history/shipments?limit=5",
                extra=lambda j, r: (
                    "FAIL: no shipments" if len(as_list(j)) < 1 else f"count={len(as_list(j))}"
                ),
            )
            expect(
                check, client, "GET /history/lanes", "GET", "/history/lanes",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )
            if PRINT_BODY:
                print("  → GET /history/shipments.csv")
            csv_resp = client.get("/history/shipments.csv")
            csv_ok = csv_resp.status_code == 200 and "lane_id" in csv_resp.text
            print_response("GET /history/shipments.csv", csv_resp.text, status=csv_resp.status_code)
            if csv_ok:
                check.ok("GET /history/shipments.csv", f"HTTP 200; bytes={len(csv_resp.content)}")
            else:
                check.fail(
                    "GET /history/shipments.csv",
                    f"HTTP {csv_resp.status_code}; missing lane_id header?",
                )

            # --- Simulation ---
            print("\n--- Simulation clock ---")
            expect(
                check, client, "GET /simulation/clock", "GET", "/simulation/clock",
                extra=lambda j, r: (
                    "FAIL: missing simulation_speed"
                    if not j or j.get("simulation_speed") is None
                    else f"speed={j.get('simulation_speed')}"
                ),
            )
            expect(
                check,
                client,
                "POST /simulation/clock (speed=60)",
                "POST",
                "/simulation/clock",
                json_body={"simulation_speed": 60},
                extra=lambda j, r: (
                    "FAIL: speed not 60"
                    if not j or float(j.get("simulation_speed", 0)) != 60
                    else f"speed={j.get('simulation_speed')}"
                ),
            )
            expect(
                check,
                client,
                "POST /simulation/clock (restore speed=1)",
                "POST",
                "/simulation/clock",
                json_body={"simulation_speed": 1},
                extra=lambda j, r: (
                    "FAIL: speed not 1"
                    if not j or float(j.get("simulation_speed", 0)) != 1
                    else f"speed={j.get('simulation_speed')}"
                ),
            )

            # --- Orders read ---
            print("\n--- Orders (read) ---")
            expect(
                check, client, "GET /orders", "GET", "/orders?status=all",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )
            expect(
                check, client, "GET /orders?status=open", "GET", "/orders?status=open",
                extra=lambda j, r: f"count={len(as_list(j))}",
            )

            # --- Orders write ---
            print("\n--- Orders (accept / decline / bid) ---")
            print("Using spawned/turbo board inventory...")
            try:
                fixed = None
                to_decline = None
                open_bid = None
                deadline = time.time() + 30
                def _legal(o: dict) -> bool:
                    # Prefer bookable weights so smoke doesn't trip the board max
                    w = o.get("weight_lbs")
                    return w is None or int(w) <= 44_000

                while time.time() < deadline and not (fixed and to_decline and open_bid):
                    opens = as_list(client.get("/orders", params={"status": "open"}).json())
                    if fixed is None:
                        fixed = next(
                            (
                                o
                                for o in opens
                                if o.get("order_type") == "fixed_rate" and _legal(o)
                            ),
                            None,
                        )
                    if open_bid is None:
                        open_bid = next(
                            (
                                o
                                for o in opens
                                if o.get("order_type") == "open_bid" and _legal(o)
                            ),
                            None,
                        )
                    if to_decline is None:
                        chosen = {
                            str(fixed["external_id"]) if fixed else "",
                            str(open_bid["external_id"]) if open_bid else "",
                        }
                        to_decline = next(
                            (
                                o
                                for o in opens
                                if str(o.get("external_id")) not in chosen and _legal(o)
                            ),
                            None,
                        )
                        if to_decline is None and len(opens) >= 2 and fixed is not None:
                            to_decline = next(
                                (
                                    o
                                    for o in opens
                                    if str(o.get("external_id")) != str(fixed["external_id"])
                                    and _legal(o)
                                ),
                                None,
                            )
                    if not (fixed and to_decline and open_bid):
                        # Spawn another burst if board is thin
                        client.post("/simulation/spawn-orders", json={"count": 4})
                        time.sleep(0.5)

                if not (fixed and to_decline and open_bid):
                    raise TimeoutError(
                        "Could not collect 3 open orders even after spawn-orders"
                    )

                fixed_id = str(fixed["external_id"])
                decline_id = str(to_decline["external_id"])
                bid_id = str(open_bid["external_id"])
                # If decline and bid collided on same id, wait for a distinct open_bid
                if decline_id == bid_id:
                    open_bid = wait_for_order(
                        client, order_type="open_bid", timeout=200, exclude={fixed_id, decline_id}
                    )
                    bid_id = str(open_bid["external_id"])

                print(f"  accept id : {fixed_id}")
                print(f"  decline id: {decline_id}")
                print(f"  bid id    : {bid_id}")

                expect(
                    check, client, "GET /orders/{external_id}", "GET", f"/orders/{fixed_id}",
                    extra=lambda j, r: (
                        "FAIL: id mismatch"
                        if not j or str(j.get("external_id")) != fixed_id
                        else f"id={j.get('external_id')} type={j.get('order_type')}"
                    ),
                )
                expect(
                    check,
                    client,
                    "POST /orders/{id}/accept",
                    "POST",
                    f"/orders/{fixed_id}/accept",
                    json_body={},
                    extra=lambda j, r: (
                        "FAIL: not accepted"
                        if not j or not j.get("ok") or (j.get("order") or {}).get("status") != "accepted"
                        else "status=accepted unit locked"
                    ),
                )
                expect(
                    check,
                    client,
                    "POST /orders/{id}/accept (already accepted -> 409)",
                    "POST",
                    f"/orders/{fixed_id}/accept",
                    json_body={},
                    expected={409},
                )
                expect(
                    check,
                    client,
                    "POST /orders/{id}/decline",
                    "POST",
                    f"/orders/{decline_id}/decline",
                    json_body={},
                    extra=lambda j, r: (
                        "FAIL: not declined"
                        if not j or (j.get("order") or {}).get("status") != "declined"
                        else "status=declined"
                    ),
                )

                bid_rate = round(float(open_bid.get("distance_miles") or 500) * 2.5, 2)
                print(f"  bidding {bid_rate} on {bid_id}")
                expect(
                    check,
                    client,
                    "POST /orders/{id}/bid",
                    "POST",
                    f"/orders/{bid_id}/bid",
                    json_body={"bid_rate": bid_rate},
                    extra=lambda j, r: (
                        "FAIL: not bid_submitted"
                        if not j or (j.get("order") or {}).get("status") != "bid_submitted"
                        else "status=bid_submitted"
                    ),
                )
                expect(
                    check,
                    client,
                    "POST accept on open_bid -> 400/409",
                    "POST",
                    f"/orders/{bid_id}/accept",
                    json_body={},
                    expected={400, 409},
                )

                client.post("/simulation/clock", json={"simulation_speed": 3600})
                final = None
                for _ in range(40):
                    time.sleep(0.5)
                    client.get("/orders", params={"status": "all"})
                    final = client.get(f"/orders/{bid_id}").json()
                    if final.get("status") in {"accepted", "bid_lost"}:
                        break
                client.post("/simulation/clock", json={"simulation_speed": 1})
                print_response("GET /orders/{bid_id} (after shipper decision)", final)
                if final and final.get("status") in {"accepted", "bid_lost"}:
                    check.ok("Bid shipper decision (accepted|bid_lost)", f"status={final.get('status')}")
                else:
                    check.fail(
                        "Bid shipper decision (accepted|bid_lost)",
                        f"status={final.get('status') if final else 'unknown'}",
                    )
            except TimeoutError as exc:
                check.fail("Order action flow", str(exc))

            # --- WebSocket ---
            print("\n--- WebSocket /orders/ws ---")
            ws_url = args.base_url.replace("https://", "wss://").replace("http://", "ws://") + "/orders/ws"
            if websockets is None:
                check.fail("WS /orders/ws", "websockets package missing (pip install websockets)")
            else:
                try:
                    import asyncio

                    async def _ws() -> str:
                        async with websockets.connect(ws_url, open_timeout=10) as ws:
                            msg = await asyncio.wait_for(ws.recv(), timeout=10)
                            return msg if isinstance(msg, str) else msg.decode("utf-8", errors="replace")

                    text = asyncio.run(_ws())
                    try:
                        ws_payload = json.loads(text)
                    except json.JSONDecodeError:
                        ws_payload = text
                    print_response("WS /orders/ws first message", ws_payload)
                    if "snapshot" in text or "order" in text:
                        check.ok("WS /orders/ws", f"received {len(text)} chars")
                    else:
                        check.fail("WS /orders/ws", f"unexpected payload: {text[:120]}")
                except Exception as exc:
                    check.fail("WS /orders/ws", str(exc))

    except httpx.ConnectError:
        print(
            f"Could not connect to {args.base_url}\n"
            "Start the API first:\n"
            "  uvicorn app.main:app --host 127.0.0.1 --port 8000",
            file=sys.stderr,
        )
        return 2
    finally:
        # Always try to restore normal demo pacing after the smoke test
        try:
            with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
                client.post(
                    "/simulation/settings",
                    json={
                        "order_interval_seconds": saved_interval,
                        "simulation_speed": saved_speed,
                    },
                )
                print(
                    f"\nRestored simulation settings: interval={saved_interval}s speed={saved_speed}"
                )
        except Exception:
            pass

    print()
    print("========================================")
    print(f"SUMMARY: {check.passed} passed, {check.failed} failed")
    print("========================================")
    if check.failed:
        print("Failed checks:")
        for item in check.failures:
            print(f"  - {item}")
        return 1
    print("All endpoint checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
