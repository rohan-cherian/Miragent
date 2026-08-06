# Miragent

**Agentic CIO in a Box** — cross-system operational intelligence for PE-backed mid-market companies.

Miragent connects to Salesforce, Workday, and NetSuite, builds a unified knowledge graph, runs 34 intelligence workers to surface operational risks, and autonomously remediates them within configurable guardrails. It is not a dashboard. It is not a bot. It is an operating partner that runs 24/7.

---

## What it does

| Layer | What happens |
|---|---|
| **Ingest** | 31 connectors pull data from CRM, HRIS, ERP, and finance systems |
| **Graph** | Neo4j digital twin unifies Person → Account → Opportunity → Vendor relationships |
| **Analyze** | 34 workers scan for revenue risk, EBITDA leaks, process bottlenecks, and org health signals |
| **Narrate** | Claude AI synthesizes findings into a 400–600 word executive memo |
| **Act** | Playbook engine maps findings to typed remediation actions with risk tiers (LOW / MEDIUM / HIGH / BLOCKED) |
| **Approve** | Approval gate holds HIGH-risk actions for human review before execution |
| **Execute** | Typed executors write back to Salesforce, Workday, and NetSuite with full audit trail |
| **Learn** | Signal/noise engine tracks acted vs. dismissed findings and proposes threshold recalibrations |

---

## Intelligence workers (34 total)

**Revenue** — PipelineVelocity, ChurnPrediction, SalesCapacity, ExpansionRevenue, TamPenetration, MarketingFunnel, CrossSellIntelligence

**EBITDA** — SaasLicense, VendorNegotiation, VendorBenchmark, HeadcountEfficiency, ProcessBottleneck, WorkingCapital, Sentiment

**Process mining** — HireToRetire, IssueToResolution, LeadToCash, ProcureToPay, ApProcessing, LicenseManagement

**Revenue agents** — OutreachSequence, LeadEnrichment, MeetingPrep, RenewalWorkflow, ExpenseAudit

**Ops agents** — Onboarding, Offboarding, CrossSellCampaign, PricingIntegrity, Workforce, EngagementIntelligence

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, Python 3.11 |
| Graph DB | Neo4j |
| Relational DB | SQLite (dev) / PostgreSQL (prod) |
| Analytics DB | ClickHouse |
| Vector DB | Weaviate |
| Cache / Queue | Redis |
| AI | Anthropic Claude (`claude-sonnet-4-5`) |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Auth | JWT + API key management |
| Infra | Docker Compose (dev), Helm + Terraform ECS (prod) |

---

## Frontend pages

| Page | What it shows |
|---|---|
| Dashboard | Live scan status, top findings, critical/high counts |
| Insights | AI-generated executive memo + per-worker findings |
| Vendor Benchmarks | 59 SaaS tools benchmarked against market rates, negotiation windows |
| Scans | Trigger and monitor intelligence scans |
| Workers | Per-worker finding breakdown |
| Approvals | Approval inbox for HIGH-risk remediation actions |
| Actions | Full remediation action dashboard with complete/defer/execute |
| Intelligence | Signal/noise scores per worker + threshold proposal review |
| User Management | Multi-tenant user + API key management |
| Settings | Platform configuration, Claude API, threshold registry |

---

## Local development

### Prerequisites
- Docker + Docker Compose
- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Node.js 18+

### Start the data stack

```bash
docker compose up -d
```

This starts Neo4j, ClickHouse, Redis, and Weaviate.

### Backend

```bash
# Install dependencies
poetry install

# Copy and configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY for AI narrative (optional, falls back gracefully)

# Run the API
poetry run uvicorn scout.api.app:app --reload

# Run tests
poetry run pytest
```

API is available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend is available at `http://localhost:5173`. It proxies `/api` to the backend.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | JWT signing secret (generate with `openssl rand -hex 32`) |
| `NEO4J_URI` | Yes | Neo4j bolt URI (e.g. `bolt://localhost:7687`) |
| `NEO4J_PASSWORD` | Yes | Neo4j password |
| `CLICKHOUSE_HOST` | Yes | ClickHouse host |
| `ANTHROPIC_API_KEY` | No | Claude API key — enables AI narrative; falls back to template without it |
| `DATABASE_URL` | No | PostgreSQL URL for prod (uses SQLite by default) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│         (Dashboard · Insights · Actions · ...)          │
└────────────────────────┬────────────────────────────────┘
                         │ REST API
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI (scout/api/)                    │
│     Auth · Rate limiting · Audit log · CORS             │
└──────┬──────────────────┬──────────────────┬────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼───────┐  ┌──────▼──────────┐
│  Neo4j      │  │  34 Workers    │  │  Action Layer   │
│  Graph DB   │  │  (scout/       │  │  Playbook +     │
│  Digital    │  │   workers/)    │  │  Executors +    │
│  Twin       │  │               │  │  Approval Gate  │
└─────────────┘  └────────┬───────┘  └─────────────────┘
                          │
                 ┌────────▼───────┐
                 │  Claude API    │
                 │  Executive     │
                 │  Memo          │
                 └────────────────┘
```

---

## Connectors (31)

Salesforce · Workday · NetSuite · HubSpot · SAP · Oracle ERP · Dynamics 365 · Dynamics CRM · Dynamics Finance · ADP · Rippling · Gusto · BambooHR · UKG · Okta · Azure AD · JumpCloud · QuickBooks · Sage Intacct · Acumatica · Bill.com · Coupa · Brex · Ramp · Concur · Jira · ServiceNow · Freshservice · Zendesk · Pipedrive · Google Workspace

All connectors ship with mock adapters for development. OAuth2 framework included for live credential integration.

---

## Deployment

Helm chart and Terraform ECS modules are in `infra/`. See `infra/helm/` and `infra/terraform/`.

Required env vars for production: `SECRET_KEY`, `NEO4J_URI`, `NEO4J_PASSWORD`, `CLICKHOUSE_HOST`, `ANTHROPIC_API_KEY`

---

## Sprint history

51 development sprints from graph schema through Signal/Noise Intelligence UI. Full sprint log, decision log, and architecture notes in [BACKLOG.md](BACKLOG.md).

---

*Built with [Claude Code](https://claude.ai/claude-code)*
