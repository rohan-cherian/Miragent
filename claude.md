# Miragent workstream notes

**Latest:** W1-API-01 FastAPI service skeleton — **Complete**  
**Also complete:** W1-SRC-05 Zendesk emulator · W1-SRC-04 Shared plumbing

---

# W1-API-01 — FastAPI service skeleton

**Status:** Complete  
**Location:** `scout/service/`  
**Tests:** `tests/service/test_console_api.py` (5 tests passing)  
**Requires:** Postgres with `src_zendesk` (same as Zendesk emulator)

---

## What this work is

The **console API door** — app factory, DI, probes, live `/corpus/stats`, OpenAPI, CORS, and one error envelope. All future console endpoints (~15 over three weeks) build on this.

`/corpus/stats` powers **Scene 1**: live tickets / accounts / analysts / channels / date range from Postgres — never stubs.

---

## What was delivered

| Piece | Detail |
|--------|--------|
| App factory | `create_app()` in `scout/service/app.py` |
| DI | `DatabaseDep` / settings via FastAPI `Depends` + `app.state` |
| `GET /health` | Liveness — process up |
| `GET /ready` | Readiness — Postgres + `src_zendesk.tickets` present |
| `GET /corpus/stats` | Live aggregates from Postgres |
| OpenAPI | `/docs`, `/redoc`, `/openapi.json` |
| CORS | localhost:5173 / 3000 (configurable) |
| Error envelope | `{ "error": { "code", "message", "details" } }` everywhere |

### `/corpus/stats` mapping

| Field | Source |
|--------|--------|
| `tickets` | `COUNT(*)` `src_zendesk.tickets` |
| `accounts` | `COUNT(*)` `src_zendesk.organizations` |
| `analysts` | users with role `agent` or `admin` |
| `channels` | `COUNT(DISTINCT via_channel)` on tickets |
| `date_range` | min `created_at` → max `updated_at` |

---

## Where it lives

```
scout/service/
  __init__.py
  app.py        # create_app factory
  config.py     # ServiceSettings
  db.py         # Postgres wrapper
  deps.py       # DI
  errors.py     # consistent envelope
  corpus.py     # stats SQL
  routes.py     # /health /ready /corpus/stats

tests/service/test_console_api.py
```

---

## How to run

```powershell
docker compose -f docker-compose.zendesk-emulator.yml up -d
$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
poetry run uvicorn scout.service.app:create_app --factory --reload --port 8090
```

- Health: http://127.0.0.1:8090/health  
- Ready: http://127.0.0.1:8090/ready  
- Stats: http://127.0.0.1:8090/corpus/stats  
- Docs: http://127.0.0.1:8090/docs  

---

## Status

**W1-API-01 — FastAPI service skeleton: Complete**

---
---

# W1-SRC-05 — Zendesk emulator API

**Status:** Complete  
**Location:** `scout/emulators/zendesk/`  
**Tests:** `tests/emulators/test_zendesk_emulator.py` (20 tests passing)  
**Depends on:** `scout/shared/` (W1-SRC-04)

---

## What this work is

The **first vendor API emulator** — and the only one with a **write path**. It exposes a Zendesk-faithful HTTP surface so connectors can exercise incremental sync, sideloads, ticket read/update, webhooks, and real rate limiting without hitting production Zendesk.

Built on top of shared plumbing (`AuthStub`, `ChaosSwitch`, `EmulatorRateLimiter`, Zendesk error envelopes). No prior `scout/emulators/` package existed; this ticket created it.

**Data backend:** PostgreSQL ``src_zendesk`` only (live dump). No in-memory demo fallback when running the emulator. Unit tests may inject ``ZendeskStore`` via ``store=``.

---

## What was delivered

### 1. Incremental export with cursor pagination

`GET /api/v2/incremental/tickets/cursor` (also `.json`)

- First page: `?start_time=<unix>`
- Next pages: `?cursor=<opaque>`
- Response includes `tickets`, `after_cursor`, `after_url`, and **`end_of_stream`**
- Tickets ordered by **`generated_timestamp`** (then `id`) — same ordering real Zendesk uses for incremental export
- Stream terminates cleanly when `end_of_stream: true`

**Module:** `scout/emulators/zendesk/export.py`

### 2. Sideloads

`?include=users,organizations` on export and single-ticket GET returns related **users** and **organizations** in the same response so one call yields a complete picture.

### 3. Single ticket endpoint

`GET /api/v2/tickets/{id}` → `{ "ticket": { ... } }`  
Missing id → Zendesk-shaped **404** (`RecordNotFound`).

### 4. Ticket update endpoint (write-back)

`PUT /api/v2/tickets/{id}` with `{ "ticket": { ... } }`

- Updates mutable fields
- Bumps `updated_at` and **`generated_timestamp`** (system update, Zendesk-style)
- On Postgres backend, writes go to `src_zendesk.tickets`
- Write-back target for week-four remediation flows

### 5. Webhook emission with HMAC signing

On every successful ticket update the emulator:

- Builds a Zendesk-shaped event payload (`zen:event-type:ticket.*`)
- Signs: `base64(HMAC-SHA256(timestamp + body, secret))`
- Sets headers:
  - `X-Zendesk-Webhook-Signature`
  - `X-Zendesk-Webhook-Signature-Timestamp`
- Records deliveries in `store.emitted_webhooks` for the event listener next week

**Module:** `scout/emulators/zendesk/webhooks.py`  
Default test secret matches Zendesk’s documented test secret.

### 6. Account-wide rate limiting that depletes

All authenticated requests share one limiter key (`"account"`). When the budget is exhausted → genuine **HTTP 429** + **`Retry-After`** + Zendesk `APIRateLimitExceeded` body (via `EmulatorRateLimiter` + `build_error_body`).

