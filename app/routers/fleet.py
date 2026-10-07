from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Driver, Terminal
from app.schemas import FleetSnapshot, FleetUnitOut, TerminalAvailability
from app.services.clock import clock
from app.services.dispatch import available_units, terminal_availability, units_at_terminal

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.get("/availability", response_model=list[TerminalAvailability])
def fleet_availability(
    terminal_code: str | None = Query(None, description="Optional filter, e.g. ATL"),
    db: Session = Depends(get_db),
) -> list[dict]:
    """
    Simple per-terminal counts of fleet units (driver+truck as one).

    `available_units` is what can take a new load right now (sim time).
    Accepting a load decrements this until delivery completes.
    """
    rows = terminal_availability(db, as_of=clock.now())
    if terminal_code:
        code = terminal_code.upper()
        rows = [r for r in rows if r["terminal_code"] == code]
        if not rows:
            raise HTTPException(status_code=404, detail=f"Terminal {terminal_code} not found")
    return rows


@router.get("/units", response_model=list[FleetUnitOut])
def list_units(
    terminal_code: str | None = Query(None, description="Filter by home terminal code"),
    status: str | None = Query(None, description="available|assigned|off_duty|maintenance"),
    equipment_type: str | None = Query(None, description="dry_van|reefer|flatbed"),
    db: Session = Depends(get_db),
) -> list[Driver]:
    q = db.query(Driver)
    if terminal_code:
        terminal = db.query(Terminal).filter(Terminal.code == terminal_code.upper()).first()
        if not terminal:
            raise HTTPException(status_code=404, detail=f"Terminal {terminal_code} not found")
        q = q.filter(Driver.home_terminal_id == terminal.id)
    if status:
        q = q.filter(Driver.status == status)
    if equipment_type:
        q = q.filter(Driver.equipment_type == equipment_type)
    return q.order_by(Driver.employee_code).all()


@router.get("/drivers", response_model=list[FleetUnitOut])
def list_drivers(
    terminal_code: str | None = Query(None),
    status: str | None = Query(None),
    equipment_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[Driver]:
    """Alias of /fleet/units (driver and truck are one unit)."""
    return list_units(terminal_code=terminal_code, status=status, equipment_type=equipment_type, db=db)


@router.get("/snapshot", response_model=list[FleetSnapshot])
def fleet_snapshot(db: Session = Depends(get_db)) -> list[FleetSnapshot]:
    """Per-terminal utilization + unit roster for dispatcher dashboards."""
    now = clock.now()
    snapshots: list[FleetSnapshot] = []
    for terminal in db.query(Terminal).order_by(Terminal.code).all():
        units = units_at_terminal(db, terminal)
        free = available_units(db, terminal, as_of=now)
        assigned = [u for u in units if u.status == "assigned" and u not in free]
        snapshots.append(
            FleetSnapshot(
                terminal=terminal,
                total_units=len(units),
                available_units=len(free),
                assigned_units=len(assigned),
                units=units,
            )
        )
    return snapshots
