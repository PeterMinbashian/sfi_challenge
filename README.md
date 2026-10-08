# Freight Challenge API — Student Guide

This service is the **simulated customer load board** for the Engineering Mini-Challenge:

**Intelligent Freight Load Board & Autonomous Dispatch Engine**  
(see `Challenge.md` for the official brief — export to PDF if needed; `Challenge.pdf` may be an older copy)

You build the dispatch product. This API pretends to be the outside world: terminals, fleet inventory, historical lanes, and a live stream of freight opportunities you can accept, decline, or bid on.

Interactive docs (once running): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Instructors will give you this project as a folder (zip / shared drive / USB). Unzip or copy it somewhere convenient, then open a terminal in that folder.

**Project layout**

```text
freight-challenge-api/
├── Challenge.md                  # Official challenge brief (edit / export to PDF)
├── Challenge.pdf                 # Optional PDF export of the brief
├── README.md                     # This student guide
├── requirements.txt
├── .env.example                  # Optional config template
├── app/                          # FastAPI application
└── data/
    └── historical_shipments.csv  # ML / history dataset
```

Created automatically on your machine (safe to delete / ignore): `.venv/`, `.env`, `freight_challenge.db`

---

## 1. What this API does


| You get from this API                                                 | You still build yourself                                      |
| --------------------------------------------------------------------- | ------------------------------------------------------------- |
| 10 regional terminals (hubs) with lat/lng                             | Your own app DB / schema                                      |
| Fleet **units** per hub (driver+truck as one) + availability counts   | Dispatcher UI (live queues, **manual bid entry**, dashboards) |
| Historical shipments for **ML / pricing models** (SQLite **and** CSV) | Time-window conflict checking in *your* engine                |
| Live orders with expiration countdowns                                | Deadhead / empty-mile optimization                            |
| Accept / decline / bid against the board                              | Optional ML + auto-pilot worker                               |
| Accelerated “brokerage clock” so days pass in minutes                 | Architecture docs + report deliverables                       |


Think of this API as **DAT / load-board lite**: it publishes freight and records bookings. Your system is the **TMS / dispatch brain** that decides what to book and how to assign assets.

---

## 2. Quick start

Requires **Python 3.11+** (3.12/3.13 fine).

```bash
# open a terminal in the freight-challenge-api folder, then:

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

On first boot the API creates local `freight_challenge.db`, loads fleet/terminals, imports `data/historical_shipments.csv` into SQLite, and starts emitting new orders about every **60 wall-clock seconds** (real-time clock by default).

To reset **live** simulation state only: stop the server, delete `freight_challenge.db`, restart (the CSV in `data/` is kept and re-imported).

### Verify your install (full endpoint smoke test)

Use this after setup to confirm **every API endpoint** works on your machine.  
Works on **macOS, Linux, and Windows** (`scripts/smoke_test.py`).

**1. Start the API** (terminal 1):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**2. Run the smoke test** (terminal 2):

```bash
# from the project folder, with your venv activated
python scripts/smoke_test.py
```

Optional flags:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
python scripts/smoke_test.py --full-body   # print full JSON arrays (no truncation)
python scripts/smoke_test.py --no-body     # PASS/FAIL only
```

By default the script prints each request and a pretty-printed response body (long lists truncated to a few items).

**What it checks**


| Area           | Endpoints                                                                                          |
| -------------- | -------------------------------------------------------------------------------------------------- |
| System         | `GET /health`                                                                                      |
| Terminals      | `GET /terminals`, `GET /terminals/{code}`, 404 for bad code                                        |
| Fleet          | `GET /fleet/availability`, `/units`, `/drivers`, `/snapshot`                                       |
| History        | `GET /history/shipments`, `/lanes`, `/shipments.csv`                                               |
| Simulation     | `GET`/`POST /simulation/clock`, `GET`/`POST /simulation/settings`, `POST /simulation/spawn-orders` |
| Orders (read)  | `GET /orders`, `GET /orders/{external_id}`                                                         |
| Orders (write) | `POST .../accept`, `.../decline`, `.../bid` (uses spawned order ids)                               |
| Conflicts      | re-accept → `409`, accept on open-bid → `400`/`409`                                                |
| WebSocket      | `WS /orders/ws` snapshot message                                                                   |


