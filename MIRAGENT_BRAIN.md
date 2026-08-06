# MIRAGENT_BRAIN.md
> Shared strategy and state document between Opus (strategy) and Sonnet (implementation).
> Last strategy update: 2026-05-20
> Last build update: 2026-05-20 — Sprint 83 complete

---

## HOW THIS FILE WORKS

**Opus sessions:** Read the full file for context. Update sections marked `[OPUS OWNS]`. The user will paste the updated file back to save it, or edit directly.

**Sonnet sessions:** Read this file at the start of every session before touching any code. Update sections marked `[SONNET OWNS]` after completing work. Never override Opus-owned sections without explicit user instruction.

**User workflow:**
1. Open Opus session → paste this file as context → Opus revises strategy sections → save file back to repo
2. Open Sonnet session → Sonnet reads this file automatically → executes sprint → updates build state → commits

---

## STRATEGIC DIRECTION `[OPUS OWNS]`

### The Three Pillars + Foundation

Miragent is a PE operating platform built on three value propositions:

**Pillar 1 — Illuminate (Digital Twin)**
Instrument the full operations of a portfolio company. Capture not just entities (people, accounts, vendors) but *activities* — the actual flow of work through the business. Model the six canonical business processes: O2C, P2P, H2R, R2R, I2R, L2R. Every process event (InvoiceReceived, ThreeWayMatchFailed, TicketEscalated) becomes a timestamped, actor-linked node in the graph. Without this, Pillars 2 and 3 stay shallow.

**Pillar 2 — Advise (Deep Process Intelligence)**
Produce findings that a PE operating partner can take into a board meeting. Not threshold flags ("health score < 60") but quantified, benchmarked, root-cause analysis ("your DSO is 47 days vs. 31-day industry benchmark; root cause is 28% invoice error rate; fixing it frees $2.3M working capital"). Every finding must have: root cause chain, industry benchmark comparison, dollar impact, and recommended action.

**Pillar 3 — Automate (Autonomous Work Agents)**
Deploy trigger-activated agents that sit in work queues and process real work — not chatbots a human navigates to. Agents must: receive triggers from source systems (new ticket, new invoice, new hire), act with tool use (read/write to CRPs, ERPs, send emails), produce confidence scores that route to auto-execute / human-approve / human-handle, and report capacity metrics (FTE equivalent work automated).

**Foundation — Trust Layer**
Every feature is built through this lens: credential encryption (AES-256/KMS), PII detection and masking in logs and LLM prompts, field-level security, agent audit trail with rationale, human kill switch on all agents, SOC 2 Type II readiness, data lineage.

### The Single Pitch
> "Miragent instruments your operations, tells you exactly what's broken and what it costs, and then fixes it — either by recommending structural changes or by deploying autonomous agents that replace manual work. The average PE portfolio company finds $3-8M in operational improvements in the first 90 days."

---

## ARCHITECTURE DECISIONS `[BOTH CONTRIBUTE]`

| Decision | Choice | Rationale | Date |
|---|---|---|---|
| Graph DB | Neo4j | Relationship traversal 10-100x faster than SQL JOINs for graph patterns | Original |
| Relational DB | SQLite → PostgreSQL | SQLite for dev simplicity; swappable via DATABASE_URL | Original |
| LLM abstraction | Provider ABC pattern | Single .complete() interface; swap Anthropic/OpenAI/Gemini/Ollama via config | Sprint 78 |
| Connector pattern | ConnectorBase ABC | Mock/real swap via USE_MOCK_CONNECTORS; same interface for all 31 connectors | Original |
| Background jobs | threading.Thread daemon | No Celery/Redis dependency; keeps deployment simple | Sprint 78 |
| Frontend state | useState + useEffect per page | No Redux/Zustand; small bundle; pages independently understandable | Original |
| Agent routing | Confidence scoring | auto-execute (>85%), human-approve (60-85%), human-handle (<60%) | Planned Sprint 84+ |
| Process model | Canonical process ontology | O2C, P2P, H2R, R2R, I2R, L2R as first-class graph concepts | Planned Sprint 84+ |

### What We Will NOT Build (Anti-patterns / Rejected Approaches)
- ❌ LLM → Cypher (Text-to-SQL style): injection risk, non-deterministic, untestable. Use pre-written Cypher templates.
- ❌ Single database for everything: polyglot persistence is intentional. Neo4j for graph, SQLite for relational, ClickHouse for analytics.
- ❌ Celery/Redis for background jobs at this stage: over-engineering. Thread daemon is sufficient until we need distributed workers.
- ❌ Chatbot-style agents: agents must be trigger-activated, not click-activated. A human navigating to a page is not automation.
- ❌ Shallow threshold workers ("health score < 60"): every finding must have root cause, benchmark, and dollar impact.

