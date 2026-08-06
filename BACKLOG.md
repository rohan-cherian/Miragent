# Miragent — Sprint Backlog & Decision Log

The single source of truth for what's been built, why decisions were made,
and what comes next. Updated at the close of each sprint.

---

## ✅ Completed Sprints

| Sprint | Capability | Key Files |
|--------|-----------|-----------|
| S01 | Project setup, FastAPI skeleton, Docker Compose (Neo4j, ClickHouse, Redis, Weaviate) | `docker-compose.yml`, `scout/api/app.py` |
| S02 | Data ingestion pipeline — connector → normalizer → graph writer | `scout/ingestion/` |
| S03 | Neo4j graph schema: Person, Account, Opportunity, Vendor nodes + OWNS/MANAGES/IN_ACCOUNT/OWNS_DEAL relationships | `scout/db/neo4j.py` |
| S04 | Revenue optimization workers: PipelineVelocity, ChurnPrediction, SalesCapacity, ExpansionRevenue | `scout/workers/pipeline_velocity.py` etc. |
| S05 | EBITDA optimization workers: SaasLicense, VendorNegotiation, HeadcountEfficiency, ProcessBottleneck, WorkingCapital, Sentiment | `scout/workers/saas_license.py` etc. |
| S06 | Full funnel intelligence: TamPenetration, MarketingFunnel, CrossSellIntelligence | `scout/workers/tam_penetration.py` etc. |
| S07 | Process mining: HireToRetire, IssueToResolution, LeadToCash, ProcureToPay, ApProcessing, LicenseManagement | `scout/workers/hire_to_retire.py` etc. |
| S08 | Executive memo + AI narrative: LLM analyst calls Claude API, graceful fallback when no key set | `scout/workers/analyst.py`, `scout/workers/llm_analyst.py` |
| S09 | Revenue agents: OutreachSequence, LeadEnrichment, MeetingPrep, RenewalWorkflow, ExpenseAudit | `scout/workers/outreach_sequence.py` etc. |
| S10 | Ops agents: Onboarding, Offboarding, CrossSellCampaign, PricingIntegrity, WorkforceWorker, EngagementIntelligence | `scout/workers/onboarding.py` etc. |
| S11 | Scout dashboard frontend: React + TypeScript + Tailwind, Vite build, React Router | `frontend/src/` |
| S12 | Polish & QA: error states, loading spinners, empty states, responsive layout | Various frontend files |
| S13 | Security: JWT auth, rate limiting (slowapi), audit logging to ClickHouse, CORS | `scout/api/routes/users.py`, `scout/db/clickhouse.py` |
| S14 | 31 enterprise connectors (mock + OAuth2 framework): Salesforce, Workday, NetSuite, HubSpot, 27 others | `scout/connectors/` |
| S15 | Multi-tenant user auth + API key management: register, login, `/me`, key CRUD | `scout/api/routes/users.py` |
| S16 | LLM narrative integration: Claude `claude-sonnet-4-5`, structured prompt, graceful fallback to template | `scout/workers/llm_analyst.py` |
| S17 | Rich mock data: 50+ persons, 30+ accounts, 25+ opportunities, 15+ vendors per scan | `scout/ingestion/mock_data.py` |
| S18 | Vendor Benchmark Intelligence: 59 SaaS tools with benchmark pricing, negotiation windows, potential savings | `scout/workers/vendor_benchmark.py`, `scout/connectors/vendor_benchmarks.py` |
| S19 | Live dashboard + Vendor UI + Auth management: VendorBenchmarks page, UserManagement page, Settings page | `frontend/src/pages/VendorBenchmarks.tsx` etc. |
| S20 | Agentic UI: Approvals inbox + Actions dashboard; Sidebar nav updated; lazy routes in App.tsx; v0.20.0 | `frontend/src/pages/Approvals.tsx`, `frontend/src/pages/Actions.tsx` |
| S45 | Fix seeded_client fixture collision: `test_clickhouse.py` fixture renamed `ch_seeded` to avoid conftest auto-skip | `tests/db/test_clickhouse.py` |
| S46 | Extended mock connector coverage: 28 connectors × 22 tests = 616 tests via parametrize | `tests/connectors/test_extended_mock_connectors.py` |
| S47 | OAuth2 + enrichment pure-logic tests: is_expired, build_auth_url, get_valid_token paths, Clearbit/ZoomInfo | `tests/connectors/test_oauth2_and_enrichment.py` |
| S48 | (same as S20 — frontend agentic UI sprint) | |
| S49 | ThresholdConfig wired into 12 workers; workforce.py + process_bottleneck.py helper threading fixed; Settings.tsx updated (v0.20.0, sprint list, worker count, Claude API) | `scout/workers/*.py`, `frontend/src/pages/Settings.tsx` |
| S50 | RenewalWorkflowWorker + EngagementIntelligenceWorker registered in threshold_registry + wired; BACKLOG.md created | `scout/workers/threshold_registry.py`, `scout/workers/renewal_workflow.py`, `scout/workers/engagement_intelligence.py` |
| S51 | Signal/Noise Intelligence UI: NoiseProfile + ThresholdProposal types, 5 API methods, Intelligence.tsx page (Worker Scores tab + Threshold Proposals tab), wired into Sidebar.tsx + App.tsx | `frontend/src/pages/Intelligence.tsx`, `frontend/src/types/index.ts`, `frontend/src/api/client.ts`, `frontend/src/components/Sidebar.tsx`, `frontend/src/App.tsx` |
| S52 | Deploy full stack — Fly.io backend, Neo4j Aura graph DB, Vercel frontend; SSH key auth, Redis made optional, git author fixed; fix EngagementIntelligenceWorker NameError (S50 regression); fix Insights severity case mismatch | `fly.toml`, `Dockerfile`, `frontend/vercel.json`, `scout/api/routes/health.py`, `scout/workers/engagement_intelligence.py`, `frontend/src/pages/Insights.tsx` |
| S53 | Complete Threshold Registry — all 32 workers now registered in threshold_registry.py with DEFAULTS + METADATA; all 15 newly-wired workers use ThresholdConfig.for_worker() — zero hardcoded numeric constants remaining | `scout/workers/threshold_registry.py`, `scout/workers/pricing_integrity.py`, `scout/workers/procure_to_pay.py`, `scout/workers/headcount_efficiency.py`, `scout/workers/onboarding.py`, `scout/workers/offboarding.py`, `scout/workers/vendor_negotiation.py`, `scout/workers/tam_penetration.py`, `scout/workers/marketing_funnel.py`, `scout/workers/cross_sell_campaign.py`, `scout/workers/cross_sell_intelligence.py`, `scout/workers/lead_enrichment.py`, `scout/workers/meeting_prep.py`, `scout/workers/outreach_sequence.py`, `scout/workers/sentiment.py`, `scout/workers/vendor.py` |
| S54 | Signal/Noise Admin API — seed baseline NoiseProfile rows for all 32 workers on first refresh; expand _RAISE_CANDIDATES to cover all workers; better refresh result message in Intelligence.tsx | `scout/engine/noise_scanner.py`, `frontend/src/pages/Intelligence.tsx`, `frontend/src/api/client.ts` |
| S55 | MFA (TOTP) — POST /mfa/setup|verify|disable, GET /mfa/status; two-step login flow (mfa_pending JWT); QR code generation; Settings.tsx MFA panel; pyotp + qrcode dependencies | `scout/api/routes/mfa.py`, `scout/db/models.py`, `scout/api/app.py`, `frontend/src/pages/Settings.tsx`, `frontend/src/api/client.ts` |