The script prints `PASS` / `FAIL` per check and a final summary. Exit code `0` = all good, `1` = something failed, `2` = could not connect.

**Notes**

- The API must already be running before you start the script.
- The smoke test temporarily sets a **fast order interval** and calls `POST /simulation/spawn-orders` so accept/decline/bid do not wait minutes. It restores normal settings when finished.
- Note: `simulation_speed` only accelerates pickup/delivery/bid timers. **New order arrival rate** is controlled by `order_interval_seconds` (wall clock) or `spawn-orders`.
- Interactive alternative: open Swagger at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
- Windows-only PowerShell copy (optional): `scripts/smoke_test.ps1`

---

## 3. How the brokerage simulation works

This is not a static CSV dump. While the server runs:

1. **New loads appear** on the board (`order_type` = `fixed_rate` or `open_bid`).
2. Each open load has an **expiration** (`expires_at`, plus `seconds_remaining` on responses).
3. You **accept**, **decline**, or **bid**.
4. A successful **accept** (or **won bid**) locks **one fleet unit** (driver+truck) at the origin hub until `delivery_at` — available count drops by 1.
5. **Simulated time defaults to real time** (`simulation_speed=1`). Pickup/delivery clocks match wall clocks unless you speed them up.
6. **New orders** appear about every **60 wall seconds** (several within any 5-minute window). Each open offer stays bookable for **~10 minutes**.
7. When sim time passes `pickup_at`, status → `in_transit`. When it passes `delivery_at`, status → `completed`, the unit becomes available again, and its **home terminal becomes the destination hub** (or nearest hub if the drop was off-pin). Capacity has moved with the freight.
8. You can keep booking new freight as capacity turns over — same pressure a real brokerage feels.

Check counts anytime: `GET /fleet/availability` → `available_units` / `assigned_units` per terminal.

Useful clock endpoints (speed up only if you want a fast demo):

```http
GET  /simulation/clock
POST /simulation/clock
Content-Type: application/json

{"simulation_speed": 1}
```

Examples: `1` = real time (default), `60` ≈ 1 sim hour per real minute, `120` even faster.

---

## 4. Domain concepts (map to the challenge sheet)

### Terminals (hubs)

Home yards for capacity:


| Code | City         | State |
| ---- | ------------ | ----- |
| ATL  | Atlanta      | GA    |
| JAX  | Jacksonville | FL    |
| DFW  | Dallas       | TX    |
| CHI  | Chicago      | IL    |
| CMH  | Columbus     | OH    |
| PHL  | Philadelphia | PA    |
| EWR  | Newark       | NJ    |
| DEN  | Denver       | CO    |
| LAX  | Los Angeles  | CA    |
| SEA  | Seattle      | WA    |


Most loads are hub-to-hub. Some origins/destinations are offset (“Near Atlanta”) so **deadhead miles** are real — you should not assume every pickup is exactly at the terminal pin.

Live orders expose `estimated_deadhead_miles` / `estimated_deadhead_cost` from the board’s nearest free unit at the booking hub to the pickup, plus `estimated_total_cost` (= loaded + deadhead).

### Bidding (manual — no rate card from the API)

There is **no published bidding matrix or suggested bid** on live orders.


| Type         | What you see                        | What you do in your UI                               |
| ------------ | ----------------------------------- | ---------------------------------------------------- |
| `fixed_rate` | `offered_rate` is set (Book-It-Now) | Accept or decline                                    |
| `open_bid`   | `offered_rate` is `null`            | Dispatcher types a **manual** `bid_rate` and submits |


How should teams decide a bid number?

- Build pricing logic in **your** product (rules, cost model, or ML).
- Train / analyze using **historical data**: `GET /history/shipments` and `GET /history/lanes` (past `offered_rate`, `bid_rate`, `won`, `distance_miles`, lane, etc.).
- Optional challenge extension §4A is exactly this: predict win probability / suggest markups from history — **you** own that model; the board will not hand you the answer on each live load.

### Order types


| Type         | Meaning                                                     | Your action                                                     |
| ------------ | ----------------------------------------------------------- | --------------------------------------------------------------- |
| `fixed_rate` | Book-It-Now. Customer posts a non-negotiable `offered_rate` | `POST /orders/{id}/accept` or `/decline`                        |
| `open_bid`   | Lane details only — no posted price                         | `POST /orders/{id}/bid` with `{"bid_rate": <manual USD total>}` |


