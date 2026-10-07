from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.history_data import HISTORY_CSV, ensure_history_csv
from app.models import HistoricalShipment
from app.schemas import HistoricalShipmentOut

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/shipments", response_model=list[HistoricalShipmentOut])
def list_historical_shipments(
    lane_id: str | None = Query(None, description="e.g. ATL-CHI"),
    won: bool | None = Query(None),
    order_type: str | None = Query(None, description="fixed_rate|open_bid"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[HistoricalShipment]:
    q = db.query(HistoricalShipment)
    if lane_id:
        q = q.filter(HistoricalShipment.lane_id == lane_id.upper())
    if won is not None:
        q = q.filter(HistoricalShipment.won == won)
    if order_type:
        q = q.filter(HistoricalShipment.order_type == order_type)
    return (
        q.order_by(HistoricalShipment.shipped_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/shipments.csv")
def download_history_csv(db: Session = Depends(get_db)) -> FileResponse:
    """
    Full historical dataset as CSV (same rows as the DB, plus ML helper columns).

    Also available on disk at `data/historical_shipments.csv` after first seed.
    """
    path = ensure_history_csv(db)
    return FileResponse(
        path,
        media_type="text/csv",
        filename="historical_shipments.csv",
    )


@router.get("/lanes")
def lane_summary(db: Session = Depends(get_db)) -> list[dict]:
    """Aggregate win-rate and average payout by lane — useful for ML baselines."""
    rows = db.query(HistoricalShipment).all()
    buckets: dict[str, dict] = {}
    for row in rows:
        b = buckets.setdefault(
            row.lane_id,
            {
                "lane_id": row.lane_id,
                "shipments": 0,
                "wins": 0,
                "avg_offered_rate": 0.0,
                "avg_distance_miles": 0.0,
                "_offered_sum": 0.0,
                "_miles_sum": 0.0,
            },
        )
        b["shipments"] += 1
        b["wins"] += int(row.won)
        b["_offered_sum"] += row.offered_rate
        b["_miles_sum"] += row.distance_miles

    out = []
    for b in buckets.values():
        n = b["shipments"] or 1
        out.append(
            {
                "lane_id": b["lane_id"],
                "shipments": b["shipments"],
                "wins": b["wins"],
                "win_rate": round(b["wins"] / n, 3),
                "avg_offered_rate": round(b["_offered_sum"] / n, 2),
                "avg_distance_miles": round(b["_miles_sum"] / n, 1),
            }
        )
    out.sort(key=lambda x: x["shipments"], reverse=True)
    return out