---

## 🔲 Queued

### Infrastructure / Deployment
- [x] Deploy to Fly.io (S52) — live at https://miragent.fly.dev
- [x] Neo4j Aura — connected, bolt URI wired into Fly.io secrets
- [x] Vercel frontend — live at https://miragent-frontend-*.vercel.app
- [ ] Version bump script: single source of truth for version number (currently duplicated in Sidebar.tsx and Settings.tsx)
- [ ] Neo4j Aura trial expires in ~14 days — decide: AuraDB Free tier or pay for Professional

### Live Connector Credentials
- [ ] Salesforce OAuth2 (connected app client_id + client_secret + instance_url)
- [ ] Workday ISU (tenant + username + password + WSDL endpoint)
- [ ] HubSpot Private App token
- [ ] NetSuite OAuth1 (account_id + consumer_key + token)
- These are external dependencies — code is ready, credentials are not

### Threshold Registry Completion
- [x] All 32 workers registered — DONE (S53)

### Signal/Noise Engine
- [x] Frontend UI built — `Intelligence.tsx`: Worker Scores tab (signal score bars) + Threshold Proposals tab (accept/reject cards) — **done S51**
- [ ] Admin API: `GET /admin/noise-profiles`, `POST /admin/noise-profiles/refresh`, `GET /admin/proposals`, `POST /admin/proposals/{id}/accept|reject`
- [ ] Signal score bars will show real trends once findings start being acted on / dismissed in production

### Worker Management Admin UI
- [ ] Frontend panel: list all 32 workers, enable/disable per tenant, adjust thresholds via sliders
- [ ] Use existing METADATA (labels, min/max, industry_low/industry_high) to power the slider ranges
- [ ] Eventually: upload a new worker Python file from the UI and hot-register it

