"""
Realistic historical shipment generation + CSV sync.

Data lives in SQLite (`historical_shipments`) and is also written to:
  data/historical_shipments.csv

If the CSV already exists and the DB is empty, the CSV is loaded into the DB
so instructors can swap in alternate datasets.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.models import HistoricalShipment, Terminal

DATA_DIR = BASE_DIR / "data"
HISTORY_CSV = DATA_DIR / "historical_shipments.csv"

CSV_COLUMNS = [
    "shipment_id",
    "lane_id",
    "origin_city",
    "origin_state",
    "origin_latitude",
    "origin_longitude",
    "destination_city",
    "destination_state",
    "destination_latitude",
    "destination_longitude",
    "distance_miles",
    "weight_lbs",
    "equipment_type",
    "order_type",
    "offered_rate",
    "bid_rate",
    "won",
    "margin_estimate",
    "shipped_at",
    # Extra analytics columns (also useful for ML feature engineering)
    "market_rpm",
    "all_in_rpm",
    "fuel_surcharge_rpm",
    "season",
    "booked_lead_hours",
]

# Directional base $/mile by origin region family (latent market, not published live)
_REGION = {
    "GA": "SE", "FL": "SE",
    "TX": "SC",
    "IL": "MW", "OH": "MW",
    "PA": "NE", "NJ": "NE",
    "CO": "MT",
    "CA": "WC", "WA": "WC",
}

# Outbound strength: WC/NE tend to pay more outbound; SE/SC often cheaper outbound
_REGION_OUT_RPM = {
    "SE": 2.35,
    "SC": 2.40,
    "MW": 2.50,
    "NE": 2.70,
    "MT": 2.45,
    "WC": 2.85,
}

_EQUIP_MULT = {"dry_van": 1.0, "reefer": 1.18, "flatbed": 1.12}

# Popular freight corridors get slightly tighter / higher volume (weighted sampling)
_HOT_LANES = {
    ("LAX", "DFW"), ("LAX", "ATL"), ("LAX", "CHI"), ("LAX", "EWR"),
    ("SEA", "CHI"), ("SEA", "DEN"),
    ("ATL", "EWR"), ("ATL", "PHL"), ("ATL", "CHI"), ("ATL", "DFW"),
    ("DFW", "CHI"), ("DFW", "ATL"), ("DFW", "LAX"),
    ("CHI", "EWR"), ("CHI", "ATL"), ("CHI", "DEN"),
    ("EWR", "ATL"), ("EWR", "CHI"), ("PHL", "ATL"), ("CMH", "EWR"),
    ("JAX", "EWR"), ("JAX", "PHL"), ("DEN", "CHI"), ("DEN", "LAX"),
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def jitter(lat: float, lon: float, miles: float, rng: random.Random) -> tuple[float, float]:
    bearing = rng.uniform(0, 2 * math.pi)
    dlat = (miles * math.cos(bearing)) / 69.0
    dlon = (miles * math.sin(bearing)) / (69.0 * max(0.2, math.cos(math.radians(lat))))
    return round(lat + dlat, 5), round(lon + dlon, 5)


def _season(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


def _seasonal_mult(season: str, equipment: str) -> float:
    # Produce / construction / holiday freight patterns
    table = {
        ("summer", "reefer"): 1.14,
        ("fall", "dry_van"): 1.08,
        ("winter", "dry_van"): 1.05,
        ("winter", "reefer"): 0.97,
        ("spring", "flatbed"): 1.10,
        ("summer", "flatbed"): 1.06,
    }
    return table.get((season, equipment), 1.0)


def _fuel_rpm(shipped_at: datetime, rng: random.Random) -> float:
    # Crude seasonal diesel proxy in $/mile contribution
    month = shipped_at.month
    base = 0.42 + 0.06 * math.sin((month - 1) / 12 * 2 * math.pi)
    return round(base + rng.uniform(-0.04, 0.04), 3)


def _weight_for_equipment(equipment: str, rng: random.Random) -> int:
    if equipment == "reefer":
        # Often denser / partials less common
        return int(rng.gauss(36_000, 4_500))
    if equipment == "flatbed":
        return int(rng.gauss(32_000, 8_000))
    # dry van — many 40-43k truckload, some LTL-ish partials
    if rng.random() < 0.18:
        return int(rng.uniform(10_000, 28_000))
    return int(rng.gauss(40_000, 3_200))


def _clamp_weight(w: int) -> int:
    return max(5_000, min(45_000, w))


def _pick_terminals(terminals: list[Terminal], rng: random.Random) -> tuple[Terminal, Terminal]:
    by_code = {t.code: t for t in terminals}
    if rng.random() < 0.55 and _HOT_LANES:
        o_code, d_code = rng.choice(list(_HOT_LANES))
        if o_code in by_code and d_code in by_code:
            return by_code[o_code], by_code[d_code]
    origin, dest = rng.sample(terminals, 2)
    return origin, dest


def _market_rpm(
    origin: Terminal,
    dest: Terminal,
    miles: float,
    equipment: str,
    shipped_at: datetime,
    rng: random.Random,
) -> float:
    o_reg = _REGION.get(origin.state, "MW")
    d_reg = _REGION.get(dest.state, "MW")
    base = _REGION_OUT_RPM[o_reg]

    # Imbalanced lanes: WC→East expensive; East→WC often cheaper (backhaul pressure)
    if o_reg == "WC" and d_reg in {"SE", "SC", "MW", "NE"}:
        base += 0.35
    if o_reg in {"SE", "SC", "MW", "NE"} and d_reg == "WC":
        base -= 0.25
    if o_reg == "NE" and d_reg == "SE":
        base += 0.10
    if o_reg == "SE" and d_reg == "NE":
        base += 0.15

    # Short haul pays higher RPM; long haul compresses a bit
    if miles < 250:
        base += 0.35
    elif miles < 500:
        base += 0.15
    elif miles > 1800:
        base -= 0.12

    season = _season(shipped_at.month)
    base *= _EQUIP_MULT.get(equipment, 1.0)
    base *= _seasonal_mult(season, equipment)
    base *= rng.uniform(0.93, 1.07)
    return round(max(1.6, base), 3)


def generate_history_records(
    terminals: list[Terminal],
    rng: random.Random | None = None,
    n: int | None = None,
    as_of: datetime | None = None,
) -> list[dict]:
    rng = rng or random.Random(42)
    n = n if n is not None else settings.history_rows
    as_of = as_of or datetime.utcnow()
    rows: list[dict] = []

    for i in range(1, n + 1):
        origin, dest = _pick_terminals(terminals, rng)
        # Most pickups near hub; some plant/DC offsets
        o_miles = rng.uniform(3, 25) if rng.random() < 0.75 else rng.uniform(30, 110)
        d_miles = rng.uniform(3, 25) if rng.random() < 0.75 else rng.uniform(30, 110)
        o_lat, o_lon = jitter(origin.latitude, origin.longitude, o_miles, rng)
        d_lat, d_lon = jitter(dest.latitude, dest.longitude, d_miles, rng)
        miles = haversine_miles(o_lat, o_lon, d_lat, d_lon)
        if miles < 80:
            # Force a more useful TL distance if jitter collapsed oddly
            miles = haversine_miles(origin.latitude, origin.longitude, dest.latitude, dest.longitude)

        equipment = rng.choices(
            ["dry_van", "reefer", "flatbed"],
            weights=[0.62, 0.22, 0.16],
            k=1,
        )[0]
        order_type = "fixed_rate" if rng.random() < 0.58 else "open_bid"

        # Ship dates over ~18 months with weekday bias (fewer weekend bookings)
        day_offset = int(rng.triangular(1, 540, 120))
        shipped_at = as_of - timedelta(days=day_offset, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        if shipped_at.weekday() >= 5 and rng.random() < 0.7:
            shipped_at -= timedelta(days=shipped_at.weekday() - 4)

        season = _season(shipped_at.month)
        market_rpm = _market_rpm(origin, dest, miles, equipment, shipped_at, rng)
        fuel_rpm = _fuel_rpm(shipped_at, rng)
        all_in = round(market_rpm + fuel_rpm * 0.35, 3)

        weight = _clamp_weight(_weight_for_equipment(equipment, rng))
        # Heavier loads nudge rate up slightly
        if weight >= 42_000:
            all_in = round(all_in * 1.03, 3)

        lead_hours = int(rng.choices(
            [6, 12, 18, 24, 36, 48, 72],
            weights=[8, 14, 18, 22, 18, 12, 8],
            k=1,
        )[0])

        if order_type == "fixed_rate":
            # Book-it-now posts near market; occasionally "too cheap" or rich
            post_rpm = all_in * rng.choices(
                [0.90, 0.96, 1.00, 1.04, 1.12],
                weights=[8, 18, 40, 24, 10],
                k=1,
            )[0]
            offered = round(miles * post_rpm, 2)
            bid = None
            # Carriers accept cheap BIN more often
            accept_p = 1 / (1 + math.exp((post_rpm - all_in) / 0.12))
            won = rng.random() < accept_p
            payout = offered if won else None
        else:
            # Open bid: board may show a weak "ask" hint historically; live API keeps null
            offered = round(miles * all_in * rng.uniform(0.92, 1.05), 2)
            # Bid behavior: aggressive / market / rich
            bid_rpm = all_in * rng.choices(
                [0.88, 0.95, 1.00, 1.06, 1.15, 1.25],
                weights=[10, 18, 28, 22, 14, 8],
                k=1,
            )[0]
            bid = round(miles * bid_rpm, 2)
            # Win if bid is competitive vs latent market
            gap = (bid_rpm - all_in) / max(all_in, 0.01)
            win_p = 1 / (1 + math.exp(8 * gap - 0.2))
            won = rng.random() < win_p
            payout = bid if won else None

        # Operating cost ~ fuel + driver + wear; margin only when won
        cost_rpm = fuel_rpm + rng.uniform(1.15, 1.55)
        if equipment == "reefer":
            cost_rpm += 0.18
        if equipment == "flatbed":
            cost_rpm += 0.10
        margin = round((payout - miles * cost_rpm), 2) if (won and payout) else None

        rows.append(
            {
                "shipment_id": f"HS-{i:05d}",
                "lane_id": f"{origin.code}-{dest.code}",
                "origin_city": origin.city,
                "origin_state": origin.state,
                "origin_latitude": o_lat,
                "origin_longitude": o_lon,
                "destination_city": dest.city,
                "destination_state": dest.state,
                "destination_latitude": d_lat,
                "destination_longitude": d_lon,
                "distance_miles": miles,
                "weight_lbs": weight,
                "equipment_type": equipment,
                "order_type": order_type,
                "offered_rate": offered,
                "bid_rate": bid if bid is not None else "",
                "won": won,
                "margin_estimate": margin if margin is not None else "",
                "shipped_at": shipped_at.replace(microsecond=0).isoformat(sep=" "),
                "market_rpm": market_rpm,
                "all_in_rpm": all_in,
                "fuel_surcharge_rpm": fuel_rpm,
                "season": season,
                "booked_lead_hours": lead_hours,
            }
        )
    return rows


def write_history_csv(rows: Iterable[dict], path: Path | None = None) -> Path:
    path = path or HISTORY_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if isinstance(out.get("won"), bool):
                out["won"] = "true" if out["won"] else "false"
            if out.get("bid_rate") in (None,):
                out["bid_rate"] = ""
            if out.get("margin_estimate") in (None,):
                out["margin_estimate"] = ""
            writer.writerow(out)
    return path


def read_history_csv(path: Path | None = None) -> list[dict]:
    path = path or HISTORY_CSV
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def insert_history_rows(db: Session, rows: list[dict]) -> int:
    for row in rows:
        db.add(
            HistoricalShipment(
                lane_id=row["lane_id"],
                origin_city=row["origin_city"],
                origin_state=row["origin_state"],
                origin_latitude=float(row["origin_latitude"]),
                origin_longitude=float(row["origin_longitude"]),
                destination_city=row["destination_city"],
                destination_state=row["destination_state"],
                destination_latitude=float(row["destination_latitude"]),
                destination_longitude=float(row["destination_longitude"]),
                distance_miles=float(row["distance_miles"]),
                weight_lbs=int(float(row["weight_lbs"])),
                equipment_type=row["equipment_type"],
                order_type=row["order_type"],
                offered_rate=float(row["offered_rate"]),
                bid_rate=_parse_optional_float(row.get("bid_rate")),
                won=_parse_bool(row["won"]),
                margin_estimate=_parse_optional_float(row.get("margin_estimate")),
                shipped_at=datetime.fromisoformat(str(row["shipped_at"]).replace("Z", "")),
            )
        )
    db.commit()
    return len(rows)


def export_db_history_csv(db: Session, path: Path | None = None) -> Path:
    """Export DB rows to CSV (analytics columns recomputed lightly where missing)."""
    path = path or HISTORY_CSV
    records = []
    for i, row in enumerate(db.query(HistoricalShipment).order_by(HistoricalShipment.id).all(), start=1):
        all_in = round(row.offered_rate / max(row.distance_miles, 1.0), 3)
        records.append(
            {
                "shipment_id": f"HS-{i:05d}",
                "lane_id": row.lane_id,
                "origin_city": row.origin_city,
                "origin_state": row.origin_state,
                "origin_latitude": row.origin_latitude,
                "origin_longitude": row.origin_longitude,
                "destination_city": row.destination_city,
                "destination_state": row.destination_state,
                "destination_latitude": row.destination_latitude,
                "destination_longitude": row.destination_longitude,
                "distance_miles": row.distance_miles,
                "weight_lbs": row.weight_lbs,
                "equipment_type": row.equipment_type,
                "order_type": row.order_type,
                "offered_rate": row.offered_rate,
                "bid_rate": row.bid_rate if row.bid_rate is not None else "",
                "won": row.won,
                "margin_estimate": row.margin_estimate if row.margin_estimate is not None else "",
                "shipped_at": row.shipped_at.replace(microsecond=0).isoformat(sep=" "),
                "market_rpm": all_in,
                "all_in_rpm": all_in,
                "fuel_surcharge_rpm": "",
                "season": _season(row.shipped_at.month),
                "booked_lead_hours": "",
            }
        )
    return write_history_csv(records, path)


def seed_history(db: Session, terminals: list[Terminal]) -> int:
    """
    Prefer existing CSV if present; otherwise generate realistic rows, write CSV, insert DB.
    """
    if HISTORY_CSV.exists():
        rows = read_history_csv()
        return insert_history_rows(db, rows)

    rows = generate_history_records(terminals)
    write_history_csv(rows)
    return insert_history_rows(db, rows)


def ensure_history_csv(db: Session) -> Path:
    if HISTORY_CSV.exists():
        return HISTORY_CSV
    if db.query(HistoricalShipment).count() == 0:
        raise FileNotFoundError("No historical shipments in DB or CSV")
    return export_db_history_csv(db)
