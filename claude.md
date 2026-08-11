# Miragent workstream notes

**Latest:** W1-PLT-06 Observability baseline — **Complete**  
**Complete stack:** W1-PLT-06 · W1-CON-01 · W1-API-01 · W1-SRC-05 · W1-SRC-04

---

## How the pieces fit together

```
Browser / Postman
   │
   ├─ :8080  Console UI (W1-CON-01)  ──/api/*──►  :8090 Console API (W1-API-01)
   │                                                    │
   ├─ :5173  Console Vite (dev)     ──/api/*──►        │
   │                                                    ▼
   └─ :8081  Zendesk emulator (W1-SRC-05) ────────► Postgres :5433
                                                         │
                                                         └─ schema src_zendesk
                                                            (live dump data)

   :16686 Jaeger UI  ◄── OTLP :4318 ──  Console API (+ emulator) traces
```

| Port | Service | Ticket |
|------|---------|--------|
| **5433** | Postgres (`src_zendesk`) | shared data |
| **8081** | Zendesk emulator | W1-SRC-05 |
| **8090** | Console FastAPI | W1-API-01 |
| **8080** | Console UI (compose/nginx) | W1-CON-01 |
| **5173** | Console UI (Vite dev) | W1-CON-01 |
| **16686** | Jaeger UI (trace viewer) | W1-PLT-06 |
| **4318** | OTLP HTTP collector | W1-PLT-06 |

**Keep ports separate** — emulator ≠ console API. They share Postgres only.

**Compose files:**
- `docker-compose.zendesk-emulator.yml` — Postgres only (emulator DSN host port 5433)
- `docker-compose.console.yml` — Jaeger + Postgres + console API + console UI

---
---

# W1-PLT-06 — Observability baseline

**Status:** Complete  
**Location:** `scout/observability/`  
**Tests:** `tests/observability/test_observability.py` (5 tests passing)  
**Depends on:** W1-API-01 FastAPI skeleton; Postgres with `src_zendesk`  
**Done when:** one `trace_id` follows a ticket from ingest → agents → console and is visible in Jaeger

---

## What this work is

Structured JSON logging + OpenTelemetry tracing with **`run_id` and `trace_id` propagated end-to-end**. Week-three debugging and the locked “explainability from day one” decision both depend on this — not a week-four bolt-on.

---

## What was delivered

| Piece | Detail |
|--------|--------|
| JSON logging | One JSON object per line; includes `run_id` / `trace_id` / `ticket_id` when bound |
| Context | `contextvars` bind for the request (`scout/observability/context.py`) |
| OTel tracing | TracerProvider → OTLP HTTP (`OTEL_EXPORTER_OTLP_ENDPOINT`, default `:4318`) |
| Middleware | ASGI: accept `X-Run-Id` / `X-Ticket-Id`; echo `X-Run-Id` / `X-Trace-Id` / `X-Ticket-Id` |
| Journey path | `GET /tickets/{id}/journey` — ingest → stub agents → console payload, one shared trace |
| Jaeger | `jaegertracing/all-in-one` in `docker-compose.console.yml` (UI `:16686`) |
| Emulator | Same middleware + tracing on Zendesk emulator for ingest-side correlation |

### Journey spans (one `trace_id`)

```
ticket.journey
  ├─ ticket.ingest
  ├─ agent.context
  ├─ agent.recommend
  └─ console.response
```

### Headers / body

| Field | Where |
|--------|--------|
| `X-Run-Id` | Request (optional) + response |
| `X-Trace-Id` | Response (32-char hex) |
| `X-Ticket-Id` | Request (optional) + response |
| `run_id` / `trace_id` | Journey JSON body (console-visible) |

---

## Where it lives

```
scout/observability/
  __init__.py
  context.py      # run_id / trace_id / ticket_id contextvars
  logging.py      # JsonFormatter + configure_json_logging
  tracing.py      # init_tracing, start_span, instrument_fastapi
  middleware.py   # ObservabilityMiddleware (ASGI)

scout/service/
  journey.py      # ingest → agents → console demo path
  routes.py       # GET /tickets/{ticket_id}/journey
  app.py          # wires logging + OTel + middleware

tests/observability/test_observability.py
docker-compose.console.yml   # + jaeger service
Dockerfile.api               # + otel packages + observability copy
```