### End-to-End Integration Test
- [ ] Test: scan → finding → action → approval → executor → audit log entry
- [ ] Currently the individual layers are tested but not the full pipeline in sequence
- [ ] Blocked by: Neo4j + executor credentials in CI

---

## 🗺️ Strategic Roadmap (future sprints)

### Security & Auth
- [x] **MFA (TOTP)** — done S55; pyotp + QR code; two-step login; Settings panel
- [ ] **SSO via SAML/OIDC** — Okta, Azure AD integration; required for enterprise IT; table stakes at Series B
- [ ] **SOC 2 Type II prep** — audit logging already in ClickHouse; need: access controls, pen test, vendor review

### Positioning
- **Tagline (board-facing):** "AI-Powered Virtual CIO Operating Partner for PE"
- **Tagline (portfolio CEO-facing):** "Your AI CIO — it watches everything and fixes what it finds"
- **Tagline (fund-facing):** "34 AI specialists running 24/7 across every portfolio company"

### Day 0 — Pre-Acquisition Due Diligence Mode
- [ ] New scan mode: `dd_scan` — point connectors at target company during last 2 weeks of diligence
- [ ] Output: structured DD risk memo (revenue risk, vendor exposure, org fragility, pricing integrity)
- [ ] Same engine, different output format — a PDF report instead of a live dashboard
- [ ] This is a stronger wedge than post-acquisition; PE firms pay for DD speed
- [ ] Key difference from current mode: read-only, no action layer, designed for 2-week engagements

### Operational Agents (new tier — beyond analytical workers)
Current workers are *analytical* (find problems). Operational agents *handle work*:
- [ ] **Customer Support Triage Agent** — reads incoming tickets, classifies severity, drafts response, routes
- [ ] **Meeting Prep Agent** — runs automatically 2h before each calendar event, pushes brief to Slack/email (MeetingPrepWorker is the analytical seed; this operationalizes it)
- [ ] **RFP Response Agent** — extracts questions from an incoming RFP, drafts 90% complete response
- [ ] **Board Report Agent** — pulls month's findings, formats into board-ready deck automatically
- [ ] **Onboarding Manager Agent** — triggered on new Workday hire: provisions systems, assigns buddy, schedules day-1 meetings
- [ ] **Incident Response Agent** — monitors alerts, pages correct on-call, drafts runbook steps
- Requires: event-driven trigger layer (webhooks or polling), Slack/Teams executor, calendar executor

### R&D / Software Factory Workers (new worker category)
Currently all workers analyze *business operations*. New category: *engineering operations*:
- [ ] **GitHubVelocityWorker** — PR cycle time, merge frequency, stale branches, bus factor
- [ ] **JiraHealthWorker** — sprint completion rate, backlog age, bug-to-feature ratio, estimation accuracy
- [ ] **DORAMetricsWorker** — deployment frequency, lead time, change failure rate, MTTR (the 4 gold-standard eng metrics)
- [ ] **TechDebtWorker** — dependency age, CVE exposure, test coverage, code complexity trends
- [ ] **EngineeringCapacityWorker** — headcount vs. output velocity, on-call burden, incident rate per engineer
- Requires: GitHub connector (API), Jira connector (REST API), Snyk/Dependabot integration
- Vista Equity Partners specifically benchmarks this across portfolio — strong enterprise buyer signal

### Technical Debt Maturity Score
- [ ] Single 0-100 "Engineering Health Score" aggregating DORA metrics, dep freshness, CVE exposure, test coverage, PR cycle time
- [ ] Pre-acquisition: technical debt = hidden capex required post-close; this is a DD risk factor
- [ ] Post-acquisition: improving score = faster product velocity = better NRR
- [ ] Display as a scored card alongside the existing executive memo

### System Discovery Scanner
- [ ] On first onboarding: auto-detect which systems a company uses (DNS, common SaaS URLs, public signals)
- [ ] Output: "We detected these 12 systems — connect them" checklist with one-click OAuth flows
- [ ] Add connectors: **Snowflake**, **Databricks**, **dbt**, **Looker**, **Tableau**, **Power BI** (analytics/BI layer)
- [ ] Add connectors: **Slack**, **Microsoft Teams**, **Google Workspace**, **Outlook** (communication layer)
- [ ] Connecting to analytics layer unlocks data quality workers, model drift detection, BI adoption analysis

