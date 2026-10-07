from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TerminalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    city: str
    state: str
    latitude: float
    longitude: float
    unit_capacity: int


class FleetUnitOut(BaseModel):
    """Driver + truck treated as one bookable unit."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    unit_number: str
    first_name: str
    last_name: str
    home_terminal_id: int
    equipment_type: str
    status: str
    current_latitude: float
    current_longitude: float
    available_at: Optional[datetime] = None


# Backward-friendly alias used in older docs
DriverOut = FleetUnitOut


class TerminalAvailability(BaseModel):
    terminal_code: str
    terminal_name: str
    city: str
    state: str
    total_units: int
    available_units: int
    assigned_units: int
    as_of_sim_time: str


class FleetSnapshot(BaseModel):
    terminal: TerminalOut
    total_units: int
    available_units: int
    assigned_units: int
    units: list[FleetUnitOut]


class HistoricalShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lane_id: str
    origin_city: str
    origin_state: str
    origin_latitude: float
    origin_longitude: float
    destination_city: str
    destination_state: str
    destination_latitude: float
    destination_longitude: float
    distance_miles: float
    weight_lbs: int
    equipment_type: str
    order_type: str
    offered_rate: float
    bid_rate: Optional[float] = None
    won: bool
    margin_estimate: Optional[float] = None
    shipped_at: datetime


class LiveOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    order_type: str
    status: str
    origin_city: str
    origin_state: str
    origin_latitude: float
    origin_longitude: float
    origin_terminal_code: Optional[str] = None
    destination_city: str
    destination_state: str
    destination_latitude: float
    destination_longitude: float
    destination_terminal_code: Optional[str] = None
    distance_miles: float
    weight_lbs: int
    equipment_type: str
    offered_rate: Optional[float] = None
    pickup_at: datetime
    delivery_at: datetime
    expires_at: datetime
    created_at: datetime
    notes: Optional[str] = None
    seconds_remaining: Optional[int] = None
    assigned_driver_id: Optional[int] = None
    assigned_truck_id: Optional[int] = None
    assigned_trailer_id: Optional[int] = None
    assigned_terminal_code: Optional[str] = None
    bid_decision_at: Optional[datetime] = None
    winning_bid_rate: Optional[float] = None


class AcceptRequest(BaseModel):
    carrier_note: Optional[str] = None


class DeclineRequest(BaseModel):
    carrier_note: Optional[str] = None


class BidRequest(BaseModel):
    bid_rate: float = Field(gt=0, description="Proposed total payout in USD")
    carrier_note: Optional[str] = None


class ActionResponse(BaseModel):
    ok: bool
    message: str
    order: LiveOrderOut


class HealthOut(BaseModel):
    status: Literal["ok"]
    app: str
    sim_time_utc: str
    simulation_speed: float


class SimulationClockOut(BaseModel):
    wall_time_utc: str
    sim_time_utc: str
    simulation_speed: float
    note: str


class SimulationSpeedRequest(BaseModel):
    simulation_speed: float = Field(ge=1, le=100_000, description="Sim seconds per wall second")
