# Engineering Mini-Challenge: Intelligent Freight Load Board & Autonomous Dispatch Engine

---

## 1. Executive Summary & Background

In the freight transportation and logistics industry, carriers manage hundreds of regional shipments across multiple geographic hubs (terminals) every day. Freight dispatchers monitor incoming shipment opportunities (“loads”) published on customer portals. These opportunities generally arrive in two formats:

- **Fixed-Rate Offers (“Book It Now”)**  
  The customer offers a predetermined, non-negotiable price. The dispatcher must quickly evaluate whether the payout covers operating costs (fuel, wear-and-tear, driver pay) and accept or decline before a competing carrier takes it.

- **Open Bids**  
  The customer posts lane details (origin, destination, weight, pickup time) without a set price. Carriers submit a bid rate ($) for the load. Your job is to bid in a way that still protects target **profit margins** when you win — not to win every auction at any price.

### Why This Matters

**The business problem.** Dispatchers make high-volume, high-stress, time-sensitive decisions under hard physical constraints: a finite number of fleet units at each terminal, a maximum legal/equipment weight, and geographic alignment. In particular:

- **Deadheading.** Driving empty to a pickup burns fuel and wastes money.
- **Resource scheduling (time windows).** Every order has a strict pickup time, drop-off time, and ETA. Once a fleet unit is assigned, it is unavailable for any other work during that window.

**The engineering challenge.** Build a full-stack, real-time web application and decision-support engine that:

- Processes historical data and fleet capacity inventories  
- Consumes a live simulated API feed of freight orders  
- Tracks temporal resource allocation  
- Optimizes routes to minimize empty miles  
- Automates booking logic under capacity and margin constraints  

**Success looks like profitable utilization** — booking loads that make money after cost, with healthy fleet use and low empty miles — **not** maximizing how many bids you win.

---

## 2. Provided Resources, Data Streams & Fleet Constraints

To jumpstart development, the following assets are provided (via the Freight Challenge API and its dataset):

### Historical dataset

Past shipment records with pricing, lane data, win/loss outcomes, and **operating cost** fields so you can analyze profitability or train predictive models. Typical fields include distance, weight, order type, offered/bid rates, `cost_per_mile`, `estimated_cost`, `won`, and `margin_estimate` (when the load was won).

### Fleet capacity inventory

Baseline data for available **fleet units** at each terminal.  
For this challenge, one fleet unit = **driver + truck** treated as a single bookable asset (no separate trailer inventory to manage).

**Capacity follows the freight.** When a unit finishes delivery, it is re-homed to the **destination hub** (or the nearest hub if the drop is off-pin). That unit’s next available booking capacity appears at that destination terminal — so chaining ATL→CHI then a CHI outbound load is how the sandbox models network flow.

### Live simulated API feed

A stream of real-time simulated customer orders with ticking expiration countdowns (WebSockets or polling). Orders include origin/destination, weight, distance, pickup/delivery windows, and cost fields:

- **`estimated_cost` / `cost_per_mile`** — operating cost for the **loaded** miles  
- **`estimated_deadhead_miles` / `estimated_deadhead_cost`** — empty move from the board’s likely unit to the pickup  
- **`estimated_total_cost`** — loaded + deadhead (use this for board-side margin)

### Order attributes & constraints

Every incoming order specifies origin, destination, weight, payout information (posted rate for fixed-rate loads; your bid for open-bid loads), expiration window, and strict pickup/drop-off time constraints (ETAs).

The board **rejects** accept/bid when `weight_lbs` exceeds the configured max (default **44,000 lbs**) with HTTP `409`. A minority of live loads are intentionally overweight so you can handle that failure path.

Use the companion **README.md** that ships with this API for endpoint details, setup, and how the simulation clock behaves.

---

## 3. Core System Requirements

Your solution must integrate several classic software engineering, scheduling, and distributed-systems components.

### A. Relational database & state management

Design a relational schema to track:

- Shipment attributes  
- Real-time terminal inventory  
- Temporal resource locks (when specific fleet units are busy vs. idle based on order time windows)

You own this schema in **your** application. The provided API is the external load board / sandbox — not a substitute for your product database.

### B. Real-time data ingestion pipeline

Consume the provided live API feed of incoming load opportunities and dynamic expiration countdowns, updating system state concurrently.

### C. Fleet, schedule & route optimization engine

- **Time-window conflict checking.** Prevent double-booking: a fleet unit cannot be assigned to overlapping order time windows.  
- **Empty-mile reduction (deadheading).** Help dispatchers (or an automated system) chain loads (e.g. drop Load A and pick up Load B nearby) to minimize empty mileage.  
- **Mileage / continuity optimization.** Prioritize orders that improve total efficiency and route continuity for each unit (capacity moves with deliveries — see §2).  
- **Margin awareness.** Use published costs so accept/bid decisions are profit-aware, not “take everything.”