Every request also runs:

1. `AuthStub` → 401 if no token  
2. `ChaosSwitch` → optional `?chaos=429|500|slow|partial`  
3. Account rate limit  

### 7. PostgreSQL only (live data)

The running emulator **requires** `ZENDESK_DATABASE_URL`. There is no demo/in-memory fallback.

- Reads tickets / users / organizations from schema **`src_zendesk`**
- `generated_timestamp` derived from `updated_at` (fallback `created_at`)
- PUT updates persist in Postgres
- `GET /health` reports `"backend": "postgres"`

```
docker compose -f docker-compose.zendesk-emulator.yml up -d
poetry run python scripts/load_zendesk_postgres.py
$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
poetry run uvicorn scout.emulators.zendesk.app:create_zendesk_app --factory --reload --port 8081
```

Postman hits return rows from Postgres (~6000 tickets from the dump).

---

## Where it lives

```
scout/emulators/
  __init__.py
  zendesk/
    __init__.py
    app.py              # FastAPI routes + shared gates
    base.py             # TicketStore protocol
    factory.py          # memory vs Postgres switch
    store.py            # In-memory store
    postgres_store.py   # Postgres src_zendesk store
    export.py           # Cursor incremental export
    webhooks.py         # HMAC sign / verify / emit

docker-compose.zendesk-emulator.yml
scripts/load_zendesk_postgres.py
schema/001_src_zendesk_schema.sql

tests/emulators/
  test_zendesk_emulator.py
```

---

## How to run

```bash
# Tests (inject in-memory store in fixtures — no Postgres required)
poetry run pytest tests/emulators/test_zendesk_emulator.py -v

# Emulator — live Postgres only
docker compose -f docker-compose.zendesk-emulator.yml up -d
poetry run python scripts/load_zendesk_postgres.py   # first time
$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
poetry run uvicorn scout.emulators.zendesk.app:create_zendesk_app --factory --reload --port 8081
```

Call with `Authorization: Bearer <any-token>` (or Basic). Missing credentials → Zendesk 401.  
Check backend: `GET http://localhost:8081/health` → `{"backend":"postgres"}`.

Starting without `ZENDESK_DATABASE_URL` raises an error (no demo data).

---

## Why this matters

| Benefit | Detail |
|---------|--------|
| Highest-value emulator | Only vendor with a write path for week-four write-back |
| Realistic sync loop | Cursor + `end_of_stream` + `generated_timestamp` matches production incremental export |
| One-call context | Sideloads return users/orgs with tickets |
| Event listener ready | HMAC-signed webhook outbox for next week’s consumer |
| Client-demo ready | Postgres backend serves dump data via the same API |
| Shared plumbing proven | First consumer of W1-SRC-04 — pattern for Jira / Entra / SFDC / ServiceNow / Okta |

---

## Status

**W1-SRC-05 — Zendesk emulator API: Complete** (including Postgres wiring)

---
---

# W1-SRC-04 — Shared Emulator Plumbing

**Status:** Complete  
**Location:** `scout/shared/`  
**Tests:** `tests/shared/` (93 tests passing)

---

## What this work is

A **shared foundation** in `scout/shared` that all six vendor API emulators reuse. Built **once**, so Zendesk, Jira, Entra, Salesforce, ServiceNow, and Okta don’t each reinvent pagination, rate limits, errors, auth, or chaos testing.

This ticket is **not** the emulators themselves — it is the common layer they plug into. W1-SRC-05 is the first consumer.

---

## What was delivered (5 pieces)

### 1. Rate limiting that behaves like a real API

Genuine **HTTP 429** + **`Retry-After`**. Not a fake flag inside a 200 body.

**Module:** `scout/shared/rate_limit.py`

### 2. Vendor-shaped error bodies

| Vendor | Example shape |
|--------|----------------|
| Salesforce | `[{ "message", "errorCode" }]` |
| Zendesk | `{ "error", "description" }` |
| Jira | `{ "errorMessages", "errors" }` |
| Entra | `{ "error": { "code", "message", "innerError" } }` |
| ServiceNow | `{ "error": { "message", "detail" }, "status": "failure" }` |
| Okta | `{ "errorCode", "errorSummary", ... }` |

**Module:** `scout/shared/errors.py`

### 3. Pagination in three real vendor styles

| Style | Vendor | How it works |
|--------|--------|--------------|
| Cursor | Zendesk | Opaque `after_cursor` / `page[after]` |
| Offset | Jira | `startAt` + `maxResults` + `total` |
| OData | Entra | `$skiptoken` / `@odata.nextLink` |

**Module:** `scout/shared/pagination.py`

### 4. Auth stubs

No token → **HTTP 401** + vendor envelope. Supports `Bearer`, `Basic`, Okta `SSWS`.

**Module:** `scout/shared/auth.py`

### 5. `?chaos=` switch

| Switch | What it does |
|--------|----------------|
| `?chaos=429` | Force rate-limit response |
| `?chaos=500` | Force server error |
| `?chaos=slow` | Delay the response |
| `?chaos=partial` | Short page that still says “more data” |

Off by default.

**Module:** `scout/shared/chaos.py`

---

## Where it lives

```
scout/shared/
  __init__.py
  rate_limit.py
  errors.py
  pagination.py
  auth.py
  chaos.py

tests/shared/
  test_rate_limit.py
  test_errors.py
  test_pagination.py
  test_auth.py
  test_chaos.py
```

---

## Status

**W1-SRC-04 — Shared emulator plumbing: Complete**  
**W1-SRC-05 — Zendesk emulator API: Complete**
