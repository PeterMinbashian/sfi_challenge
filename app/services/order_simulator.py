"""Background live-order generator + WebSocket broadcaster."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import timedelta
from typing import Any, Optional

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import LiveOrder, Terminal
from app.schemas import LiveOrderOut
from app.history_data import haversine_miles, jitter
from app.seed import EQUIPMENT
from app.services.clock import clock
from app.services.dispatch import advance_order_lifecycle

log = logging.getLogger("freight.simulator")


class OrderHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


hub = OrderHub()


def order_to_dict(order: LiveOrder, now=None) -> dict[str, Any]:
    now = now or clock.now()
    remaining = max(0, int((order.expires_at - now).total_seconds()))
    data = LiveOrderOut.model_validate(order).model_dump(mode="json")
    data["seconds_remaining"] = remaining
    return data


def expire_stale_orders(db: Session) -> dict:
    """Backward-compatible name used by routers — runs full lifecycle tick."""
    return advance_order_lifecycle(db)


def create_simulated_order(db: Session, rng: Optional[random.Random] = None) -> LiveOrder:
    rng = rng or random.Random()
    terminals = db.query(Terminal).all()
    if len(terminals) < 2:
        raise RuntimeError("Need at least two terminals to simulate orders")

    origin_t, dest_t = rng.sample(terminals, 2)
    near_hub = rng.random() < 0.7
    if near_hub:
        o_lat, o_lon = jitter(origin_t.latitude, origin_t.longitude, miles=rng.uniform(3, 25), rng=rng)
        d_lat, d_lon = jitter(dest_t.latitude, dest_t.longitude, miles=rng.uniform(3, 25), rng=rng)
        o_city, o_state = origin_t.city, origin_t.state
        d_city, d_state = dest_t.city, dest_t.state
        o_code, d_code = origin_t.code, dest_t.code
    else:
        o_lat, o_lon = jitter(origin_t.latitude, origin_t.longitude, miles=rng.uniform(40, 120), rng=rng)
        d_lat, d_lon = jitter(dest_t.latitude, dest_t.longitude, miles=rng.uniform(40, 120), rng=rng)
        o_city, o_state = f"Near {origin_t.city}", origin_t.state
        d_city, d_state = f"Near {dest_t.city}", dest_t.state
        o_code, d_code = None, None

    miles = haversine_miles(o_lat, o_lon, d_lat, d_lon)
    order_type = "fixed_rate" if rng.random() < 0.55 else "open_bid"
    equipment = rng.choice(EQUIPMENT)
    # Fixed-rate posts a Book-It-Now price; open-bid has no offered_rate (manual bid in UI)
    offered = round(miles * rng.uniform(2.0, 3.5), 2) if order_type == "fixed_rate" else None

    now = clock.now()
    # Short enough that sim-speed demos show pickups/deliveries within minutes of wall time
    pickup = now + timedelta(hours=rng.uniform(1, 6))
    transit_hours = max(3.0, miles / rng.uniform(45, 55))
    delivery = pickup + timedelta(hours=transit_hours + rng.uniform(1, 4))
    expires = now + timedelta(minutes=settings.order_ttl_sim_minutes)

    order = LiveOrder(
        external_id=f"LD-{uuid.uuid4().hex[:10].upper()}",
        order_type=order_type,
        status="open",
        origin_city=o_city,
        origin_state=o_state,
        origin_latitude=o_lat,
        origin_longitude=o_lon,
        origin_terminal_code=o_code,
        destination_city=d_city,
        destination_state=d_state,
        destination_latitude=d_lat,
        destination_longitude=d_lon,
        destination_terminal_code=d_code,
        distance_miles=miles,
        weight_lbs=rng.randint(8_000, 44_000),
        equipment_type=equipment,
        offered_rate=offered,
        pickup_at=pickup,
        delivery_at=delivery,
        expires_at=expires,
        created_at=now,
        notes="Simulated customer load opportunity",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


async def simulator_loop(stop_event: asyncio.Event) -> None:
    log.info(
        "Brokerage simulator started (interval=%ss ttl=%s sim-min speed=%sx)",
        settings.order_interval_seconds,
        settings.order_ttl_sim_minutes,
        settings.simulation_speed,
    )
    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                stats = advance_order_lifecycle(db)
                if any(stats.values()):
                    await hub.broadcast({"event": "lifecycle", "stats": stats, "clock": clock.snapshot()})
                order = create_simulated_order(db)
                payload = {
                    "event": "order.created",
                    "order": order_to_dict(order),
                    "clock": clock.snapshot(),
                }
            finally:
                db.close()
            await hub.broadcast(payload)
        except Exception:
            log.exception("Simulator tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.order_interval_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("Order simulator stopped")