---

## CURRENT BUILD STATE `[SONNET OWNS]`

### What Is Built and Tested
| Component | Status | Tests | Sprint |
|---|---|---|---|
| FastAPI app factory + middleware stack | ✅ Complete | — | 13 |
| 31 connectors (mock + real framework) | ✅ Complete | — | 12-38 |
| Salesforce live OAuth2 connector | ✅ Complete | 20 tests | 83 |
| Neo4j graph schema + ingestion | ✅ Complete | — | Original |
| 34 intelligence workers | ✅ Complete (shallow) | — | Various |
| LLM provider abstraction (4 providers) | ✅ Complete | — | 78 |
| InsightSnapshot persistence | ✅ Complete | 50 tests | 78 |
| Portfolio view (fund dashboard) | ✅ Complete | — | 78 |
| Insight scheduling (background daemon) | ✅ Complete | — | 78 |
| Copilot (NL Q&A + action loop) | ✅ Complete | 18 tests | 79, 82 |
| Multi-tenant access control | ✅ Complete | 24 tests | 80 |
| Monday email digest | ✅ Complete | 20 tests | 81 |
| Connector credential store + OAuth flow | ✅ Complete | 20 tests | 83 |
| 9 conversational agents (UI shells) | ✅ Built | — | 60-69 |
| Actions + Approvals + Execution log | ✅ Complete | — | Various |
| SSO (Okta, Azure AD, Google) | ✅ Complete | — | 58 |
| MFA (TOTP) | ✅ Complete | — | MFA |
| Security middleware (audit, rate limit, headers) | ✅ Complete | — | 13 |
| Knowledge Base (Weaviate) | ✅ Complete | — | 75 |
| Notification Center | ✅ Complete | — | 76 |
| Health Score | ✅ Complete | — | 77 |
| Board Report | ✅ Complete | — | 70 |
| Communications Analysis | ✅ Complete | — | 73 |
| Design Session | ✅ Complete | — | 72 |
| Mission Control | ✅ Complete | — | 62 |

**Total tests: 132 passing, 0 failures**
**Frontend: 30+ pages, lazy-loaded, TypeScript strict mode**
**Backend: 40+ API routes, FastAPI, fully documented at /docs**

### Known Weaknesses (Critical — Must Fix)
- ⚠️ Digital Twin captures entities but NOT process activities/transactions
- ⚠️ Workers produce shallow threshold flags, not quantified process intelligence
- ⚠️ 9 agents are conversational UI shells, not trigger-activated autonomous workers
- ⚠️ No industry benchmarks database — findings have no "good vs. bad" reference
- ⚠️ No cost impact quantification on findings
- ⚠️ No process event schema in Neo4j (O2C, P2P, H2R events)
- ⚠️ Connector credential encryption is plain JSON (needs AES-256 for production)

### Current Tech Versions
- Python 3.11, FastAPI 0.100+, SQLAlchemy 2.x
- Neo4j 5.x (Aura in production)
- React 18, TypeScript, Vite, Tailwind CSS, Lucide React 0.303
- reportlab (PDF generation)
- Deployed: Fly.io (backend), Vercel (frontend), Neo4j Aura (graph)

---

## NEXT SPRINT QUEUE `[OPUS PRIORITIZES, SONNET EXECUTES]`

Priority order as of 2026-05-20. Opus should reorder/add/remove as strategy evolves.

### Immediate Priority (Phase 1 — Deepen the Twin)
- [ ] **Sprint 84 — Process Event Schema**
  Add activity/transaction nodes to Neo4j: `ProcessEvent` node type with `event_type`, `occurred_at`, `actor_id`, `system_source`, `process_lane` (O2C/P2P/H2R/I2R/L2R/R2R), `duration_seconds`, `outcome`, `metadata`. Update connector ingestion to pull transactional data (Salesforce call logs, NetSuite invoice events, Zendesk ticket transitions, Workday workflow approvals). This is the foundation everything else depends on.

- [ ] **Sprint 85 — Canonical Process Ontology**
  Model the six business processes as first-class graph concepts. Define process lane nodes, event sequences, bottleneck detection. Graph queries that reconstruct actual process flows from event sequences.

