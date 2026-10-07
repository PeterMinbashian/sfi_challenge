# Freight Challenge API — Student Guide

This service is the **simulated customer load board** for the Engineering Mini-Challenge:

**Intelligent Freight Load Board & Autonomous Dispatch Engine**  
(see `Challenge.pdf` for the official brief)

You build the dispatch product. This API pretends to be the outside world: terminals, fleet inventory, historical lanes, and a live stream of freight opportunities you can accept, decline, or bid on.

Interactive docs (once running): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Clone from GitLab

```bash
git clone <GITLAB_REPO_URL> freight-challenge-api
cd freight-challenge-api
```

Replace `<GITLAB_REPO_URL>` with the URL your instructors provide (HTTPS or SSH).

**Repo layout**

```text
freight-challenge-api/
├── Challenge.pdf                 # Official challenge brief
├── README.md                     # This student guide
├── requirements.txt
├── .env.example                  # Optional config template
├── app/                          # FastAPI application
└── data/
    └── historical_shipments.csv  # ML / history dataset
```

Local-only files (not in Git): `.venv/`, `.env`, `freight_challenge.db`

---

## 1. What this API does

| You get from this API | You still build yourself |
|---|---|
| 10 regional terminals (hubs) with lat/lng | Your own app DB / schema |
| Fleet **units** per hub (driver+truck as one) + availability counts | Dispatcher UI (live queues, **manual bid entry**, dashboards) |
| Historical shipments for **ML / pricing models** (SQLite **and** CSV) | Time-window conflict checking in *your* engine |
| Live orders with expiration countdowns | Deadhead / empty-mile optimization |
| Accept / decline / bid against the board | Optional ML + auto-pilot worker |
| Accelerated “brokerage clock” so days pass in minutes | Architecture docs + report deliverables |

Think of this API as **DAT / load-board lite**: it publishes freight and records bookings. Your system is the **TMS / dispatch brain** that decides what to book and how to assign assets.

---

## 2. Quick start

Requires **Python 3.11+** (3.12/3.13 fine).

```bash
git clone <GITLAB_REPO_URL> freight-challenge-api
cd freight-challenge-api

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt

# optional
# copy .env.example .env

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: `http://127.0.0.1:8000/docs`
- Health: `GET http://127.0.0.1:8000/health`

On first boot the API creates local `freight_challenge.db`, loads fleet/terminals, imports `data/historical_shipments.csv` into SQLite, and starts emitting new orders about every **8 wall-clock seconds**.

To reset **live** simulation state only: stop the server, delete `freight_challenge.db`, restart (the CSV in `data/` is kept and re-imported).

---

## 3. How the brokerage simulation works

This is not a static CSV dump. While the server runs:

1. **New loads appear** on the board (`order_type` = `fixed_rate` or `open_bid`).
2. Each open load has an **expiration** (`expires_at`, plus `seconds_remaining` on responses).
3. You **accept**, **decline**, or **bid**.
4. A successful **accept** (or **won bid**) locks **one fleet unit** (driver+truck) at the origin hub until `delivery_at` — available count drops by 1.
5. **Simulated time** advances faster than real time (default **60×** → about **1 real minute ≈ 1 simulated hour**).
6. When sim time passes `pickup_at`, status → `in_transit`. When it passes `delivery_at`, status → `completed` and the unit becomes available again (may relocate toward the destination hub).
7. You can keep booking new freight as capacity turns over — same pressure a real brokerage feels.

Check counts anytime: `GET /fleet/availability` → `available_units` / `assigned_units` per terminal.

Useful clock endpoints:

```http
GET  /simulation/clock
POST /simulation/clock
Content-Type: application/json

{"simulation_speed": 120}
```

---

## 4. Domain concepts (map to the challenge sheet)

### Terminals (hubs)

Home yards for capacity:

| Code | City | State |
|------|------|-------|
| ATL | Atlanta | GA |
| JAX | Jacksonville | FL |
| DFW | Dallas | TX |
| CHI | Chicago | IL |
| CMH | Columbus | OH |
| PHL | Philadelphia | PA |
| EWR | Newark | NJ |
| DEN | Denver | CO |
| LAX | Los Angeles | CA |
| SEA | Seattle | WA |

Most loads are hub-to-hub. Some origins/destinations are offset (“Near Atlanta”) so **deadhead miles** are real — you should not assume every pickup is exactly at the terminal pin.

