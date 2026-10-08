from fastapi import APIRouter

from app.config import settings
from app.database import SessionLocal
from app.schemas import (
    SimulationClockOut,
    SimulationSettingsOut,
    SimulationSettingsRequest,
    SimulationSpeedRequest,
    SpawnOrdersOut,
    SpawnOrdersRequest,
)
from app.services.clock import clock
from app.services.order_simulator import create_simulated_order

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _settings_out() -> SimulationSettingsOut:
    return SimulationSettingsOut(
        simulation_speed=clock.speed,
        order_interval_seconds=settings.order_interval_seconds,
        order_ttl_sim_minutes=settings.order_ttl_sim_minutes,
        bid_decision_sim_minutes=settings.bid_decision_sim_minutes,
        note=(
            "order_interval_seconds is wall-clock time between new offers; "
            "simulation_speed only accelerates pickup/delivery/bid timers."
        ),
    )


@router.get("/clock", response_model=SimulationClockOut)
def get_clock() -> SimulationClockOut:
    return SimulationClockOut(**clock.snapshot())


@router.post("/clock", response_model=SimulationClockOut)
def set_speed(body: SimulationSpeedRequest) -> SimulationClockOut:
    """Change acceleration. Resets the sim epoch so 'now' stays continuous enough for demos."""
    clock.reset(speed=body.simulation_speed)
    return SimulationClockOut(**clock.snapshot())


@router.get("/settings", response_model=SimulationSettingsOut)
def get_settings() -> SimulationSettingsOut:
    return _settings_out()


@router.post("/settings", response_model=SimulationSettingsOut)
def update_settings(body: SimulationSettingsRequest) -> SimulationSettingsOut:
    """
    Runtime tuning for demos / smoke tests.

    - `order_interval_seconds`: how often new loads appear (wall clock)
    - `simulation_speed`: how fast pickup/delivery/bid timers advance
    """
    if body.simulation_speed is not None:
        clock.reset(speed=body.simulation_speed)
    if body.order_interval_seconds is not None:
        settings.order_interval_seconds = float(body.order_interval_seconds)
    return _settings_out()


@router.post("/spawn-orders", response_model=SpawnOrdersOut)
def spawn_orders(body: SpawnOrdersRequest | None = None) -> SpawnOrdersOut:
    """
    Immediately create open orders (does not wait for the background interval).
    Useful for smoke tests so accept/decline/bid do not wait minutes.
    Guarantees at least one fixed_rate and one open_bid when count >= 2.
    """
    req = body or SpawnOrdersRequest()
    created_ids: list[str] = []
    fixed = 0
    open_bid = 0
    db = SessionLocal()
    try:
        for i in range(req.count):
            if req.count >= 2 and i == 0:
                forced = "fixed_rate"
            elif req.count >= 2 and i == 1:
                forced = "open_bid"
            else:
                forced = None
            order = create_simulated_order(db, order_type=forced)
            created_ids.append(order.external_id)
            if order.order_type == "fixed_rate":
                fixed += 1
            else:
                open_bid += 1
    finally:
        db.close()
    return SpawnOrdersOut(
        created=len(created_ids),
        fixed_rate=fixed,
        open_bid=open_bid,
        external_ids=created_ids,
    )
