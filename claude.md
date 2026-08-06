# W1-SRC-04 — Shared Emulator Plumbing

**Status:** Complete  
**Location:** `scout/shared/`  
**Tests:** `tests/shared/` (93 tests passing)

---

## What this work is

We built a **shared foundation** in `scout/shared` that all six vendor API emulators will reuse. This is infrastructure built **once**, so Zendesk, Jira, Entra, Salesforce, ServiceNow, and Okta emulators don’t each reinvent pagination, rate limits, errors, auth, or chaos testing.

This ticket is **not** the emulators themselves — it is the common layer they will plug into.

---

## What was delivered (5 pieces)

### 1. Rate limiting that behaves like a real API

When a client exceeds the limit, the emulator returns a genuine **HTTP 429** with a real **`Retry-After`** header.

- Not a fake “rate limited” flag inside a success response
- Clients must wait and retry correctly — same as production APIs

**Module:** `scout/shared/rate_limit.py`

### 2. Vendor-shaped error bodies

Each vendor returns errors in its own format. We copied those shapes faithfully:

| Vendor | Example shape |
|--------|----------------|
| Salesforce | `[{ "message", "errorCode" }]` |
| Zendesk | `{ "error", "description" }` |
| Jira | `{ "errorMessages", "errors" }` |
| Entra | `{ "error": { "code", "message", "innerError" } }` |
| ServiceNow | `{ "error": { "message", "detail" }, "status": "failure" }` |
| Okta | `{ "errorCode", "errorSummary", ... }` |

This lets connector error-handling be tested against **realistic** responses.

**Module:** `scout/shared/errors.py`

### 3. Pagination in three real vendor styles

Vendors page differently; we support all three:

| Style | Vendor | How it works |
|-------|--------|--------------|
| Cursor | Zendesk | Opaque `after_cursor` / `page[after]` |
| Offset | Jira | `startAt` + `maxResults` + `total` |
| OData | Entra | `$skiptoken` / `@odata.nextLink` |

**Module:** `scout/shared/pagination.py`

### 4. Auth stubs

Requests with **no token** are rejected with **HTTP 401** and the correct vendor error body.

- Supports `Bearer`, `Basic`, and Okta `SSWS`
- Missing or empty credentials fail closed

**Module:** `scout/shared/auth.py`

### 5. `?chaos=` switch (on-demand fault injection)

For resilience testing, callers can opt in via query param:

| Switch | What it does |
|--------|----------------|
| `?chaos=429` | Force rate-limit response |
| `?chaos=500` | Force server error |
| `?chaos=slow` | Delay the response |
| `?chaos=partial` | Return a short page that still says “more data” |
| `?chaos=slow,partial` | Combine modes |

**Off by default** — normal requests are unaffected.

**Module:** `scout/shared/chaos.py`

---

## Where it lives

```
scout/shared/
  __init__.py       # Public exports
  rate_limit.py     # 429 + Retry-After
  errors.py         # Vendor error envelopes
  pagination.py     # Zendesk / Jira / Entra paging
  auth.py           # Reject missing tokens
  chaos.py          # ?chaos= fault injection

tests/shared/
  test_rate_limit.py
  test_errors.py
  test_pagination.py
  test_auth.py
  test_chaos.py
```

---

## Why this matters

| Benefit | Detail |
|---------|--------|
| Build once, reuse six times | Next emulator tickets consume this layer instead of duplicating logic |
| Realistic vendor behavior | Connectors can be tested against production-like HTTP, errors, and paging |
| Safer resilience testing | Chaos is explicit and opt-in via `?chaos=` |
| Clear contract | Auth failures, rate limits, and errors look like the real vendors |

---

## How emulators will use it (example)

```python
from scout.shared import (
    AuthStub,
    ChaosSwitch,
    EmulatorRateLimiter,
    Vendor,
    paginate_zendesk,
)

auth = AuthStub(Vendor.ZENDESK)
limiter = EmulatorRateLimiter(max_requests=60, window_seconds=60)
chaos = ChaosSwitch(Vendor.ZENDESK)

# 1. Reject missing token
if blocked := auth.enforce(request.headers):
    return blocked

# 2. Optional chaos injection
result = chaos.apply(request.query_params)
if result.response is not None:
    return result.response  # 429 or 500

# 3. Enforce real rate limits
if blocked := limiter.enforce(client_key):
    return blocked

# 4. Paginate in vendor style
return paginate_zendesk(
    tickets,
    after_cursor=request.query_params.get("page[after]"),
    force_partial=result.effects.partial,
)
```

---

## Status

**W1-SRC-04 — Shared emulator plumbing: Complete**