### Bidding (manual — no rate card from the API)

There is **no published bidding matrix or suggested bid** on live orders.

| Type | What you see | What you do in your UI |
|---|---|---|
| `fixed_rate` | `offered_rate` is set (Book-It-Now) | Accept or decline |
| `open_bid` | `offered_rate` is `null` | Dispatcher types a **manual** `bid_rate` and submits |

How should teams decide a bid number?
- Build pricing logic in **your** product (rules, cost model, or ML).
- Train / analyze using **historical data**: `GET /history/shipments` and `GET /history/lanes` (past `offered_rate`, `bid_rate`, `won`, `distance_miles`, equipment, lane, etc.).
- Optional challenge extension §4A is exactly this: predict win probability / suggest markups from history — **you** own that model; the board will not hand you the answer on each live load.

### Order types

| Type | Meaning | Your action |
|---|---|---|
| `fixed_rate` | Book-It-Now. Customer posts a non-negotiable `offered_rate` | `POST /orders/{id}/accept` or `/decline` |
| `open_bid` | Lane details only — no posted price | `POST /orders/{id}/bid` with `{"bid_rate": <manual USD total>}` |

### Order lifecycle (statuses)

`open` → (`accepted` | `declined` | `expired` | `bid_submitted`)  
`bid_submitted` → (`accepted` if won | `bid_lost`)  
`accepted` → `in_transit` → `completed`

### Equipment

`dry_van` | `reefer` | `flatbed`  
Match equipment when you can; booking prefers a free unit with the same `equipment_type`, then falls back to any free unit at that hub.

### Weight

Orders include `weight_lbs` (roughly 8,000–44,000). The challenge asks **you** to enforce weight/equipment rules in *your* backend before you call accept/bid. This API does not reject on weight by itself.

---

## 5. API reference (student-facing)

Base URL (local): `http://127.0.0.1:8000`

### System & simulation

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Includes current sim time + speed |
| GET | `/simulation/clock` | Wall time vs simulated time |
| POST | `/simulation/clock` | Change `simulation_speed` |

### Terminals & fleet

Fleet capacity is simplified: **one unit = driver + truck**. There is no separate trailer inventory to manage.

| Method | Path | Notes |
|---|---|---|
| GET | `/terminals` | All hubs (`unit_capacity` = seeded unit count) |
| GET | `/terminals/{code}` | e.g. `/terminals/ATL` |
| GET | `/fleet/availability` | **Per-terminal counts** (`available_units`, `assigned_units`) |
| GET | `/fleet/availability?terminal_code=ATL` | One hub |
| GET | `/fleet/snapshot` | Counts + full unit roster |
| GET | `/fleet/units?terminal_code=ATL&status=available` | List units |
| GET | `/fleet/drivers` | Alias of `/fleet/units` |

### History (for analysis / optional ML)

Historic data is stored in the SQLite table `historical_shipments` **and** mirrored to:

`data/historical_shipments.csv`

| Method | Path | Notes |
|---|---|---|
| GET | `/history/shipments?limit=100&won=true&lane_id=ATL-CHI` | JSON page of past loads |
| GET | `/history/shipments.csv` | Download full CSV (same file as on disk) |
| GET | `/history/lanes` | Aggregated win rate + avg rate by lane |

Default seed size: **2,500** lanes over ~18 months, biased toward real corridors, with:

- Directional RPM (e.g. West Coast outbound tends richer; backhaul weaker)
- Equipment mix (dry van / reefer / flatbed) and weight distributions
- Seasonal effects + fuel surcharge component
- Win/loss tied to how competitive the bid/BIN was vs latent market
- Extra CSV-only helper columns for feature engineering: `market_rpm`, `all_in_rpm`, `fuel_surcharge_rpm`, `season`, `booked_lead_hours`

Core modeling fields: `lane_id`, `origin_state`, `destination_state`, `distance_miles`, `weight_lbs`, `offered_rate`, `bid_rate`, `won`, `margin_estimate`, `order_type`, `equipment_type`, `shipped_at`.

**Note:** Live open-bid orders still do **not** expose suggested bids — use history/CSV to train your own model, then enter bids manually in the UI.

### Live orders