### Order lifecycle (statuses)

`open` → (`accepted` | `declined` | `expired` | `bid_submitted`)  
`bid_submitted` → (`accepted` if won | `bid_lost`)  
`accepted` → `in_transit` → `completed`

### Weight

Orders include `weight_lbs`. The board max is `**MAX_WEIGHT_LBS` (default 44,000)**. Accept or bid on a heavier load → HTTP `409`. Most live loads are legal; roughly ~8% are overweight so you can demo the failure path.

---

## 5. API reference (student-facing)

Base URL (local): `http://127.0.0.1:8000`

### System & simulation


| Method | Path                | Notes                             |
| ------ | ------------------- | --------------------------------- |
| GET    | `/health`           | Includes current sim time + speed |
| GET    | `/simulation/clock` | Wall time vs simulated time       |
| POST   | `/simulation/clock` | Change `simulation_speed`         |


### Terminals & fleet

Fleet capacity is simplified: **one unit = driver + truck**. There is no separate trailer inventory to manage.


| Method | Path                                              | Notes                                                         |
| ------ | ------------------------------------------------- | ------------------------------------------------------------- |
| GET    | `/terminals`                                      | All hubs (`unit_capacity` = seeded unit count)                |
| GET    | `/terminals/{code}`                               | e.g. `/terminals/ATL`                                         |
| GET    | `/fleet/availability`                             | **Per-terminal counts** (`available_units`, `assigned_units`) |
| GET    | `/fleet/availability?terminal_code=ATL`           | One hub                                                       |
| GET    | `/fleet/snapshot`                                 | Counts + full unit roster                                     |
| GET    | `/fleet/units?terminal_code=ATL&status=available` | List units                                                    |
| GET    | `/fleet/drivers`                                  | Alias of `/fleet/units`                                       |


### History (for analysis / optional ML)

Historic data is stored in the SQLite table `historical_shipments` **and** mirrored to:

`data/historical_shipments.csv`


| Method | Path                                                    | Notes                                    |
| ------ | ------------------------------------------------------- | ---------------------------------------- |
| GET    | `/history/shipments?limit=100&won=true&lane_id=ATL-CHI` | JSON page of past loads                  |
| GET    | `/history/shipments.csv`                                | Download full CSV (same file as on disk) |
| GET    | `/history/lanes`                                        | Aggregated win rate + avg rate by lane   |


Default seed size: **2,500** lanes over ~18 months, biased toward real corridors, with:

- Directional RPM (e.g. West Coast outbound tends richer; backhaul weaker)
- Weight distributions (mostly full truckloads)
- Seasonal effects + fuel surcharge component
- Win/loss tied to how competitive the bid/BIN was vs latent market
- **Operating cost** on every row (`cost_per_mile`, `estimated_cost`) so you can compute profit without guessing
- Extra CSV-only helper columns for feature engineering: `market_rpm`, `all_in_rpm`, `fuel_surcharge_rpm`, `season`, `booked_lead_hours`

Core modeling fields: `lane_id`, `origin_state`, `destination_state`, `distance_miles`, `weight_lbs`, `offered_rate`, `bid_rate`, `won`, `cost_per_mile`, `estimated_cost`, `margin_estimate`, `order_type`, `shipped_at`.

**Margin math**


| Piece                     | Meaning                                                               |
| ------------------------- | --------------------------------------------------------------------- |
| `estimated_cost`          | Loaded-mile operating cost only                                       |
| `estimated_deadhead_cost` | Empty miles from likely board unit → pickup (`cost_per_mile × miles`) |
| `estimated_total_cost`    | Loaded + deadhead (best board-side total)                             |


- Fixed-rate: `margin ≈ offered_rate - estimated_total_cost`
- Open-bid (if won): `margin ≈ bid_rate - estimated_total_cost`
- History rows use loaded cost for `margin_estimate` when `won=true` (no live deadhead replay); still always include `estimated_cost` / `cost_per_mile`

**Note:** Live open-bid orders do **not** expose a suggested bid — use history/CSV to train your own pricing model, then enter bids manually in the UI. Live awards are not scored on bid amount; prioritize **profitable** bookings over win rate.