---

## How to verify

```powershell
# Jaeger + Postgres (or full console stack)
docker compose -f docker-compose.console.yml up -d jaeger postgres

# Console API pointing at Jaeger OTLP
$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
$env:OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"
$env:OTEL_SERVICE_NAME="miragent-console-api"
poetry run uvicorn scout.service.app:create_app --factory --reload --port 8090

# Pick a live ticket id, then:
# GET http://localhost:8090/tickets/<id>/journey
# Headers: X-Run-Id: demo-run-001
# Open http://localhost:16686 → service miragent-console-api → find that trace_id
```

```powershell
poetry run pytest tests/observability tests/service -v
```

---

## Status

**W1-PLT-06 — Observability baseline: Complete**

---
---

# W1-CON-01 — Console shell

**Status:** Complete  
**Location:** `console/` (separate from Miragent CIO `frontend/`)  
**Stack:** React 18 + Vite + Tailwind · **demo-grade** (explicit)  
**Compose:** `docker-compose.console.yml`  
**Depends on:** W1-API-01 FastAPI skeleton (for `/api` proxy)

---

## What this work is

The **container for all twelve demo screens** across eight scenes. Layout, routing, auth stub, API client, and design tokens are settled now so week three can ship five screens in five days without fighting plumbing.

**Demo-grade, not production-grade:** looks considered, no broken states. No design system, no component library, no settings page. Polish hours this week belong to the intelligence layer later.

---

## What was delivered

| Piece | Detail |
|--------|--------|
| Layout | Sidebar + mobile nav — `src/layout/ShellLayout.tsx` |
| Routing | 12 navigable routes (empty placeholders, intentional) |
| Auth stub | `/login` — any email/password; Bearer token in `localStorage` |
| API client | `src/api/client.ts` — `/health`, `/ready`, `/corpus/stats` + error envelope parsing |
| Design tokens | CSS variables in `src/index.css` mapped into Tailwind |
| Compose serve | nginx on **:8080**, proxies `/api` → FastAPI `:8090` |

### Twelve routes (empty shells)

| Route | Screen | Scene |
|--------|--------|--------|
| `/connections` | Connections | Scene 1 |
| `/corpus` | Corpus dashboard | Scene 1 |
| `/ticket-360` | Ticket 360 | Scene 2 |
| `/context` | Context & citations | Scene 3 |
| `/explainers` | Explainers | Scene 3 |
| `/recommendation` | Analyst recommendation | Scene 4 |
| `/call-player` | Call player | Scene 5 |
| `/approvals` | Approval queue | Scene 6 |
| `/audit` | Audit viewer | Scene 7 |
| `/kb-review` | KB review | Scene 7 |
| `/digest` | Weekly digest | Scene 8 |
| `/home` | Overview | Shell |

Default after login: `/corpus`.

---

## Where it lives

```
console/
  package.json
  vite.config.ts          # /api → :8090 proxy in dev
  tailwind.config.js
  Dockerfile              # build + nginx
  nginx.conf              # SPA + /api proxy to api:8090
  src/
    main.tsx
    App.tsx               # routes
    index.css             # design tokens
    nav.ts                # sidebar items
    api/client.ts
    auth/AuthContext.tsx
    auth/RequireAuth.tsx
    layout/ShellLayout.tsx
    pages/LoginPage.tsx
    pages/EmptyScreen.tsx
    pages/screens.tsx     # twelve placeholders

docker-compose.console.yml
Dockerfile.api            # slim image for scout.service
```

---

## How to run

**Dev (hot reload):**
```powershell
# Terminal A — console API (needs Postgres on 5433)
$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
poetry run uvicorn scout.service.app:create_app --factory --reload --port 8090

# Terminal B — console UI
cd console
npm install
npm run dev
# http://localhost:5173
```

**Compose (build + serve):**
```powershell
docker compose -f docker-compose.console.yml up -d --build
# Console  http://localhost:8080
# API      http://localhost:8090
```

Sign in with any email/password on `/login`, then navigate the sidebar.

---

## Status

**W1-CON-01 — Console shell: Complete**

---
---

