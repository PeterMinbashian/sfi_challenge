# Data files

| File | Purpose |
|------|---------|
| `historical_shipments.csv` | Seed / ML training history (also loaded into SQLite on first API boot) |

Includes `cost_per_mile` and `estimated_cost` on every row so students can compute margin vs `offered_rate` / `bid_rate` without inventing a cost model. `margin_estimate` is filled only when `won=true`.

The live SQLite database (`freight_challenge.db`) is created locally when you start the API (it is not part of the distributed project files).