### Live orders


| Method | Path                            | Notes                                                  |
| ------ | ------------------------------- | ------------------------------------------------------ |
| GET    | `/orders`                       | Default `status=open`. Use `status=all` for everything |
| GET    | `/orders?order_type=fixed_rate` | Filter Book-It-Now                                     |
| GET    | `/orders/{external_id}`         | Single load, e.g. `LD-ABC123...`                       |
| POST   | `/orders/{external_id}/accept`  | Fixed-rate only                                        |
| POST   | `/orders/{external_id}/decline` | Either type while still `open`                         |
| POST   | `/orders/{external_id}/bid`     | Open-bid only; body `{"bid_rate": 2400}`               |
| WS     | `/orders/ws`                    | Push feed                                              |


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

First message is usually a `**snapshot**` of currently open orders. Later messages are `**order.created**` (and occasional `**lifecycle**` ticks when bids resolve / loads complete).

#### Important order fields


| Field                              | Why you care                                               |
| ---------------------------------- | ---------------------------------------------------------- |
| `external_id`                      | Stable ID for accept/bid URLs                              |
| `order_type`                       | `fixed_rate` vs `open_bid`                                 |
| `offered_rate`                     | Payout for Book-It-Now (null on open bid — bid manually)   |
| `estimated_cost`                   | Operating cost for **loaded** miles (USD)                  |
| `cost_per_mile`                    | $/mile used for loaded and deadhead math                   |
| `estimated_deadhead_miles`         | Empty miles from likely free unit → pickup                 |
| `estimated_deadhead_cost`          | Deadhead $ (`miles × cost_per_mile`)                       |
| `estimated_total_cost`             | `estimated_cost + estimated_deadhead_cost`                 |
| `origin_`* / `destination_*`       | Lane geometry + cities                                     |
| `origin_terminal_code`             | Hub hint (may be null if off-hub)                          |
| `distance_miles`                   | Loaded trip length                                         |
| `weight_lbs`                       | Must be ≤ board max (default 44,000) or accept/bid → `409` |
| `pickup_at` / `delivery_at`        | Time-window lock interval (**sim time**)                   |
| `expires_at` / `seconds_remaining` | How long you have to act                                   |
| `assigned_`*                       | Filled after a successful book                             |


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
- Fleet → `GET /fleet/`* and `GET /terminals`  
- Live feed → `GET /orders` and/or `WS /orders/ws`

You are **not** expected to invent the external board; you **are** expected to invent everything behind your dispatcher product.

### Do we need our own database if the API already tracks capacity?

**Yes.** Requirement §3A asks *you* to design a relational schema for shipments, inventory, and temporal locks.  
This API’s locking is the **shared board / sandbox truth** so demos feel real. Your app should still model assignments, conflicts, and utilization — treat API capacity as an external constraint you must respect (and that can reject you with `409`).

### Fixed-rate vs open-bid: who “wins”?

- **Fixed-rate:** first successful `accept` wins that load on the board (subject to capacity).  
- **Open-bid:** your UI collects a **manual** `bid_rate`; after a short **simulated** delay the shipper awards or rejects (`bid_win_probability`, default ~45%). A win auto-assigns capacity like an accept. Live awards are **not** scored on how low/high your bid is.  
- **What does this load cost us?** Use `estimated_total_cost` (loaded + deadhead) vs `offered_rate` (or your bid). `estimated_cost` alone ignores empty miles to the pickup.  
- **What number should we bid?** The board will not suggest a bid. Use `estimated_total_cost` as a floor, then refine with analysis/ML on `/history/`* if you want.

Competing carriers are simulated by **expiration** and **capacity**, not by other student teams hitting the same server (unless you share one instance).

### Goal: make money, not win every bid

Treat the live board as a **capacity + margin** exercise. Declining a cheap fixed-rate load or bidding above break-even and losing is fine. History exists so optional ML can study pricing patterns; core success is profitable utilization and empty-mile control.

### What clock do pickup / delivery / expiration use?

**Simulated time** from `GET /simulation/clock`.  
Do not assume `pickup_at` is “wall clock + N hours” for UX timers without reading the sim clock. At default speed, multi-hour windows complete in a few real minutes.

### What is “deadheading” expected to mean in grading?

