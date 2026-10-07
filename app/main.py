import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal, init_db
from app.routers import fleet, history, orders, simulation, terminals
from app.schemas import HealthOut
from app.seed import seed_if_empty
from app.services.clock import clock
from app.services.order_simulator import simulator_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()

    stop_event = asyncio.Event()
    task = asyncio.create_task(simulator_loop(stop_event))
    app.state.simulator_stop = stop_event
    app.state.simulator_task = task
    yield
    stop_event.set()
    await task


app = FastAPI(
    title=settings.app_name,
    description=(
        "Simulated freight load board for the Engineering Mini-Challenge: "
        "Intelligent Freight Load Board & Autonomous Dispatch Engine. "
        "Provides terminals, fleet inventory, historical shipments, and a live order feed."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(terminals.router)
app.include_router(fleet.router)
app.include_router(history.router)
app.include_router(orders.router)
app.include_router(simulation.router)


@app.get("/health", response_model=HealthOut, tags=["system"])
def health() -> HealthOut:
    snap = clock.snapshot()
    return HealthOut(
        status="ok",
        app=settings.app_name,
        sim_time_utc=snap["sim_time_utc"],
        simulation_speed=snap["simulation_speed"],
    )