| Method | Path | Notes |
|---|---|---|
| GET | `/orders` | Default `status=open`. Use `status=all` for everything |
| GET | `/orders?order_type=fixed_rate` | Filter Book-It-Now |
| GET | `/orders/{external_id}` | Single load, e.g. `LD-ABC123...` |
| POST | `/orders/{external_id}/accept` | Fixed-rate only |
| POST | `/orders/{external_id}/decline` | Either type while still `open` |
| POST | `/orders/{external_id}/bid` | Open-bid only; body `{"bid_rate": 2400}` |
| WS | `/orders/ws` | Push feed |

#### Polling example

```bash
curl http://127.0.0.1:8000/orders?status=open
curl -X POST http://127.0.0.1:8000/orders/LD-XXXXXXXXXX/accept
curl -X POST http://127.0.0.1:8000/orders/LD-YYYYYYYYYY/bid ^
  -H "Content-Type: application/json" ^
  -d "{\"bid_rate\": 2750}"
```

#### WebSocket example (browser / Node)

```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/orders/ws");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.event: "snapshot" | "order.created" | "lifecycle"
  console.log(msg.event, msg);
};

// optional keepalive
setInterval(() => ws.send("ping"), 15000);
```

First message is usually a **`snapshot`** of currently open orders. Later messages are **`order.created`** (and occasional **`lifecycle`** ticks when bids resolve / loads complete).

#### Important order fields

| Field | Why you care |
|---|---|
| `external_id` | Stable ID for accept/bid URLs |
| `order_type` | `fixed_rate` vs `open_bid` |
| `offered_rate` | Payout for Book-It-Now (null on open bid — bid manually) |
| `origin_*` / `destination_*` | Lane geometry + cities |
| `origin_terminal_code` | Hub hint (may be null if off-hub) |
| `distance_miles` | Revenue/cost and empty-mile math |
| `weight_lbs` / `equipment_type` | Constraint checks |
| `pickup_at` / `delivery_at` | Time-window lock interval (**sim time**) |
| `expires_at` / `seconds_remaining` | How long you have to act |
| `assigned_*` | Filled after a successful book |

---

## 6. Suggested integration flow

```text
┌─────────────┐     poll / websocket      ┌──────────────────────┐
│  This API   │ ─────────────────────────▶│  Your ingestion      │
│  (board)    │                           │  service             │
└──────▲──────┘                           └──────────┬───────────┘
       │                                             │
       │ accept / bid                                ▼
       │                                   ┌──────────────────────┐
       └───────────────────────────────────│  Your dispatch / DB  │
                                           │  UI + optimizers     │
                                           └──────────────────────┘
```

Recommended approach:

1. On startup, load `/terminals`, `/fleet/snapshot`, and enough `/history/*` for analytics.
2. Subscribe to `/orders/ws` **or** poll `/orders?status=open` every few seconds.
3. Mirror interesting loads into **your** database (do not treat this API’s SQLite file as your app DB).
4. Before calling accept/bid, run **your** checks: capacity, time-window overlap, weight, deadhead cost, margin.
5. Call this API to book. Handle `409` (expired, already taken, or no capacity at hub for that window).
6. Drive your UI off **your** state; use `/fleet/snapshot` as a cross-check / demo dashboard data source.
7. Use `/simulation/clock` so timelines in the UI show **sim time**, not only wall time.

---

## 7. Clarifications (challenge doc ambiguities)

The challenge PDF is intentionally high-level. Use these interpretations unless your instructors say otherwise.

### “Provided historical dataset / fleet inventory / live API”
**Resolved by this service.**  
- History → `GET /history/shipments` and `GET /history/lanes`  
- Fleet → `GET /fleet/*` and `GET /terminals`  
- Live feed → `GET /orders` and/or `WS /orders/ws`

You are **not** expected to invent the external board; you **are** expected to invent everything behind your dispatcher product.

### Do we need our own database if the API already tracks capacity?
**Yes.** Requirement §3A asks *you* to design a relational schema for shipments, inventory, and temporal locks.  
This API’s locking is the **shared board / sandbox truth** so demos feel real. Your app should still model assignments, conflicts, and utilization — treat API capacity as an external constraint you must respect (and that can reject you with `409`).