### D. Web-based dispatch interface (frontend)

Build a responsive UI allowing dispatchers to:

- View live-updating freight queues filtered by Fixed-Rate vs. Open-Bid  
- Accept/decline fixed-rate shipments with immediate UI feedback  
- Input and submit custom rate bids for open-bid shipments  
- Monitor real-time terminal utilization, schedule timelines, and capacity warnings  
- (Recommended) Show estimated cost and implied margin before booking

### E. Business & constraint logic (backend enforcement)

Enforce backend guardrails that prevent orders from being accepted when:

- A terminal lacks an available fleet unit for that time window  
- Weight exceeds the board max (the API will also `409` — your UI should surface this cleanly)  
- Location / assignment rules you define are violated  
- (Recommended) Expected margin falls below a threshold you set  

The board enforces capacity and max weight. **Your** product should still refuse bad business (weak margin, ugly deadhead) even when the board would accept it.

---

## 4. Optional Advanced Extensions

These are **optional**. Core success is a working dispatch product that books profitably under capacity and time-window constraints.

### A. Analytics / machine learning (optional)

Use the historical dataset (`estimated_cost`, `offered_rate` / `bid_rate`, `won`, `margin_estimate`, lane and season features) to:

- Analyze which lanes and rate levels tend to be profitable after cost  
- Optionally train a model that suggests a bid or an accept/decline recommendation  
- Surface that recommendation in the UI for a human dispatcher  

**Important:** Live open-bid awards on the simulated board are **not** scored on the dollar amount of your bid. Treat history as the place to study pricing patterns; treat the live board as practice making **money-aware** decisions when a load is won. Optimizing only for “win rate” is the wrong objective.

### B. Autonomous “auto-pilot” dispatch mode (optional)

Build a background worker that can accept fixed-rate loads and submit open bids without a click — but only when your own **operational guardrails** pass, for example:

- A free fleet unit exists for the pickup/delivery window (no double-booking)  
- Expected margin is above a minimum threshold you define (`payout − estimated_total_cost`, or your own deadhead model)  
- Empty-mile / deadhead cost to the pickup is acceptable  


“Safety” here means operational guardrails (capacity, schedule conflicts, minimum margin) — not a separate compliance product. Auto-pilot should prefer profitable utilization over booking every load.

---

## 5. Suggested Deliverables

### A. Architecture documentation

Database entity-relationship diagram (ERD), system architecture diagram, and data-flow explanations (especially how time-window locking is handled).

### B. Backend services & APIs

Functional backend handling API feed ingestion, capacity tracking, temporal constraint validation, and routing/optimization logic, exposed via REST and/or WebSocket endpoints.

### C. Frontend prototype

An interactive dispatcher web application demonstrating the live workflow, fleet utilization, and schedule tracking.

### D. Engineering & business report

A concise summary covering:

- How constraint logic, time-window scheduling, and empty-mile optimization were implemented  
- How historical data (and cost/margin fields) were leveraged  
- How you balanced booking volume vs. profitability  
- Recommendations for scaling the system to an enterprise level  

---

## 6. Evaluation emphasis (how to think about “done”)

Strong solutions typically demonstrate:

1. Reliable ingestion of the live board  
2. Correct capacity and time-window locking in **your** system  
3. A usable dispatcher UI for fixed-rate and open-bid workflows  
4. Credible empty-mile / chaining logic  
5. Decisions guided by **cost and margin**, not blind accept/bid volume  

Optional ML and auto-pilot can strengthen a submission but are not required for a complete core solution.

---

## Appendix — Quick reference (provided API)

| You get from the API | You still build yourself |
|---|---|
| Regional terminals (hubs) with lat/lng | Your own app DB / schema |
| Fleet units per hub + availability | Dispatcher UI and dashboards |
| Historical shipments (JSON + CSV) with cost/margin fields | Time-window conflict checking in your engine |
| Live orders with expiration countdowns + estimated cost | Deadhead / empty-mile optimization |
| Accept / decline / bid against the board | Optional ML + auto-pilot worker |
| Simulation clock for demos | Architecture docs + report |

**Margin math**

- Loaded cost only: `estimated_cost` (fuel + driver + wear on loaded miles)  
- Board-side total: `estimated_total_cost ≈ estimated_cost + estimated_deadhead_cost`  
- Fixed-rate: `margin ≈ offered_rate − estimated_total_cost`  
- Open-bid (when won): `margin ≈ bid_rate − estimated_total_cost`  

If you assign a different unit than the board’s nearest free unit, recompute deadhead from **your** unit’s position to the pickup using `cost_per_mile`.

See the accompanying `README.md` for setup, endpoints, and simulation details.
