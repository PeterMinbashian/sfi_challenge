"""Assign / release fleet units (driver + truck as one) by terminal time windows."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Driver, LiveOrder, Terminal
from app.services.clock import clock


@dataclass
class Assignment:
    unit: Driver
    terminal: Terminal


def _origin_terminal(db: Session, order: LiveOrder) -> Terminal | None:
    if order.origin_terminal_code:
        return (
            db.query(Terminal)
            .filter(Terminal.code == order.origin_terminal_code.upper())
            .first()
        )
    terminals = db.query(Terminal).all()
    if not terminals:
        return None
    return min(
        terminals,
        key=lambda t: (t.latitude - order.origin_latitude) ** 2
        + (t.longitude - order.origin_longitude) ** 2,
    )


def is_unit_free(unit: Driver, busy_from: datetime) -> bool:
    """A unit is free if idle, or its current load ends before the next pickup."""
    if unit.status in ("maintenance", "off_duty"):
        return False
    if unit.status == "available":
        return True
    return unit.available_at is not None and unit.available_at <= busy_from


def units_at_terminal(db: Session, terminal: Terminal) -> list[Driver]:
    return (
        db.query(Driver)
        .filter(Driver.home_terminal_id == terminal.id)
        .order_by(Driver.employee_code)
        .all()
    )


def available_units(
    db: Session,
    terminal: Terminal,
    as_of: datetime | None = None,
    equipment_type: str | None = None,
) -> list[Driver]:
    as_of = as_of or clock.now()
    units = units_at_terminal(db, terminal)
    free = [u for u in units if is_unit_free(u, as_of)]
    if equipment_type:
        matched = [u for u in free if u.equipment_type == equipment_type]
        return matched or free  # fall back to any equipment if exact match unavailable
    return free


def terminal_availability(
    db: Session,
    as_of: datetime | None = None,
) -> list[dict]:
    """Per-terminal unit counts for dashboards / student capacity checks."""
    as_of = as_of or clock.now()
    out = []
    for terminal in db.query(Terminal).order_by(Terminal.code).all():
        units = units_at_terminal(db, terminal)
        free = [u for u in units if is_unit_free(u, as_of)]
        assigned = [u for u in units if u.status == "assigned" and not is_unit_free(u, as_of)]
        out.append(
            {
                "terminal_code": terminal.code,
                "terminal_name": terminal.name,
                "city": terminal.city,
                "state": terminal.state,
                "total_units": len(units),
                "available_units": len(free),
                "assigned_units": len(assigned),
                "as_of_sim_time": as_of.isoformat() + "Z",
            }
        )
    return out


def find_assignment(db: Session, order: LiveOrder) -> Assignment:
    terminal = _origin_terminal(db, order)
    if not terminal:
        raise HTTPException(status_code=409, detail="No terminal available for origin")

    free = available_units(
        db,
        terminal,
        as_of=order.pickup_at,
        equipment_type=order.equipment_type,
    )
    if not free:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No available fleet units at {terminal.code} "
                f"for pickup window starting {order.pickup_at.isoformat()}"
            ),
        )
    return Assignment(unit=free[0], terminal=terminal)


def lock_assignment(assignment: Assignment, order: LiveOrder) -> None:
    unit = assignment.unit
    unit.status = "assigned"
    unit.available_at = order.delivery_at
    order.assigned_driver_id = unit.id
    order.assigned_truck_id = None
    order.assigned_trailer_id = None
    order.assigned_terminal_code = assignment.terminal.code


def book_order(db: Session, order: LiveOrder) -> Assignment:
    """Capacity check + lock one fleet unit. Caller sets status and commits."""
    assignment = find_assignment(db, order)
    lock_assignment(assignment, order)
    return assignment


def advance_order_lifecycle(db: Session) -> dict:
    now = clock.now()
    stats = {"expired": 0, "bids_won": 0, "bids_lost": 0, "in_transit": 0, "completed": 0}

    for order in (
        db.query(LiveOrder)
        .filter(LiveOrder.status == "open", LiveOrder.expires_at <= now)
        .all()
    ):
        order.status = "expired"
        stats["expired"] += 1

    pending_bids = (
        db.query(LiveOrder)
        .filter(
            LiveOrder.status == "bid_submitted",
            LiveOrder.bid_decision_at.isnot(None),
            LiveOrder.bid_decision_at <= now,
        )
        .all()
    )
    for order in pending_bids:
        if random.random() < settings.bid_win_probability:
            try:
                book_order(db, order)
            except HTTPException:
                order.status = "bid_lost"
                stats["bids_lost"] += 1
                continue
            order.status = "accepted"
            stats["bids_won"] += 1
        else:
            order.status = "bid_lost"
            stats["bids_lost"] += 1

    for order in (
        db.query(LiveOrder)
        .filter(LiveOrder.status == "accepted", LiveOrder.pickup_at <= now)
        .all()
    ):
        if order.delivery_at <= now:
            order.status = "completed"
            stats["completed"] += 1
            _release_unit(db, order)
        else:
            order.status = "in_transit"
            stats["in_transit"] += 1

    db.flush()
    for order in (
        db.query(LiveOrder)
        .filter(LiveOrder.status == "in_transit", LiveOrder.delivery_at <= now)
        .all()
    ):
        order.status = "completed"
        stats["completed"] += 1
        _release_unit(db, order)

    if any(stats.values()):
        db.commit()
    return stats


def _release_unit(db: Session, order: LiveOrder) -> None:
    if not order.assigned_driver_id:
        return
    unit = db.get(Driver, order.assigned_driver_id)
    if not unit:
        return
    unit.status = "available"
    unit.available_at = None
    unit.current_latitude = order.destination_latitude
    unit.current_longitude = order.destination_longitude
    if order.destination_terminal_code:
        dest = (
            db.query(Terminal)
            .filter(Terminal.code == order.destination_terminal_code)
            .first()
        )
        if dest:
            unit.home_terminal_id = dest.id
