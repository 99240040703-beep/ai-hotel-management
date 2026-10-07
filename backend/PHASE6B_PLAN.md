# Phase 6B/6C — Implementation Plan

Written after inspecting the actual codebase, not before.

## What inspection found

**Reusable, working, must not be duplicated**

| Asset | Location |
|---|---|
| 12 analytics functions | `services/analytics_service.py` |
| Lifecycle rules / statuses | `services/order_lifecycle.py` |
| Authoritative pricing | `services/order_service.py` |
| ML: demand, revenue forecast, waste, pricing, sentiment, recommender | `ml/*.py` |
| Personalised recommendations | `services/recommendation_service.py` |
| Legacy fixed-intent assistant (176 Phase 5 assertions depend on it) | `services/ai_business_service.py` |

**Genuinely missing** (this is the whole of Phase 6C's job)

1. `order_headers.status` holds only the *current* status. Nothing records
   when an order moved Placed→Confirmed→…→Served, or when it was cancelled.
   Prep time, delays and cancellation rate are therefore uncomputable.
2. No `status_changed_at` / `completed_at` / `paid_at` on any order row.
3. No inventory movement ledger — `inventory` is current state only.
4. No payment transaction record anywhere. `payment_status` is a single
   string per header. There is no amount, method or reference to read.
5. No delivery lifecycle. `order_type='delivery'` exists; nothing tracks it.
6. `reservations` has no `updated_at`.
7. The assistant can only answer 15 closed intents, one data source at a
   time, with no follow-up context.

## Decisions

### D1 — Add one event table, not one per subsystem
`RestaurantEvent(id, event_type, entity_type, entity_id, actor_user_id,
metadata JSON, created_at)`. Inventory movements, waste, reviews and
reservations all become rows in *this* table via `entity_type`. Adding an
`InventoryEvent`, `WasteEvent` and `OrderEvent` would be three duplicate
event systems, which the brief explicitly forbids.

Historical rows are **not** backfilled. A timestamp for a transition that
was never recorded would be fabricated.

### D2 — Payment: report the limitation, do not invent a ledger
The brief lists payments as a domain but forbids fabrication. There is no
payment table. So `get_payment_metrics` reports the payment **status**
distribution and outstanding value from `order_headers`, and states
explicitly that no per-transaction record (amount/method/reference)
exists. Building a payments table now would create records with no
gateway behind them — fake payments, which the brief forbids.

### D3 — Delivery: same treatment
Delivery *orders* exist as `order_type`. Delivery *lifecycle* does not.
Report order counts; report the missing lifecycle as a limitation.

### D4 — Keep `/api/ai/assistant` exactly as it is
Phase 5 asserts on `intent` strings from that endpoint. The new
restaurant-wide assistant lives at `/api/ai/assistant/ask`. The frontend
moves to the new one. Nothing is removed, so all 705 tests keep their
subject.

### D5 — Router selects *domains*, not answers
The router scores the question against per-domain vocabularies and returns
a ranked domain set plus a resolved time window. It never produces prose
and never picks one branch. An unmatched question is not refused — it
falls back to a business summary, because "I don't know what you mean" is
not the same as "the restaurant has no data".

### D6 — All arithmetic stays in Python
Growth %, AOV, cancellation rate, collection %, prep time. The
orchestrator computes them from tool output. No arithmetic is delegated
to a language model.

## New files

| File | Purpose |
|---|---|
| `services/event_service.py` | `record_event()`, event queries, idempotent-safe recorder |
| `services/restaurant_tools.py` | 18 tool functions + `TOOL_REGISTRY` allowlist |
| `services/question_router.py` | Time-window resolution + multi-domain selection |
| `services/ai_operations_service.py` | Orchestration, context, answer composition |
| `scripts/migrate_phase6b_operations.py` | Idempotent, additive, dry-run by default |
| `scripts/test_phase6b_ai_operations.py` | Phase 6B/6C acceptance tests |

## Modified files

| File | Change |
|---|---|
| `models.py` | `RestaurantEvent`; 3 nullable OrderHeader timestamps; `Reservation.updated_at` |
| `schemas.py` | `OperationsAnswer`, `OperationsResponse`, `AssistantTurn` |
| `routes/ai.py` | `/assistant/ask`, `/assistant/context`, `/assistant/capabilities` (all `require_admin`) |
| `routes/orders.py` | Record lifecycle + payment events on status change |
| `routes/reservations.py` | Record reservation events |
| `routes/inventory.py`, `routes/waste.py`, `routes/reviews.py` | Record entity events |
| `frontend/src/api.js` | `askOperationsQuestion`, `getAssistantCapabilities`, `clearAssistantContext` |
| `frontend/src/AIChartBoard.jsx` | Conversation UI, no category selection |
| `frontend/src/App.css` | Conversation styles |

## Tool set (18, covering brief sections A–O)

orders, bills, payments, customers, menu, reservations, tables, kitchen,
delivery, inventory, waste, reviews, revenue, comparison, business summary,
forecast, existing-ML insights, operational events.

Each tool declares its parameters. The orchestrator may only call a tool
with declared parameters. There is no code path from a question to a SQL
string.

## Flow

```
question (+ recent turns)
  → question_router: window + ranked domains + intent flags
  → tool selection (1..6 tools, bounded)
  → each tool: db → validated dict, or {"has_data": false, "limitation": "..."}
  → orchestrator computes every derived figure in Python
  → answer = conclusion / key numbers / observations / inference / recommendation / limitations
  → data_sources[] names the tools actually used
```

## Safety

* Every new route: `Depends(require_admin)`.
* Conversation context holds only the last few resolved windows and
  domains — no question text is persisted anywhere.
* No credential, hash, secret or SQL is ever placed in a tool payload.
* Customer AI routes are untouched.