### Deeper Findings — Alpha-Generating Intelligence
Current findings are surface-level (e.g., "customer likely to churn"). Deeper tier:
- [ ] **Onboarding Ramp Optimization** — time-to-first-deal for AEs vs. benchmark (3.5 months industry); time-to-first-commit for engineers; gap = $X/year productivity loss
- [ ] **Meeting Effectiveness** — calendar analysis: % meetings with no agenda, % with no follow-up, cost of recurring meetings per year (headcount × hours × loaded cost)
- [ ] **Attention Allocation** — are AEs filing IT tickets themselves? Are engineers attending too many status meetings? Revenue-generating employees doing admin work = hidden cost
- [ ] **Knowledge Concentration** — who is in the most meetings, most CC'd, most DM'd? Bottleneck detection; key-person departure risk
- [ ] **Communication Network Analysis** — graph of who talks to whom; islands = silos; over-connected nodes = key-person risk and organizational bottleneck
- Requires: Google Workspace / Outlook / Slack connectors

### Infrastructure (Production Scaling)
- Current: Fly.io (API) + Vercel (frontend) + Neo4j Aura + ClickHouse Cloud — valid through Series A
- Migration triggers: (a) customer requires data residency Fly.io doesn't serve, (b) SOC 2/FedRAMP/HIPAA requires hyperscaler certification
- When migrating: AWS is the default choice (most compliance certifications, largest managed service portfolio)
- Code is container-native — migration is one config change, not a rewrite

---

## 📋 Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-17 | Prioritized Actions.tsx (S48) over deployment | Frontend gap was the last demo-blocking item; deployment requires external infra setup |
| 2026-05-17 | Renamed seeded_client → ch_seeded in test_clickhouse.py (S45) | conftest auto-skip rule matched the fixture name, masking 13 valid ClickHouse tests |
| 2026-05-17 | Used dynamic import (importlib) for 28-connector test file (S46) | Single parametrized file cleaner than 28 test classes; coverage tool shows false negatives but all 616 tests pass |
| 2026-05-17 | ThresholdConfig uses module-level constants as fallbacks (S49) | Preserves backward compatibility — workers are correct even if registry lookup fails |
| 2026-05-17 | Threaded thresholds as parameters through helper methods in workforce.py (S49) | Helper methods are private; passing values explicitly is cleaner than re-calling ThresholdConfig inside helpers |
| 2026-05-17 | Avoided sed for bulk replacement (S50 lesson) | sed -i replaces module-level constant definitions too, breaking fallback references; use targeted Edit tool instead |
| 2026-05-17 | Used ActivitySquare icon for Intelligence nav item (S51) | Brain already used for Insights; ActivitySquare (pulse/signal shape) semantically matches signal/noise concept |
| 2026-05-17 | Made Redis optional in health check (S52) | Redis is only used for async job queuing — not on the critical path; Fly.io Redis add-on requires credit card; core functionality works without it |
| 2026-05-17 | All 32 workers use ThresholdConfig — zero hardcoded numeric constants remaining (S53) | Single source of truth in threshold_registry.py; per-tenant overrides stored in WorkerConfig DB table and merged at runtime |

---

## 🏗️ Architecture Notes (for cold-start reading)

**Where the intelligence logic lives:**
- `scout/workers/*.py` — 34 workers, each a `WorkerBase` subclass with `run(tenant_id) -> WorkerResult`
- `scout/workers/threshold_registry.py` — all configurable thresholds with defaults + metadata + per-tenant override support
- `scout/workers/analyst.py` — orchestrates all workers, passes findings to LLM
- `scout/workers/llm_analyst.py` — calls Claude API, generates 400-600 word executive memo

**Where the agentic action layer lives:**
- `scout/actions/playbook.py` — PlaybookEngine: maps action_type → risk tier (LOW/MEDIUM/HIGH/BLOCKED)
- `scout/actions/executors.py` — 3 executors (Salesforce, Workday, NetSuite), 13 action types, dry_run support
- `scout/api/routes/admin.py` — approval gate API, actions API, playbook config API

**Where the thresholds come from:**
- Written as expert hypotheses during development, sourced from general SaaS/PE domain knowledge
- `industry_low`/`industry_high` ranges in METADATA indicate benchmark context
- Per-tenant overrides stored in `WorkerConfig` DB table, merged at runtime via `ThresholdConfig.for_worker()`
- Signal/noise engine designed to validate hypotheses over time — not yet populated with real data

**What's blocked by Neo4j:**
- 218 tests are skipped when Neo4j is not running (controlled by conftest.py auto-skip on `seeded_driver`/`seeded_client` fixtures)
- All 28 mock connector tests (616 tests) and OAuth2/enrichment tests (59 tests) run without Neo4j
- ClickHouse tests (13 tests) run without Neo4j (fixture named `ch_seeded`, not caught by auto-skip)
