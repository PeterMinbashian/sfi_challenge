from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Freight Challenge API"
    database_url: str = f"sqlite:///{BASE_DIR / 'freight_challenge.db'}"
    # How often the simulator emits a new live order (seconds, wall clock)
    order_interval_seconds: float = 8.0
    # How long an open order stays bookable (simulated minutes)
    order_ttl_sim_minutes: int = 45
    # Sim time multiplier: 60 => 1 real minute ≈ 1 simulated hour
    simulation_speed: float = 60.0
    # Seed fleet size: one "unit" = driver + truck combined
    units_per_terminal: int = 8
    history_rows: int = 2500
    # Chance an open bid is awarded after review delay
    bid_win_probability: float = 0.45
    # Simulated minutes before a submitted bid is won/lost
    bid_decision_sim_minutes: int = 15


settings = Settings()