# W1-API-01 — FastAPI service skeleton

**Status:** Complete  
**Location:** `scout/service/`  
**Tests:** `tests/service/test_console_api.py` (5 tests passing)  
**Requires:** Postgres with `src_zendesk` (same DB as Zendesk emulator)  
**Consumed by:** W1-CON-01 console (`/api` → this service)

---

## What this work is

The **single door** between backend work and everything the console shows. App factory, DI, probes, live `/corpus/stats`, OpenAPI, CORS, and one error envelope. ~Fifteen endpoints land on this skeleton over the next three weeks.

`/corpus/stats` powers **Scene 1**: live tickets / accounts / analysts / channels / date range — never stubs. First thing on screen in the demo.

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
| CORS | `:5173`, `:3000`, `:8080` (console) |
| Error envelope | `{ "error": { "code", "message", "details" } }` on every failure |

### `/corpus/stats` mapping

| Field | Source |
|--------|--------|
| `tickets` | `COUNT(*)` `src_zendesk.tickets` |
| `accounts` | `COUNT(*)` `src_zendesk.organizations` |
| `analysts` | users with role `agent` or `admin` |
| `channels` | `COUNT(DISTINCT via_channel)` on tickets |
| `date_range` | min `created_at` → max `updated_at` |

Typical live numbers from the dump: ~6000 tickets · ~1200 accounts · ~240 analysts · ~4 channels.

---

## Where it lives

```
scout/service/
  __init__.py
  app.py        # create_app factory
  config.py     # ServiceSettings (API_DATABASE_URL / ZENDESK_DATABASE_URL)
  db.py         # Postgres wrapper
  deps.py       # DI
  errors.py     # consistent envelope
  corpus.py     # stats SQL
  routes.py     # /health /ready /corpus/stats

tests/service/test_console_api.py
Dockerfile.api
```

---

## How to run

```powershell
docker compose -f docker-compose.zendesk-emulator.yml up -d
# first time only:
poetry run python scripts/load_zendesk_postgres.py

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
**Port:** **8081** (keep separate from console API :8090)

---

## What this work is

The **first vendor API emulator** — and the only one with a **write path**. Zendesk-faithful HTTP so connectors can exercise incremental sync, sideloads, ticket read/update, webhooks, and real rate limiting without hitting production Zendesk.

Built on shared plumbing (`AuthStub`, `ChaosSwitch`, `EmulatorRateLimiter`, Zendesk error envelopes).

**Data backend:** PostgreSQL `src_zendesk` only (live dump). No in-memory demo fallback when running. Unit tests may inject `ZendeskStore` via `store=`.

---

## What was delivered

### 1. Incremental export with cursor pagination

`GET /api/v2/incremental/tickets/cursor`

- First page: `?start_time=<unix>`
- Next pages: `?cursor=<opaque>` (use `after_cursor` from prior response)
- Response: `tickets`, `after_cursor`, `after_url`, **`end_of_stream`**
- Ordered by **`generated_timestamp`** (then `id`)
- Ends cleanly when `end_of_stream: true`

### 2. Sideloads

`?include=users,organizations` on export / single ticket — related users and orgs in the same call.

### 3. Single ticket

`GET /api/v2/tickets/{id}` → `{ "ticket": { … } }` · missing → Zendesk 404 `RecordNotFound`

### 4. Ticket update (write-back)

`PUT /api/v2/tickets/{id}` with `{ "ticket": { … } }`  
Persists to Postgres · bumps `generated_timestamp` · emits HMAC webhook.

### 5. Webhook emission with HMAC signing

`base64(HMAC-SHA256(timestamp + body, secret))`  
Headers: `X-Zendesk-Webhook-Signature`, `X-Zendesk-Webhook-Signature-Timestamp`  
Recorded in `store.emitted_webhooks` for next week’s event listener.

### 6. Account-wide rate limiting

Shared key `"account"` → real **HTTP 429** + **`Retry-After`** + Zendesk envelope when depleted.

Every request: **AuthStub → ChaosSwitch → EmulatorRateLimiter → handler**.

### 7. PostgreSQL only

Requires `ZENDESK_DATABASE_URL`.  
`GET /health` → `"backend": "postgres"`.

---

## Where it lives

```
scout/emulators/zendesk/
  app.py · base.py · factory.py · store.py · postgres_store.py
  export.py · webhooks.py