Empty miles from a truck’s **current/last known position** (or home terminal) to the **next pickup**.  
The board publishes `estimated_deadhead_`* for its own nearest free unit. Your optimizer may pick a different unit — recompute with `cost_per_mile`.  
After delivery, capacity **moves** to the destination hub, so ATL→CHI then a CHI outbound load is the intended chaining pattern. Exact algorithm is yours (greedy, graph, ILP, heuristics, etc.).

### Are weight / location constraints enforced by the board?

**Yes for capacity and weight; margin is yours.**  

- Location/capacity: booking fails with `409` if the origin hub has **no free fleet unit** for that pickup window.  
- Weight: booking/bid fails with `409` if `weight_lbs` > `MAX_WEIGHT_LBS` (default 44,000).  
- Business margin / “is this worth it?”: **your** backend should still enforce.

### WebSockets or polling?

Either satisfies “live feed.” WebSockets are nicer for the UI; polling is fine for MVP. Many teams do both (WS primary, poll as fallback).

### Is auto-pilot / ML required?

**No.** Challenge §4 is optional. Core grading centers on ingestion, schema/locks, constraint enforcement, dispatch UI, and a credible optimization story. History endpoints exist so ML/analytics teams have labeled cost, win/loss, and margin fields if they opt in.

### What should the frontend show at minimum?

From §3D:

1. Live queue split by fixed-rate vs open-bid
2. Accept / decline for fixed-rate
3. Bid entry for open-bid
4. Terminal utilization + some schedule / capacity warning view

### What are the suggested deliverables, concretely?


| Deliverable       | Practical meaning                                                                |
| ----------------- | -------------------------------------------------------------------------------- |
| Architecture docs | ERD + diagram of feed → DB → optimizer → UI; explain time-window locks           |
| Backend           | Service that ingests this API, validates constraints, exposes *your* APIs        |
| Frontend          | Dispatcher prototype wired to your backend (not only raw Swagger)                |
| Report            | How you handled constraints, scheduling, empty miles, history usage, scale notes |


### Can we change simulation speed?

Yes, for demos (`POST /simulation/clock`). Document the speed you used if timing screenshots matter. Instructors may ask you to run at the default (`60`).

### Auth?

None in the local challenge build. Do not put secrets in client code for this exercise; if you deploy publicly, put a reverse proxy / API key in front.

---

## 8. Configuration (operators / instructors)

Optional `.env` in the project root:

```env
DATABASE_URL=sqlite:///./freight_challenge.db
ORDER_INTERVAL_SECONDS=60
ORDER_TTL_SIM_MINUTES=10
SIMULATION_SPEED=1
BID_WIN_PROBABILITY=0.45
BID_DECISION_SIM_MINUTES=3
UNITS_PER_TERMINAL=8
HISTORY_ROWS=2500
MAX_WEIGHT_LBS=44000
```


| Variable                 | Effect                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------- |
| `SIMULATION_SPEED`       | Sim seconds per 1 wall second (`1` = real time; `60` ≈ 1 sim hour per real minute) |
| `ORDER_TTL_SIM_MINUTES`  | How long a load stays `open` (sim minutes; = wall minutes at speed 1)              |
| `ORDER_INTERVAL_SECONDS` | Wall seconds between new offers (60 ⇒ ~5 new loads in 5 minutes)                   |
| `BID_*`                  | How open bids are awarded                                                          |
| `MAX_WEIGHT_LBS`         | Accept/bid rejected above this weight                                              |


---

## 9. Common errors


| HTTP  | Typical cause                                                                               |
| ----- | ------------------------------------------------------------------------------------------- |
| `400` | Wrong verb for order type (accept on open-bid, or bid on fixed-rate)                        |
| `404` | Bad `external_id` / terminal code                                                           |
| `409` | Expired, not `open`, no free capacity at the hub for that pickup window, or weight over max |


---

## 10. Fair-use tips for the challenge

- Build **your** system to survive the board restarting (re-seed wipes live orders).  
- Prefer `external_id` as the join key to the board.  
- Show sim time in the UI so pickup/delivery timelines make sense.  
- Optimize for **margin and empty miles**, not “accept everything.”  
- Read `Challenge.pdf` for business context; use **this README** for how the provided API behaves.

Good luck — run freight like a brokerage, not a CRUD tutorial.