### Fixed-rate vs open-bid: who “wins”?
- **Fixed-rate:** first successful `accept` wins that load on the board (subject to capacity).  
- **Open-bid:** your UI collects a **manual** `bid_rate`; after a short **simulated** delay the shipper awards or rejects (`bid_win_probability`, default ~45%). A win auto-assigns capacity like an accept.  
- **What number should we bid?** Not provided by the live API. Derive it in your product from cost models and/or ML on `/history/*`.

Competing carriers are simulated by **expiration** and **capacity**, not by other student teams hitting the same server (unless you share one instance).

### What clock do pickup / delivery / expiration use?
**Simulated time** from `GET /simulation/clock`.  
Do not assume `pickup_at` is “wall clock + N hours” for UX timers without reading the sim clock. At default speed, multi-hour windows complete in a few real minutes.

### What is “deadheading” expected to mean in grading?
Empty miles from a truck’s **current/last known position** (or home terminal) to the **next pickup**.  
Chaining Load A drop → nearby Load B pickup should score better than sending an idle Atlanta truck to grab a Dallas pickup when a Dallas truck is free. Exact algorithm is yours (greedy, graph, ILP, heuristics, etc.).

### Are weight / location constraints enforced by the board?
**Partially.**  
- Location/capacity: booking fails with `409` if the origin hub has **no free fleet unit** for that pickup window (`available_units` would be 0 for that time).  
- Weight / business margin rules: **your** backend must enforce (challenge §3E). The board will still let you accept a heavy load if a unit exists.

### WebSockets or polling?
Either satisfies “live feed.” WebSockets are nicer for the UI; polling is fine for MVP. Many teams do both (WS primary, poll as fallback).

### Is auto-pilot / ML required?
**No.** Challenge §4 is optional. Core grading centers on ingestion, schema/locks, constraint enforcement, dispatch UI, and a credible optimization story. History endpoints exist so ML teams have data if they opt in.

### What should the frontend show at minimum?
From §3D:
1. Live queue split by fixed-rate vs open-bid  
2. Accept / decline for fixed-rate  
3. Bid entry for open-bid  
4. Terminal utilization + some schedule / capacity warning view  

### What are the suggested deliverables, concretely?
| Deliverable | Practical meaning |
|---|---|
| Architecture docs | ERD + diagram of feed → DB → optimizer → UI; explain time-window locks |
| Backend | Service that ingests this API, validates constraints, exposes *your* APIs |
| Frontend | Dispatcher prototype wired to your backend (not only raw Swagger) |
| Report | How you handled constraints, scheduling, empty miles, history usage, scale notes |

### Can we change simulation speed?
Yes, for demos (`POST /simulation/clock`). Document the speed you used if timing screenshots matter. Instructors may ask you to run at the default (`60`).

### Auth?
None in the local challenge build. Do not put secrets in client code for this exercise; if you deploy publicly, put a reverse proxy / API key in front.

---

## 8. Configuration (operators / instructors)

Optional `.env` in the project root:

```env
DATABASE_URL=sqlite:///./freight_challenge.db
ORDER_INTERVAL_SECONDS=8
ORDER_TTL_SIM_MINUTES=45
SIMULATION_SPEED=60
BID_WIN_PROBABILITY=0.45
BID_DECISION_SIM_MINUTES=15
UNITS_PER_TERMINAL=8
HISTORY_ROWS=2500
```

| Variable | Effect |
|---|---|
| `SIMULATION_SPEED` | Simulated seconds per 1 wall second (`60` ≈ 1 sim hour per real minute) |
| `ORDER_TTL_SIM_MINUTES` | How long a load stays `open` in **sim** minutes |
| `ORDER_INTERVAL_SECONDS` | Wall seconds between new offers |
| `BID_*` | How open bids are awarded |

---

## 9. Common errors

| HTTP | Typical cause |
|---|---|
| `400` | Wrong verb for order type (accept on open-bid, or bid on fixed-rate) |
| `404` | Bad `external_id` / terminal code |
| `409` | Expired, not `open`, or no free capacity at the hub for that pickup window |

---

## 10. Fair-use tips for the challenge

- Build **your** system to survive the board restarting (re-seed wipes live orders).  
- Prefer `external_id` as the join key to the board.  
- Show sim time in the UI so pickup/delivery timelines make sense.  
- Optimize for **margin and empty miles**, not “accept everything.”  
- Read `Challenge.pdf` for business context; use **this README** for how the provided API behaves.

Good luck — run freight like a brokerage, not a CRUD tutorial.