- [ ] **Sprint 86 — Industry Benchmarks Database**
  SQLite table of industry benchmark metrics by process and sector (e.g., DSO by industry, O2C cycle time, first-call resolution rate, cost-per-hire). Seeded with realistic data. Used by all deep process analyzers to contextualize findings.

### Phase 2 — Deepen the Intelligence
- [ ] **Sprint 87 — Deep Process Analyzers (replace shallow workers)**
  Replace/augment 34 shallow workers with deep process analyzers: Invoice Matching Analyzer, AR Aging Analyzer, Sales Activity Analyzer, Procure-to-Pay Analyzer, Headcount Efficiency Analyzer, Ticket Resolution Analyzer. Each produces: root cause chain, benchmark comparison, dollar impact, recommended action.

- [ ] **Sprint 88 — Cost Impact Calculator**
  Attach dollar values to every finding automatically. Labour cost model (fully-loaded cost per FTE by function), working capital impact model (DSO gap × revenue × cost of capital), efficiency gap model (cycle time delta × volume × labour cost).

### Phase 3 — Real Autonomous Agents
- [ ] **Sprint 89 — Work Queue Infrastructure**
  Inbound trigger system (webhooks from source systems), agent work queues (SQLite `agent_work_items` table), confidence scoring and routing logic (auto/approve/human), capacity tracking dashboard (FTE equivalent automated).

- [ ] **Sprint 90 — Invoice Processing Agent** (first real autonomous agent)
  Trigger: new invoice arrives. Actions: extract data, match to PO, route exceptions. Tool use: read from AP system, post to ERP, send notification. Confidence routing. FTE equivalent tracking.

- [ ] **Sprint 91 — AR Dunning Agent**
  Trigger: invoice past due date. Actions: send dunning email sequence, track responses, escalate to collections. Replaces manual AR follow-up.

- [ ] **Sprint 92 — Customer Issue Resolution Agent**
  Trigger: new ticket in Zendesk/Salesforce. Actions: classify, search KB, draft resolution, send or escalate. The 20 → 5 headcount reduction example.

### Phase 4 — Trust Layer (runs in parallel)
- [ ] **Sprint 93 — Credential Encryption**
  AES-256 encryption for ConnectorCredentialStore.auth_data. KMS integration design for production. PII detection and masking in audit logs and LLM prompts.

- [ ] **Sprint 94 — Field-Level Security**
  Role-based field visibility (salary data, board findings only visible to specific roles). Data residency controls. SOC 2 Type II audit completion.

---

## OPEN QUESTIONS `[EITHER CAN ADD]`

- [ ] **Pricing model:** How does Miragent charge? Per portfolio company per month? Per FTE automated? Per finding actioned? This affects which metrics we surface and how we report value.
- [ ] **Agent tool registry scope:** What systems can agents actually write to in v1? Salesforce and Zendesk seem safest. NetSuite and Workday have higher risk. Need clear boundaries.
- [ ] **Benchmarks data source:** Build benchmarks database manually (curated from public sources) or integrate a third-party benchmarks API? Manual gives us control; API gives us freshness.
- [ ] **Process event ingestion frequency:** Real-time webhooks (complex) or batch pull every 15 minutes (simpler)? Batch is sufficient for most use cases initially.
- [ ] **Multi-org vs. single-org deployment:** Is Miragent deployed once per PE firm, or is it a SaaS with all PE firms on one instance? This has major implications for data isolation and deployment architecture.

---

## QUALITY STANDARDS `[OPUS SETS]`

Standards that apply to all implementation work. Sonnet must not compromise on these.

### Code
- Every new API route has tests before the sprint is closed
- Tests use in-memory SQLite, never a shared test database
- No new external package dependencies without explicit discussion
- TypeScript strict mode — no `any` types
- Read every file before editing it

### Intelligence / Findings
- Every finding must have: title, description, severity, root cause, dollar impact (when quantifiable), recommended action
- No finding is "interesting" without being actionable
- All dollar impacts must be derived from actual data in the graph, not estimates

### Agents
- No agent is "built" unless it has: trigger mechanism, confidence scoring, human escalation path, action audit trail, and FTE equivalent tracking
- Conversational UI wrappers around agents are not autonomous agents

### Security
- No credentials in logs, ever
- No PII in LLM prompts without explicit masking
- Every autonomous agent action logged with: actor (agent name), action taken, inputs, outputs, confidence score, timestamp
- Every agent has a kill switch (enabled=False in config disables it completely)

---

*This file is the source of truth for Miragent's direction. When in doubt, refer here.*
