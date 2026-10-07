from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import LiveOrder, OrderAction
from app.schemas import (
    AcceptRequest,
    ActionResponse,
    BidRequest,
    DeclineRequest,
    LiveOrderOut,
)
from app.services.clock import clock
from app.services.dispatch import book_order
from app.services.order_simulator import expire_stale_orders, hub, order_to_dict

router = APIRouter(prefix="/orders", tags=["orders"])


def _enrich(order: LiveOrder) -> LiveOrderOut:
    return LiveOrderOut.model_validate(order_to_dict(order))


@router.get("", response_model=list[LiveOrderOut])
def list_orders(
    status: str | None = Query(
        "open",
        description="open|accepted|in_transit|completed|bid_submitted|bid_lost|expired|declined|all",
    ),
    order_type: str | None = Query(None, description="fixed_rate|open_bid"),
    db: Session = Depends(get_db),
) -> list[LiveOrderOut]:
    expire_stale_orders(db)
    q = db.query(LiveOrder)
    if status and status != "all":
        q = q.filter(LiveOrder.status == status)
    if order_type:
        q = q.filter(LiveOrder.order_type == order_type)
    orders = q.order_by(LiveOrder.created_at.desc()).limit(200).all()
    return [_enrich(o) for o in orders]


@router.get("/{external_id}", response_model=LiveOrderOut)
def get_order(external_id: str, db: Session = Depends(get_db)) -> LiveOrderOut:
    expire_stale_orders(db)
    order = db.query(LiveOrder).filter(LiveOrder.external_id == external_id.upper()).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _enrich(order)


def _require_open(order: LiveOrder | None) -> LiveOrder:
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "open":
        raise HTTPException(status_code=409, detail=f"Order is {order.status}, not open")
    if order.expires_at <= clock.now():
        order.status = "expired"
        raise HTTPException(status_code=409, detail="Order expired")
    return order


@router.post("/{external_id}/accept", response_model=ActionResponse)
def accept_order(
    external_id: str,
    body: AcceptRequest | None = None,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Accept a fixed-rate load: locks driver/truck/trailer until delivery (sim time)."""
    expire_stale_orders(db)
    order = db.query(LiveOrder).filter(LiveOrder.external_id == external_id.upper()).first()
    order = _require_open(order)
    if order.order_type != "fixed_rate":
        raise HTTPException(
            status_code=400,
            detail="Only fixed_rate orders can be accepted directly; use POST /orders/{id}/bid",
        )

    assignment = book_order(db, order)
    order.status = "accepted"
    db.add(
        OrderAction(
            order_id=order.id,
            action="accept",
            carrier_note=(body.carrier_note if body else None),
            created_at=clock.now(),
        )
    )
    db.commit()
    db.refresh(order)
    return ActionResponse(
        ok=True,
        message=(
            f"Order accepted — locked unit {assignment.unit.unit_number} "
            f"({assignment.unit.employee_code}) at {assignment.terminal.code} "
            f"until {order.delivery_at.isoformat()}"
        ),
        order=_enrich(order),
    )


@router.post("/{external_id}/decline", response_model=ActionResponse)
def decline_order(
    external_id: str,
    body: DeclineRequest | None = None,
    db: Session = Depends(get_db),
) -> ActionResponse:
    expire_stale_orders(db)
    order = db.query(LiveOrder).filter(LiveOrder.external_id == external_id.upper()).first()
    order = _require_open(order)
    order.status = "declined"
    db.add(
        OrderAction(
            order_id=order.id,
            action="decline",
            carrier_note=(body.carrier_note if body else None),
            created_at=clock.now(),
        )
    )
    db.commit()
    db.refresh(order)
    return ActionResponse(ok=True, message="Order declined", order=_enrich(order))


@router.post("/{external_id}/bid", response_model=ActionResponse)
def bid_order(
    external_id: str,
    body: BidRequest,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """Submit an open bid. Shipper awards/rejects after a short simulated delay."""
    expire_stale_orders(db)
    order = db.query(LiveOrder).filter(LiveOrder.external_id == external_id.upper()).first()
    order = _require_open(order)
    if order.order_type != "open_bid":
        raise HTTPException(
            status_code=400,
            detail="Only open_bid orders accept bids; use POST /orders/{id}/accept for fixed_rate",
        )
    now = clock.now()
    order.status = "bid_submitted"
    order.winning_bid_rate = body.bid_rate
    order.bid_decision_at = now + timedelta(minutes=settings.bid_decision_sim_minutes)
    db.add(
        OrderAction(
            order_id=order.id,
            action="bid",
            bid_rate=body.bid_rate,
            carrier_note=body.carrier_note,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(order)
    return ActionResponse(
        ok=True,
        message=(
            f"Bid of ${body.bid_rate:.2f} submitted — shipper decides at "
            f"{order.bid_decision_at.isoformat()} (sim time)"
        ),
        order=_enrich(order),
    )


@router.websocket("/ws")
async def orders_ws(websocket: WebSocket) -> None:
    await hub.connect(websocket)
    try:
        db = SessionLocal()
        try:
            expire_stale_orders(db)
            open_orders = (
                db.query(LiveOrder)
                .filter(LiveOrder.status == "open")
                .order_by(LiveOrder.created_at.desc())
                .limit(50)
                .all()
            )
            await websocket.send_json(
                {
                    "event": "snapshot",
                    "orders": [order_to_dict(o) for o in open_orders],
                    "clock": clock.snapshot(),
                }
            )
        finally:
            db.close()

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception:
        await hub.disconnect(websocket)
