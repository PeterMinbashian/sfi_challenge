"""Accelerated brokerage clock.

Wall-clock seconds are multiplied by `simulation_speed` so multi-day
pickup/delivery windows play out in minutes during a student demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import settings


class SimulationClock:
    def __init__(self) -> None:
        self._wall_start = datetime.utcnow()
        self._sim_start = self._wall_start
        self.speed = settings.simulation_speed

    def reset(self, speed: float | None = None) -> None:
        if speed is not None:
            self.speed = max(1.0, float(speed))
        self._wall_start = datetime.utcnow()
        self._sim_start = self._wall_start

    def now(self) -> datetime:
        elapsed = datetime.utcnow() - self._wall_start
        return self._sim_start + timedelta(seconds=elapsed.total_seconds() * self.speed)

    def snapshot(self) -> dict:
        wall = datetime.utcnow()
        sim = self.now()
        return {
            "wall_time_utc": wall.isoformat() + "Z",
            "sim_time_utc": sim.isoformat() + "Z",
            "simulation_speed": self.speed,
            "note": (
                f"1 real second ~= {self.speed:g} simulated seconds "
                f"({self.speed / 3600:g} sim hours per real second)"
            ),
        }


clock = SimulationClock()