docker-compose.zendesk-emulator.yml
scripts/load_zendesk_postgres.py
schema/001_src_zendesk_schema.sql
tests/emulators/test_zendesk_emulator.py
```

---

## How to run

```powershell
docker compose -f docker-compose.zendesk-emulator.yml up -d
poetry run python scripts/load_zendesk_postgres.py   # first time only

$env:ZENDESK_DATABASE_URL="postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
poetry run uvicorn scout.emulators.zendesk.app:create_zendesk_app --factory --reload --port 8081
```

Auth header: `Authorization: Bearer test-token`  
Docs: http://127.0.0.1:8081/docs  
Pagination demo:  
`GET /api/v2/incremental/tickets/cursor?start_time=0&per_page=10`  
then `?cursor=<after_cursor>&per_page=10` until `end_of_stream: true`.

---

## Status

**W1-SRC-05 — Zendesk emulator API: Complete**

---
---

# W1-SRC-04 — Shared emulator plumbing

**Status:** Complete  
**Location:** `scout/shared/`  
**Tests:** `tests/shared/` (93 tests passing)  
**Consumed by:** W1-SRC-05 (and future Jira / Entra / SFDC / ServiceNow / Okta emulators)

---

## What this work is

Shared foundation so six vendor emulators don’t reinvent pagination, rate limits, errors, auth, or chaos. **Not** the emulators themselves — the common layer they plug into.

---

## What was delivered (5 pieces)

### 1. Rate limiting that actually bites

Genuine **HTTP 429** + **`Retry-After`**. Not a flag inside a 200 body.  
**Module:** `scout/shared/rate_limit.py`

### 2. Vendor-shaped error envelopes

| Vendor | Shape |
|--------|--------|
| Salesforce | `[{ "message", "errorCode" }]` |
| Zendesk | `{ "error", "description" }` |
| Jira | `{ "errorMessages", "errors" }` |
| Entra | `{ "error": { "code", "message", "innerError" } }` |
| ServiceNow | `{ "error": { "message", "detail" }, "status": "failure" }` |
| Okta | `{ "errorCode", "errorSummary", … }` |

**Module:** `scout/shared/errors.py`

### 3. Pagination — three real styles

| Style | Vendor | Mechanism |
|--------|--------|-----------|
| Cursor | Zendesk | opaque `after_cursor` / `page[after]` |
| Offset | Jira | `startAt` + `maxResults` + `total` |
| OData | Entra | `$skiptoken` / `@odata.nextLink` |

**Module:** `scout/shared/pagination.py`

### 4. Auth stubs

No token → **HTTP 401** + vendor envelope. Schemes: `Bearer`, `Basic`, Okta `SSWS`.  
**Module:** `scout/shared/auth.py`

### 5. `?chaos=` switch (opt-in)

| Switch | Effect |
|--------|--------|
| `?chaos=429` | Force rate-limit response |
| `?chaos=500` | Force server error |
| `?chaos=slow` | Delay response |
| `?chaos=partial` | Short page that still says more data |

Off by default.  
**Module:** `scout/shared/chaos.py`

---

## Where it lives

```
scout/shared/
  __init__.py · rate_limit.py · errors.py · pagination.py · auth.py · chaos.py

tests/shared/
  test_rate_limit.py · test_errors.py · test_pagination.py · test_auth.py · test_chaos.py
```

---

## Status

**W1-SRC-04 — Shared emulator plumbing: Complete**

---
---

# Overall status

| Ticket | Deliverable | Status |
|--------|-------------|--------|
| **W1-SRC-04** | Shared emulator plumbing | Complete |
| **W1-SRC-05** | Zendesk emulator API (+ Postgres) | Complete |
| **W1-API-01** | FastAPI console skeleton | Complete |
| **W1-CON-01** | Console shell (React/Vite/Tailwind) | Complete |
| **W1-PLT-06** | Observability baseline (JSON logs + OTel + Jaeger) | Complete |

**Next (expected):** fill console screens · more console API endpoints · event listener for HMAC webhooks · remaining vendor emulators · week-four write-back.
