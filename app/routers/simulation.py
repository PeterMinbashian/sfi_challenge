from fastapi import APIRouter

from app.schemas import SimulationClockOut, SimulationSpeedRequest
from app.services.clock import clock

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/clock", response_model=SimulationClockOut)
def get_clock() -> SimulationClockOut:
    return SimulationClockOut(**clock.snapshot())


@router.post("/clock", response_model=SimulationClockOut)
def set_speed(body: SimulationSpeedRequest) -> SimulationClockOut:
    """Change acceleration. Resets the sim epoch so 'now' stays continuous enough for demos."""
    clock.reset(speed=body.simulation_speed)
    return SimulationClockOut(**clock.snapshot())
