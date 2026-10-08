"""Seed terminals, fleet units, and historical shipments."""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.config import settings
from app.history_data import ensure_history_csv, haversine_miles, jitter, seed_history
from app.models import Driver, HistoricalShipment, Terminal

# Regional hubs students treat as home yards / capacity centers.
TERMINAL_DEFS = [
    {"code": "ATL", "name": "Atlanta Terminal", "city": "Atlanta", "state": "GA", "latitude": 33.6407, "longitude": -84.4277},
    {"code": "JAX", "name": "Jacksonville Terminal", "city": "Jacksonville", "state": "FL", "latitude": 30.4941, "longitude": -81.6879},
    {"code": "DFW", "name": "Dallas–Fort Worth Terminal", "city": "Dallas", "state": "TX", "latitude": 32.8998, "longitude": -97.0403},
    {"code": "CHI", "name": "Chicago Terminal", "city": "Chicago", "state": "IL", "latitude": 41.9742, "longitude": -87.9073},
    {"code": "CMH", "name": "Columbus Terminal", "city": "Columbus", "state": "OH", "latitude": 39.9980, "longitude": -82.8919},
    {"code": "PHL", "name": "Philadelphia Terminal", "city": "Philadelphia", "state": "PA", "latitude": 39.8729, "longitude": -75.2437},
    {"code": "EWR", "name": "Newark Terminal", "city": "Newark", "state": "NJ", "latitude": 40.6895, "longitude": -74.1745},
    {"code": "DEN", "name": "Denver Terminal", "city": "Denver", "state": "CO", "latitude": 39.8561, "longitude": -104.6737},
    {"code": "LAX", "name": "Los Angeles Terminal", "city": "Los Angeles", "state": "CA", "latitude": 33.9416, "longitude": -118.4085},
    {"code": "SEA", "name": "Seattle Terminal", "city": "Seattle", "state": "WA", "latitude": 47.4502, "longitude": -122.3088},
]

FIRST_NAMES = [
    "Jordan", "Alex", "Casey", "Morgan", "Riley", "Taylor", "Jamie", "Avery",
    "Quinn", "Drew", "Cameron", "Reese", "Parker", "Skyler", "Hayden",
]
LAST_NAMES = [
    "Nguyen", "Patel", "Garcia", "Johnson", "Kim", "Brown", "Martinez", "Lee",
    "Wilson", "Anderson", "Thomas", "Jackson", "White", "Harris", "Clark",
]
__all__ = [
    "TERMINAL_DEFS",
    "haversine_miles",
    "jitter",
    "seed_if_empty",
]


def _backfill_history_costs(db: Session) -> None:
    """Fill cost columns on older DB rows that predate estimated_cost."""
    from app.history_data import estimate_operating_cost

    missing = (
        db.query(HistoricalShipment)
        .filter(
            (HistoricalShipment.estimated_cost.is_(None))
            | (HistoricalShipment.cost_per_mile.is_(None))
        )
        .all()
    )
    if not missing:
        return
    for i, row in enumerate(missing, start=1):
        cpm, total = estimate_operating_cost(row.distance_miles, rng=random.Random(10_000 + i))
        row.cost_per_mile = cpm
        row.estimated_cost = total
        if row.won and row.margin_estimate is None:
            payout = row.bid_rate if row.order_type == "open_bid" and row.bid_rate else row.offered_rate
            if payout is not None:
                row.margin_estimate = round(payout - total, 2)
    db.commit()


def seed_if_empty(db: Session) -> None:
    if db.query(Terminal).count() > 0:
        if db.query(HistoricalShipment).count() > 0:
            _backfill_history_costs(db)
            ensure_history_csv(db)
        return

    rng = random.Random(42)
    terminals: list[Terminal] = []
    for defn in TERMINAL_DEFS:
        t = Terminal(**defn, unit_capacity=settings.units_per_terminal)
        db.add(t)
        terminals.append(t)
    db.flush()

    # One unit = driver + truck. No separate truck/trailer inventory.
    for t in terminals:
        for i in range(1, settings.units_per_terminal + 1):
            lat, lon = jitter(t.latitude, t.longitude, miles=rng.uniform(1, 12), rng=rng)
            status = "available" if i < settings.units_per_terminal else "maintenance"
            db.add(
                Driver(
                    employee_code=f"{t.code}-D{i:03d}",
                    unit_number=f"{t.code}-U{i:03d}",
                    first_name=rng.choice(FIRST_NAMES),
                    last_name=rng.choice(LAST_NAMES),
                    home_terminal_id=t.id,
                    status=status,
                    current_latitude=lat,
                    current_longitude=lon,
                    available_at=None,
                )
            )

    db.commit()
    seed_history(db, terminals)
