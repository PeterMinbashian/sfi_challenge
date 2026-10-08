from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Terminal(Base):
    __tablename__ = "terminals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(2))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # Fleet is modeled as N driver+truck "units" per terminal (not separate assets)
    unit_capacity: Mapped[int] = mapped_column(Integer, default=0)

    units: Mapped[list[Driver]] = relationship(back_populates="home_terminal")


class Driver(Base):
    """
    One fleet unit = driver + truck together (challenge simplification).
    Booking locks this single record until delivery_at.
    """

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    unit_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    home_terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="available")  # available|assigned|off_duty|maintenance
    current_latitude: Mapped[float] = mapped_column(Float)
    current_longitude: Mapped[float] = mapped_column(Float)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    home_terminal: Mapped[Terminal] = relationship(back_populates="units")


class HistoricalShipment(Base):
    __tablename__ = "historical_shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lane_id: Mapped[str] = mapped_column(String(40), index=True)
    origin_city: Mapped[str] = mapped_column(String(80))
    origin_state: Mapped[str] = mapped_column(String(2))
    origin_latitude: Mapped[float] = mapped_column(Float)
    origin_longitude: Mapped[float] = mapped_column(Float)
    destination_city: Mapped[str] = mapped_column(String(80))
    destination_state: Mapped[str] = mapped_column(String(2))
    destination_latitude: Mapped[float] = mapped_column(Float)
    destination_longitude: Mapped[float] = mapped_column(Float)
    distance_miles: Mapped[float] = mapped_column(Float)
    weight_lbs: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(20))  # fixed_rate|open_bid
    offered_rate: Mapped[float] = mapped_column(Float)
    bid_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    won: Mapped[bool] = mapped_column(Boolean, default=False)
    # Carrier operating cost for the loaded miles (fuel + driver + wear); always present
    cost_per_mile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shipped_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class LiveOrder(Base):
    __tablename__ = "live_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_type: Mapped[str] = mapped_column(String(20))  # fixed_rate|open_bid
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|accepted|bid_submitted|expired|declined
    origin_city: Mapped[str] = mapped_column(String(80))
    origin_state: Mapped[str] = mapped_column(String(2))
    origin_latitude: Mapped[float] = mapped_column(Float)
    origin_longitude: Mapped[float] = mapped_column(Float)
    origin_terminal_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    destination_city: Mapped[str] = mapped_column(String(80))
    destination_state: Mapped[str] = mapped_column(String(2))
    destination_latitude: Mapped[float] = mapped_column(Float)
    destination_longitude: Mapped[float] = mapped_column(Float)
    destination_terminal_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    distance_miles: Mapped[float] = mapped_column(Float)
    weight_lbs: Mapped[int] = mapped_column(Integer)
    offered_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Published so students can compute margin without inventing a cost model
    cost_per_mile: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pickup_at: Mapped[datetime] = mapped_column(DateTime)
    delivery_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Set when booked; capacity frees when status becomes completed
    assigned_driver_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assigned_truck_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assigned_trailer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assigned_terminal_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # For open bids: when the shipper decides win/lose (sim time)
    bid_decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    winning_bid_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class OrderAction(Base):
    """Student accept / bid / decline submissions recorded by the API."""

    __tablename__ = "order_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("live_orders.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # accept|decline|bid
    bid_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    carrier_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
