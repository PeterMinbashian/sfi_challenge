from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Freight Challenge API"
    database_url: str = f"sqlite:///{BASE_DIR / 'freight_challenge.db'}"
    # How often the simulator emits a new live order (seconds, wall clock)
    # Default: one new offer per minute (~5 orders within 5 minutes)
    order_interval_seconds: float = 60.0
    # How long an open order stays bookable (sim minutes; = wall minutes at speed 1)
    order_ttl_sim_minutes: int = 10
    # Sim time multiplier: 1 = real time; 60 ≈ 1 sim hour per real minute
    simulation_speed: float = 1.0
    # Seed fleet size: one "unit" = driver + truck combined
    units_per_terminal: int = 8
    history_rows: int = 2500
    # Chance an open bid is awarded after review delay
    bid_win_probability: float = 0.45
    # Simulated minutes before a submitted bid is won/lost
    bid_decision_sim_minutes: int = 3
    # Board rejects accept/bid when weight_lbs exceeds this (legal / equipment cap)
    max_weight_lbs: int = 44_000


settings = Settings()
