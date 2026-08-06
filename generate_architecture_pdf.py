"""
Miragent Technical Architecture PDF Generator
Produces a print-ready US Letter PDF using reportlab Platypus.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame
from copy import deepcopy
import os

# ── Colors ──────────────────────────────────────────────────────────────────
NAVY      = HexColor('#1B2A4A')
GREEN     = HexColor('#2ECC71')
LIGHTGRAY = HexColor('#F4F6F9')
MIDGRAY   = HexColor('#CBD2DC')
WHITE     = white
DARKTEXT  = HexColor('#1A1A2E')

# ── Page geometry ────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter          # 612 × 792 pt
MARGIN = 0.75 * inch             # 54 pt
CONTENT_W = PAGE_W - 2 * MARGIN

OUTPUT_PATH = "/Users/shahriarrafimayeri/Downloads/Miragent_Technical_Architecture.pdf"

# ── Footer canvas ────────────────────────────────────────────────────────────
class PageNumCanvas(canvas.Canvas):
    """Canvas that adds a footer with page number on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(self._pageNumber, total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_footer(self, page_num, total):
        self.saveState()
        # Thin separator line
        self.setStrokeColor(MIDGRAY)
        self.setLineWidth(0.5)
        self.line(MARGIN, 36, PAGE_W - MARGIN, 36)
        # Footer text
        self.setFont("Helvetica", 8)
        self.setFillColor(HexColor('#6B7A99'))
        text = f"Miragent Technical Architecture  |  Page {page_num}  |  Confidential"
        self.drawCentredString(PAGE_W / 2, 22, text)
        self.restoreState()


# ── Styles ───────────────────────────────────────────────────────────────────
base_styles = getSampleStyleSheet()

def make_style(name, parent_name='Normal', **kwargs):
    parent = base_styles[parent_name]
    return ParagraphStyle(name=name, parent=parent, **kwargs)

S_COVER_TITLE = make_style('CoverTitle',
    fontName='Helvetica-Bold', fontSize=52, textColor=NAVY,
    spaceAfter=8, leading=58, alignment=TA_LEFT)

S_COVER_SUB = make_style('CoverSub',
    fontName='Helvetica', fontSize=22, textColor=HexColor('#3A4E6E'),
    spaceAfter=10, leading=28, alignment=TA_LEFT)

S_COVER_TAG = make_style('CoverTag',
    fontName='Helvetica', fontSize=13, textColor=HexColor('#5A6A8A'),
    spaceAfter=6, leading=18, alignment=TA_LEFT)

S_COVER_VER = make_style('CoverVer',
    fontName='Helvetica-Oblique', fontSize=11, textColor=HexColor('#7A8AAA'),
    spaceAfter=0, leading=16, alignment=TA_LEFT)

S_COVER_BOX = make_style('CoverBox',
    fontName='Helvetica', fontSize=10.5, textColor=WHITE,
    spaceAfter=0, leading=17, alignment=TA_LEFT)

S_TOC_TITLE = make_style('TOCTitle',
    fontName='Helvetica-Bold', fontSize=26, textColor=NAVY,
    spaceAfter=20, leading=32, alignment=TA_LEFT)

S_TOC_ITEM = make_style('TOCItem',
    fontName='Helvetica', fontSize=12, textColor=DARKTEXT,
    spaceAfter=6, leading=18, leftIndent=8)

S_SECTION_H = make_style('SectionH',
    fontName='Helvetica-Bold', fontSize=20, textColor=NAVY,
    spaceBefore=18, spaceAfter=10, leading=26)

S_SECTION_H2 = make_style('SectionH2',
    fontName='Helvetica-Bold', fontSize=14, textColor=NAVY,
    spaceBefore=12, spaceAfter=6, leading=20)

S_SECTION_H3 = make_style('SectionH3',
    fontName='Helvetica-Bold', fontSize=11.5, textColor=HexColor('#2A3D6A'),
    spaceBefore=8, spaceAfter=4, leading=16)

S_BODY = make_style('Body',
    fontName='Helvetica', fontSize=10, textColor=DARKTEXT,
    spaceAfter=6, leading=15)

S_BODY_BOLD = make_style('BodyBold',
    fontName='Helvetica-Bold', fontSize=10, textColor=DARKTEXT,
    spaceAfter=4, leading=15)

S_CODE = make_style('Code',
    fontName='Courier', fontSize=9, textColor=HexColor('#1B2A4A'),
    spaceAfter=3, leading=13, leftIndent=12)

S_INFO_BOX = make_style('InfoBox',
    fontName='Helvetica', fontSize=10, textColor=DARKTEXT,
    spaceAfter=0, leading=15)

S_LABEL_GREEN = make_style('LabelGreen',
    fontName='Helvetica-Bold', fontSize=9, textColor=WHITE,
    spaceAfter=0, leading=13, alignment=TA_CENTER)

S_TABLE_HEADER = make_style('TH',
    fontName='Helvetica-Bold', fontSize=9.5, textColor=WHITE,
    spaceAfter=0, leading=14, alignment=TA_LEFT)

S_TABLE_CELL = make_style('TC',
    fontName='Helvetica', fontSize=9, textColor=DARKTEXT,
    spaceAfter=0, leading=13, alignment=TA_LEFT)

S_TABLE_CELL_BOLD = make_style('TCB',
    fontName='Helvetica-Bold', fontSize=9, textColor=DARKTEXT,
    spaceAfter=0, leading=13, alignment=TA_LEFT)


# ── Helper builders ──────────────────────────────────────────────────────────

def hr():
    return HRFlowable(width="100%", thickness=0.8, color=MIDGRAY, spaceAfter=10, spaceBefore=4)

def section_hr():
    return HRFlowable(width="100%", thickness=2, color=GREEN, spaceAfter=12, spaceBefore=2)

def spacer(h=8):
    return Spacer(1, h)

def body(text):
    return Paragraph(text, S_BODY)

def h1(text):
    return Paragraph(text, S_SECTION_H)

def h2(text):
    return Paragraph(text, S_SECTION_H2)

def h3(text):
    return Paragraph(text, S_SECTION_H3)

def code(text):
    return Paragraph(text, S_CODE)

def info_box(paragraphs, bg=LIGHTGRAY, padding=14):
    """Wrap content in a shaded box using a single-cell Table."""
    inner = [Paragraph(p, S_INFO_BOX) for p in paragraphs]
    tbl = Table([[inner]], colWidths=[CONTENT_W - 2])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg),
        ('ROUNDEDCORNERS', [4]),
        ('LEFTPADDING',   (0,0), (-1,-1), padding),
        ('RIGHTPADDING',  (0,0), (-1,-1), padding),
        ('TOPPADDING',    (0,0), (-1,-1), padding),
        ('BOTTOMPADDING', (0,0), (-1,-1), padding),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    return tbl

def navy_box(paragraphs, padding=16):
    inner = [Paragraph(p, S_COVER_BOX) for p in paragraphs]
    tbl = Table([[inner]], colWidths=[CONTENT_W - 2])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), NAVY),
        ('LEFTPADDING',   (0,0), (-1,-1), padding),
        ('RIGHTPADDING',  (0,0), (-1,-1), padding),
        ('TOPPADDING',    (0,0), (-1,-1), padding),
        ('BOTTOMPADDING', (0,0), (-1,-1), padding),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    return tbl

def data_table(headers, rows, col_widths=None):
    """Navy header, alternating light-gray / white rows."""
    header_row = [Paragraph(h, S_TABLE_HEADER) for h in headers]
    data = [header_row]
    for i, row in enumerate(rows):
        data.append([Paragraph(str(c), S_TABLE_CELL) for c in row])

    if col_widths is None:
        col_widths = [CONTENT_W / len(headers)] * len(headers)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR',     (0, 0), (-1, 0), WHITE),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0), 9.5),
        ('ROWBACKGROUND', (0, 1), (-1, -1), [LIGHTGRAY, WHITE]),
        ('GRID',          (0, 0), (-1, -1), 0.4, MIDGRAY),
        ('LINEBELOW',     (0, 0), (-1, 0), 1.2, GREEN),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUND', (0, 1), (-1, -1), [LIGHTGRAY, WHITE]),
    ]
    # Manually alternate row backgrounds
    for i in range(1, len(data)):
        bg = LIGHTGRAY if i % 2 == 1 else WHITE
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── CONTENT BUILDER ──────────────────────────────────────────────────────────

def build_story():
    story = []

    # ── PAGE 1: COVER ──────────────────────────────────────────────────────
    story.append(spacer(80))
    story.append(Paragraph("Miragent", S_COVER_TITLE))
    story.append(spacer(4))

    # Green accent bar
    story.append(HRFlowable(width="30%", thickness=4, color=GREEN, spaceAfter=16, spaceBefore=0))

    story.append(Paragraph("Technical Architecture Reference", S_COVER_SUB))
    story.append(spacer(6))
    story.append(Paragraph(
        "System design, data layer, API surface, and deployment topology",
        S_COVER_TAG))
    story.append(spacer(4))
    story.append(Paragraph("v0.83.0 — May 2026", S_COVER_VER))
    story.append(spacer(36))

    story.append(navy_box([
        "<b>About this document</b>",
        "",
        "This document covers the complete technical architecture of the Miragent platform: "
        "the four-layer system design, polyglot data layer, 31-connector ingestion framework, "
        "34-worker intelligence engine, multi-provider LLM layer, 40+ API routes, security "
        "middleware stack, React frontend, and Fly.io/Vercel deployment topology.",
    ]))

    story.append(PageBreak())

    # ── PAGE 2: TABLE OF CONTENTS ──────────────────────────────────────────
    story.append(spacer(20))
    story.append(Paragraph("Table of Contents", S_TOC_TITLE))
    story.append(section_hr())
    story.append(spacer(8))

    toc_entries = [
        ("1.", "System Architecture Overview"),
        ("2.", "The Four Layers"),
        ("3.", "Data Layer — Polyglot Persistence"),
        ("4.", "Connector Framework"),
        ("5.", "Intelligence Worker Engine"),
        ("6.", "LLM Provider Layer"),
        ("7.", "API Surface — All Routes"),
        ("8.", "Security Middleware Stack"),
        ("9.", "Database Models & Schema"),
        ("10.", "Frontend Architecture"),
        ("11.", "Background Services & Scheduler"),
        ("12.", "Deployment Topology"),
        ("13.", "Configuration & Environment"),
        ("14.", "Testing Architecture"),
    ]

    toc_data = []
    for num, title in toc_entries:
        toc_data.append([
            Paragraph(f"<b>{num}</b>", S_TOC_ITEM),
            Paragraph(title, S_TOC_ITEM),
        ])

    toc_table = Table(toc_data, colWidths=[36, CONTENT_W - 36])
    toc_table.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LINEBELOW',     (0,0), (-1,-2), 0.3, MIDGRAY),
    ]))
    story.append(toc_table)
    # Architecture principles interstitial (fills the TOC page better)
    story.append(spacer(20))
    story.append(hr())
    story.append(spacer(8))

    principles = [
        ("12-Factor Config",
         "All configuration lives in environment variables. Code never reads env vars directly — "
         "always via the pydantic-settings Settings class. Dev uses .env.local; production uses "
         "injected secrets on Fly.io."),
        ("Polyglot Persistence",
         "Each database is chosen for its strengths: Neo4j for graph traversal, ClickHouse for "
         "append-only analytics, Weaviate for vector similarity, SQLAlchemy/SQLite for relational data. "
         "No single database is forced to serve all shapes."),
        ("Mock-first Development",
         "Every connector has a mock twin. USE_MOCK_CONNECTORS=true swaps the entire connector layer "
         "for deterministic synthetic data. This allows full end-to-end testing without SaaS credentials."),
        ("Single LLM Abstraction",
         "LLMAnalyst is the only component that knows about LLM providers. All other code calls "
         "provider.complete(system, messages). Switching from Anthropic to Ollama requires changing "
         "one environment variable."),
        ("Risk-tiered Automation",
         "No action is taken without an explicit risk classification. LOW findings auto-remediate; "
         "HIGH findings pause for human approval. BLOCKED actions are never automated, regardless "
         "of configuration."),
        ("SOC 2 by Design",
         "Every API request is logged to ClickHouse (AuditLogMiddleware). Rate limiting prevents "
         "abuse. Security headers are injected at the middleware layer, not in individual routes. "
         "Approval gates create an immutable audit trail for every remediation."),
    ]

    for title, desc in principles:
        principle_tbl = Table(
            [[Paragraph(title, S_TABLE_CELL_BOLD), Paragraph(desc, S_TABLE_CELL)]],
            colWidths=[140, CONTENT_W - 140]
        )
        principle_tbl.setStyle(TableStyle([
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING',   (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
            ('LINEBELOW',    (0,0), (-1,-1), 0.3, MIDGRAY),
        ]))
        story.append(principle_tbl)

    story.append(PageBreak())

    # ── SECTION 1: System Architecture Overview ────────────────────────────
    story.append(h1("1. System Architecture Overview"))
    story.append(section_hr())

    story.append(info_box([
        "<b>One-sentence summary:</b> Miragent pulls data from 31 business systems, builds a "
        "unified knowledge graph, runs 34 AI workers to find problems, surfaces findings through "
        "an intelligent UI, and fixes them automatically within configured guardrails."
    ]))
    story.append(spacer(12))

    story.append(h2("Tech Stack"))
    story.append(spacer(6))

    tech_headers = ["Layer", "Technology", "Purpose"]
    tech_rows = [
        ["API",             "FastAPI (Python 3.11)",          "REST endpoints, middleware, routing"],
        ["Graph DB",        "Neo4j 5.x",                     "Digital twin — nodes and relationships"],
        ["Relational DB",   "SQLite (dev) / PostgreSQL (prod)", "Auth, actions, config, snapshots"],
        ["Analytics DB",    "ClickHouse",                    "Audit logs, time-series events"],
        ["Vector DB",       "Weaviate",                      "Semantic search, KB embeddings"],
        ["LLM",             "Anthropic / OpenAI / Gemini / Ollama", "Narrative synthesis, Copilot answers"],
        ["Frontend",        "React 18, TypeScript, Vite",    "Browser UI"],
        ["Frontend Deploy", "Vercel",                         "CDN-distributed static hosting"],
        ["Backend Deploy",  "Fly.io",                         "Edge-deployed Docker containers"],
        ["Graph Deploy",    "Neo4j Aura",                    "Managed cloud Neo4j"],
    ]
    story.append(data_table(tech_headers, tech_rows, col_widths=[100, 160, CONTENT_W - 260]))
    story.append(spacer(14))

    story.append(h2("Key Architectural Decisions"))
    story.append(spacer(6))
    decisions = [
        ("FastAPI over Django/Flask",
         "FastAPI's dependency injection system is central to the architecture — it enables clean "
         "auth wiring, test overrides, and per-route middleware without global state. Automatic "
         "OpenAPI generation means the API is always self-documenting."),
        ("Neo4j over pure SQL for the digital twin",
         "The core analytical value of Miragent is relationship traversal: finding chains of risk "
         "across org boundaries. A graph database makes these queries declarative (Cypher) rather "
         "than requiring multi-table JOINs that are slow, hard to write, and harder to maintain."),
        ("Python threading over Celery",
         "The background scheduler uses a single daemon thread with a 60-second tick. This keeps "
         "deployment simple — no Redis, no Celery worker process, no distributed queue. The tradeoff "
         "is single-node scheduling, which is acceptable at current scale."),
        ("Vite + React over Next.js",
         "Miragent's frontend is a pure SPA with no server-side rendering requirements. Vite gives "
         "fast HMR in development and optimised static output for Vercel deployment. Next.js would "
         "add complexity (SSR, edge functions) without benefit for this use case."),
    ]
    for i, (title, desc) in enumerate(decisions):
        bg = LIGHTGRAY if i % 2 == 0 else WHITE
        dec_tbl = Table(
            [[Paragraph(f"<b>{title}</b>", S_TABLE_CELL_BOLD)],
             [Paragraph(desc, S_TABLE_CELL)]],
            colWidths=[CONTENT_W]
        )
        dec_tbl.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,-1), bg),
            ('LEFTPADDING',  (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING',   (0,0), (0,0), 8),
            ('TOPPADDING',   (0,1), (0,1), 2),
            ('BOTTOMPADDING',(0,0), (-1,-1), 8),
            ('GRID',         (0,0), (-1,-1), 0.4, MIDGRAY),
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
        ]))
        story.append(dec_tbl)
    story.append(PageBreak())

    # ── SECTION 2: The Four Layers ─────────────────────────────────────────
    story.append(h1("2. The Four Layers"))
    story.append(section_hr())

    # Layer 1
    story.append(h2("Layer 1 — Connectors (the ears)"))
    story.append(body("Location: <font name='Courier'>scout/connectors/</font>"))
    story.append(body(
        "31 connectors, each a Python class inheriting from <font name='Courier'>ConnectorBase</font> (ABC). "
        "Every connector implements five abstract methods:"))
    story.append(spacer(4))
    for m in [
        "authenticate() -> bool",
        "discover_schema() -> list[EntitySchema]",
        "extract_full(entity_type) -> Iterator[RawRecord]",
        "extract_incremental(entity_type, cursor) -> Iterator[RawRecord]",
        "health_check() -> ConnectorHealth",
    ]:
        story.append(code(f"  {m}"))
    story.append(spacer(6))
    story.append(body(
        "Mock connectors (<font name='Courier'>scout/connectors/mock/</font>) implement the same interface "
        "but return deterministic synthetic data. The registry "
        "(<font name='Courier'>scout/connectors/registry.py</font>) returns mock or real based on "
        "<font name='Courier'>USE_MOCK_CONNECTORS</font> env var."))
    story.append(spacer(10))

    # Layer 2
    story.append(h2("Layer 2 — The Graph (the brain's memory)"))
    story.append(body("Location: <font name='Courier'>scout/graph/, scout/ingestion/</font>"))
    story.append(body(
        "Raw records flow through: <b>Normalizer</b> (standardises field names, dates, phone numbers "
        "across sources) &rarr; <b>Resolver</b> (deduplicates entities using fuzzy name+email matching) "
        "&rarr; <b>Graph writer</b> (writes canonical entities as Neo4j nodes with typed relationships)."))
    story.append(spacer(6))

    graph_data = [
        ["Node Labels", "Person, Account, Opportunity, Vendor, Department, Role"],
        ["Relationship Types", "REPORTS_TO, MANAGES, OWNS_DEAL, IN_ACCOUNT, USES_VENDOR, HAS_CONTRACT"],
    ]
    g_tbl = Table(graph_data, colWidths=[120, CONTENT_W - 120])
    g_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (0,-1), LIGHTGRAY),
        ('FONTNAME',     (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,-1), 9),
        ('GRID',         (0,0), (-1,-1), 0.4, MIDGRAY),
        ('LEFTPADDING',  (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING',   (0,0), (-1,-1), 6),
        ('BOTTOMPADDING',(0,0), (-1,-1), 6),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(g_tbl)
    story.append(spacer(10))

    # Layer 3
    story.append(h2("Layer 3 — The Workers (the analysts)"))
    story.append(body("Location: <font name='Courier'>scout/workers/</font>"))
    story.append(body(
        "34 Python classes, each a specialised analytical worker. Workers receive "
        "<font name='Courier'>WorkerContext</font> (Neo4j driver, tenant_id, config) and return "
        "<font name='Courier'>list[Finding]</font>."))
    story.append(body(
        "Each Finding contains: title, description, severity (CRITICAL/HIGH/MEDIUM/LOW), "
        "affected_entity_ids, worker_name, metadata."))
    story.append(spacer(10))

    # Layer 4
    story.append(h2("Layer 4 — The Action Layer (the hands)"))
    story.append(body("Location: <font name='Courier'>scout/actions/</font>"))
    story.append(body(
        "Findings &rarr; Playbook engine &rarr; RemediationActions &rarr; Approval gate "
        "&rarr; Executors &rarr; Source system updates."))
    story.append(spacer(4))

    risk_data = [
        ["Risk Tier", "Automation Behaviour"],
        ["LOW",     "Auto-execute"],
        ["MEDIUM",  "Execute with notification"],
        ["HIGH",    "Wait for human approval"],
        ["BLOCKED", "Never automated"],
    ]
    story.append(data_table(
        ["Risk Tier", "Automation Behaviour"],
        [r for r in risk_data[1:]],
        col_widths=[100, CONTENT_W - 100]
    ))
    story.append(PageBreak())

    # ── SECTION 3: Data Layer ──────────────────────────────────────────────
    story.append(h1("3. Data Layer — Polyglot Persistence"))
    story.append(section_hr())
    story.append(body(
        "Why four databases: each is optimised for a different data shape and access pattern."))
    story.append(spacer(8))

    # Neo4j
    story.append(h2("Neo4j — Property Graph Database"))
    story.append(info_box([
        "<b>URI:</b> NEO4J_URI env var (Neo4j Aura in production)",
        "<b>Schema:</b> indexes on tenant_id for all node labels; uniqueness constraints on entity IDs",
        "<b>Why Neo4j:</b> relationship traversal is 10-100x faster than SQL JOINs for graph patterns. "
        '"Show all customers at risk because their main contact just left" is a single traversal, not a 6-table JOIN.',
        "<b>Used by:</b> ingestion pipeline, all 34 workers, Copilot graph queries, graph API endpoints.",
    ]))
    story.append(spacer(10))

    # SQLite/Postgres
    story.append(h2("SQLite / PostgreSQL — Relational Database"))
    story.append(body(
        "ORM: SQLAlchemy 2.x with Alembic migrations. "
        "Connection: <font name='Courier'>DATABASE_URL</font> env var; "
        "<font name='Courier'>sqlite:///./miragent.db</font> in dev."))
    story.append(body(
        "Key tables: users, remediation_actions, approval_requests, insight_snapshots, "
        "insight_schedules, user_tenant_access, digest_recipients, connector_credential_store, "
        "kb_documents, kb_chunks, sso_providers."))
    story.append(spacer(10))

    # ClickHouse
    story.append(h2("ClickHouse — Column-Store Analytics"))
    story.append(body(
        "Used for: audit log (every API call), scan event log, action execution log."))
    story.append(body(
        "Why ClickHouse: append-only high-volume writes (10,000+ events/second); analytical "
        "aggregations over time ranges are very fast. Required for SOC 2 audit trail."))
    story.append(spacer(10))

    # Weaviate
    story.append(h2("Weaviate — Vector Database"))
    story.append(body(
        "Used for: knowledge base document embeddings, semantic search across findings. "
        "Status: provisioned and connected; actively used by KB Manager (Sprint 75)."))
    story.append(PageBreak())

    # ── SECTION 4: Connector Framework ────────────────────────────────────
    story.append(h1("4. Connector Framework"))
    story.append(section_hr())

    story.append(h2("File Structure"))
    for line in [
        "scout/connectors/",
        "  base.py — ConnectorBase ABC + @rate_limited decorator",
        "  models.py — ConnectorCredentials, RawRecord, EntitySchema, ConnectorHealth",
        "  oauth2.py — OAuth2Token, OAuth2ClientCredentials, OAuth2AuthorizationCode",
        "  registry.py — CONNECTOR_REGISTRY dict, get_connector(), get_connector_with_stored_creds()",
        "  salesforce.py — Production Salesforce connector (SOQL, 5 calls/sec, pagination)",
        "  workday.py — Production Workday connector",
        "  [29 more production connectors]",
        "  mock/ — 31 mock connectors returning deterministic synthetic data",
    ]:
        story.append(code(line))
    story.append(spacer(10))

    story.append(h2("Rate Limiting"))
    story.append(body(
        "<font name='Courier'>@rate_limited</font> decorator enforces CALLS_PER_SECOND "
        "(5 for Salesforce, 10 for others). Uses <font name='Courier'>time.sleep()</font> between calls."))
    story.append(spacer(10))

    story.append(h2("Credential Storage (Sprint 83)"))
    story.append(body(
        "<font name='Courier'>ConnectorCredentialStore</font> SQLAlchemy model stores OAuth2 tokens per "
        "(tenant_id, connector_id). <font name='Courier'>get_connector_with_stored_creds()</font> queries "
        "this table and returns a live connector with stored auth_data."))
    story.append(spacer(10))

    story.append(h2("Connector Categories"))
    story.append(body(
        "The 31 connectors span the major business system categories an enterprise relies on. "
        "Each category uses the same ConnectorBase interface, enabling the ingestion pipeline to "
        "treat all connectors uniformly."))
    story.append(spacer(6))

    connector_cat_rows = [
        ["CRM & Sales",          "Salesforce, HubSpot, Pipedrive, Zoho CRM"],
        ["HR & Workforce",       "Workday, BambooHR, Rippling, Gusto, ADP"],
        ["Finance & Accounting", "QuickBooks, Xero, NetSuite, Sage"],
        ["IT & Identity",        "Okta, Azure AD, Google Workspace, JumpCloud"],
        ["Project & Tickets",    "Jira, Linear, Asana, ServiceNow"],
        ["Communication",        "Slack, Microsoft Teams, Gmail"],
        ["Procurement",          "Coupa, SAP Ariba, Procurify"],
        ["Analytics & BI",       "Looker, Tableau, Metabase"],
        ["Custom / Generic",     "REST connector (configurable base URL + auth)"],
    ]
    story.append(data_table(
        ["Category", "Connectors"],
        connector_cat_rows,
        col_widths=[140, CONTENT_W - 140]
    ))
    story.append(spacer(12))

    story.append(h2("Salesforce OAuth2 Flow"))
    oauth_steps = [
        "GET /connectors/salesforce/auth-start",
        "  -> Salesforce consent screen",
        "  -> GET /connectors/salesforce/callback  (no auth required)",
        "  -> token exchange",
        "  -> stored in ConnectorCredentialStore",
        "  -> future scans use stored refresh_token",
    ]
    for s in oauth_steps:
        story.append(code(s))
    story.append(PageBreak())

    # ── SECTION 5: Intelligence Worker Engine ─────────────────────────────
    story.append(h1("5. Intelligence Worker Engine"))
    story.append(section_hr())

    story.append(body(
        "All 34 workers are registered in a worker registry and run during a scan. Each worker receives "
        "<font name='Courier'>WorkerContext</font> with Neo4j driver + tenant_id + config overrides, "
        "runs Cypher queries against the graph, applies threshold logic to classify findings, and returns "
        "<font name='Courier'>list[Finding]</font> with severity ratings."))
    story.append(spacer(10))

    story.append(h2("Worker Categories"))
    worker_headers = ["Category", "Workers"]
    worker_rows = [
        ["Sales & Pipeline",   "ChurnPrediction, PipelineVelocity, WinRateAnalysis, AccountCoverage"],
        ["Finance & Vendors",  "VendorBenchmark, ContractRenewal, BudgetVariance, DuplicateSubscriptions"],
        ["HR & Workforce",     "WorkforceWorker, KeyPersonRisk, AttritionRisk, HiringVelocity"],
        ["Compliance & IT",    "AccessRightSizing, PolicyCompliance, SecurityPosture, DataQuality"],
        ["Operations",         "ProcessAdherence, TicketSLA, VendorUtilisation, ChangeVelocity"],
        ["Executive",          "RevenueConcentration, CustomerConcentration, MarginAnalysis, RunwayAnalysis"],
        ["Intelligence",       "10 additional cross-cutting analytical workers"],
    ]
    story.append(data_table(worker_headers, worker_rows, col_widths=[140, CONTENT_W - 140]))
    story.append(spacer(12))

    story.append(h2("Finding Severity Levels"))
    sev_rows = [
        ["CRITICAL", "Immediate action required; included in executive summary"],
        ["HIGH",     "Routed to Approvals queue when actioned"],
        ["MEDIUM",   "Auto-execute with notification"],
        ["LOW",      "Informational — logged only"],
    ]
    story.append(data_table(["Severity", "Behaviour"], sev_rows, col_widths=[80, CONTENT_W - 80]))
    story.append(spacer(12))

    story.append(h2("InsightSnapshot Persistence"))
    story.append(body(
        "After every successful <font name='Courier'>/insights</font> run, an "
        "<font name='Courier'>InsightSnapshot</font> row is upserted to SQLite with: finding counts "
        "by severity, top 10 findings, worker summaries, narrative snippet (first 500 chars of LLM memo), "
        "llm_provider, llm_model, run_at. Portfolio view reads InsightSnapshots without re-running workers."))
    story.append(PageBreak())

    # ── SECTION 6: LLM Provider Layer ─────────────────────────────────────
    story.append(h1("6. LLM Provider Layer"))
    story.append(section_hr())

    story.append(body(
        "Location: <font name='Courier'>scout/analysis/llm_analyst.py, scout/analysis/providers/</font>"))
    story.append(body(
        "<font name='Courier'>LLMAnalyst</font> holds a single <font name='Courier'>_provider</font> "
        "instance selected at startup from <font name='Courier'>LLM_PROVIDER</font> env var. All LLM calls "
        "go through <font name='Courier'>provider.complete(system, messages) -> str</font>. The provider is "
        "the only LLM-aware component."))
    story.append(spacer(10))

    llm_headers = ["Provider", "SDK", "Default Model", "API Key Env Var"]
    llm_rows = [
        ["Anthropic (default)", "anthropic",            "claude-sonnet-4-5", "ANTHROPIC_API_KEY"],
        ["OpenAI",              "openai",                "gpt-4o",            "OPENAI_API_KEY"],
        ["Google Gemini",       "google-generativeai",  "gemini-2.0-flash",  "GEMINI_API_KEY"],
        ["Ollama (local)",      "HTTP (stdlib)",         "llama3.1",          "None required"],
    ]
    story.append(data_table(llm_headers, llm_rows,
        col_widths=[120, 130, 120, CONTENT_W - 370]))
    story.append(spacer(10))

    story.append(info_box([
        "<b>Fallback:</b> If the configured provider's API key is missing or the call fails, the system "
        "falls back to a template narrative. An <font name='Courier'>is_available</font> flag is surfaced "
        "in API responses."
    ]))
    story.append(PageBreak())

    # ── SECTION 7: API Surface ─────────────────────────────────────────────
    story.append(h1("7. API Surface — All Routes"))
    story.append(section_hr())

    story.append(body(
        "Framework: FastAPI 0.100+ with automatic OpenAPI docs at "
        "<font name='Courier'>/docs</font> and <font name='Courier'>/redoc</font>."))
    story.append(body(
        "Auth: JWT Bearer tokens; <font name='Courier'>get_current_user</font> dependency injected per route."))
    story.append(spacer(8))

    route_groups = [
        ("Core", "GET /health, POST /scans, GET /scans/{id}, GET /graph/*"),
        ("Auth & Users",
         "POST /auth/login, POST /auth/refresh, POST /auth/logout, GET/POST /auth/sso/*, "
         "GET /sso/domain-check, POST/GET /mfa/*, POST/GET/PUT/DELETE /users/*, GET/PUT/DELETE /admin/*"),
        ("Intelligence",
         "GET /insights, POST /copilot/ask, POST /copilot/create-action, "
         "GET /communications/*, GET /health-score/*"),
        ("Portfolio & Fund", "GET /portfolio/summary, GET /portfolio/tenants"),
        ("Agents (9 agents)",
         "POST/GET /ddq/*, POST/GET /agents/payroll/*, POST/GET /agents/portal-access/*, "
         "POST/GET /agents/support-triage/*, POST/GET /payment-status/*, POST/GET /benefits/*, "
         "GET/POST /vendor-onboarding/*, POST/GET /it-access/*, POST/GET /compliance/*"),
        ("Operations",
         "GET /mission-control/*, GET/POST /dashboard/*, GET/POST /notifications/*, "
         "GET/POST/DELETE /schedule/*, GET/POST/DELETE /knowledge-base/*, "
         "POST/GET /design-session/*, POST/GET /board-report/*"),
        ("Access Control",
         "GET /access/my-tenants, GET /access/users/{id}, POST /access/grant, "
         "DELETE /access/revoke/{user_id}/{tenant_id}"),
        ("Connectors",
         "GET /connectors, GET /connectors/salesforce/auth-start, "
         "GET /connectors/salesforce/callback (no auth), "
         "POST /connectors/salesforce/disconnect, POST /connectors/salesforce/test"),
        ("Email Digest",
         "GET/POST/DELETE /digest/recipients, POST /digest/send-now"),
        ("Webhooks", "POST /webhooks/*"),
    ]

    route_data = [[Paragraph(f"<b>{g}</b>", S_TABLE_CELL_BOLD), Paragraph(r, S_TABLE_CELL)]
                  for g, r in route_groups]
    route_tbl = Table(
        [[Paragraph("Route Group", S_TABLE_HEADER), Paragraph("Endpoints", S_TABLE_HEADER)]] + route_data,
        colWidths=[130, CONTENT_W - 130],
        repeatRows=1
    )
    route_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), NAVY),
        ('LINEBELOW',     (0, 0), (-1, 0), 1.2, GREEN),
        ('GRID',          (0, 0), (-1, -1), 0.4, MIDGRAY),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ] + [('BACKGROUND', (0, i), (-1, i), LIGHTGRAY if i % 2 == 1 else WHITE)
         for i in range(1, len(route_data) + 1)]))
    story.append(route_tbl)
    story.append(PageBreak())

    # ── SECTION 8: Security Middleware Stack ───────────────────────────────
    story.append(h1("8. Security Middleware Stack"))
    story.append(section_hr())

    story.append(h2("Execution Order (request &rarr; response)"))
    story.append(info_box([
        "SecurityHeadersMiddleware &rarr; AuditLogMiddleware &rarr; RateLimitMiddleware &rarr; CORS &rarr; routes",
        "",
        "<i>Note: Starlette middleware is LIFO so they are registered in reverse order in app.py.</i>",
    ]))
    story.append(spacer(12))

    mw_items = [
        ("SecurityHeadersMiddleware",
         "Adds X-Content-Type-Options: nosniff, X-Frame-Options: DENY, X-XSS-Protection: 1; mode=block, "
         "Strict-Transport-Security, Content-Security-Policy to every response."),
        ("AuditLogMiddleware",
         "Logs every request to logs/audit.log — timestamp, method, path, tenant_id (from JWT), user_id, "
         "IP address, response status, duration_ms. Required for SOC 2 Type II."),
        ("RateLimitMiddleware",
         "60 requests/minute per tenant (configurable via RATE_LIMIT_PER_MINUTE). In-memory sliding window. "
         "Returns 429 with Retry-After header when exceeded."),
        ("CORS",
         "allow_origins=[\"*\"] in development. Tighten to specific frontend domain in production."),
        ("JWT Authentication",
         "HS256 signed tokens. get_current_user dependency decodes token, loads User from SQLite, "
         "validates is_active. AUTH_ENABLED=false disables auth for local testing."),
    ]
    for name, desc in mw_items:
        story.append(KeepTogether([
            h3(name),
            body(desc),
            spacer(4),
        ]))

    story.append(spacer(8))
    story.append(h2("Threat Model Summary"))
    story.append(body(
        "The security middleware stack addresses the OWASP API Top 10 threats relevant to Miragent's "
        "API surface. The table below maps each threat to the mitigation implemented."))
    story.append(spacer(6))

    threat_rows = [
        ["Broken Object Level Auth",     "JWT tenant_id claim scoped on every Neo4j query and SQLAlchemy filter"],
        ["Broken Authentication",        "HS256 JWT with short expiry; refresh token rotation; MFA support"],
        ["Excessive Data Exposure",      "Response models use explicit field whitelists (Pydantic schemas)"],
        ["Lack of Resources & Rate Limiting", "RateLimitMiddleware: 60 req/min per tenant, 429 + Retry-After"],
        ["Security Misconfiguration",    "SecurityHeadersMiddleware injects CSP, HSTS, X-Frame-Options on every response"],
        ["Injection",                    "Parameterised Cypher queries; SQLAlchemy ORM prevents raw SQL injection"],
        ["Improper Asset Management",    "OpenAPI auto-generated at /docs; all routes visible in one place"],
        ["Insufficient Logging",         "AuditLogMiddleware logs every request to ClickHouse for SOC 2 Type II"],
    ]
    story.append(data_table(
        ["Threat", "Mitigation"],
        threat_rows,
        col_widths=[180, CONTENT_W - 180]
    ))
    story.append(PageBreak())

    # ── SECTION 9: Database Models ─────────────────────────────────────────
    story.append(h1("9. Database Models & Schema"))
    story.append(section_hr())
    story.append(body(
        "All SQLAlchemy models in <font name='Courier'>scout/db/models.py</font>."))
    story.append(spacer(8))

    model_groups = [
        ("Auth & Users",         "Tenant, User, APIKey"),
        ("Workers",              "WorkerConfig, NoiseProfile, ThresholdProposal"),
        ("Findings & Actions",   "FindingDisposition, RemediationAction, ApprovalRequest, "
                                 "ExecutionLog, EvidenceCheckLog, ActionReminder, PlaybookRule"),
        ("Intelligence",         "InsightSnapshot, InsightSchedule"),
        ("SSO",                  "SSOProvider"),
        ("Knowledge Base",       "KBDocument, KBChunk"),
        ("Agents",               "DDQJob, PayrollRequest, PortalAccessRequest, "
                                 "ProcessBlueprint, AgentDeployment"),
        ("Access Control",       "UserTenantAccess"),
        ("Email",                "DigestRecipient"),
        ("Connectors",           "ConnectorCredentialStore"),
    ]
    story.append(data_table(
        ["Category", "Models"],
        model_groups,
        col_widths=[130, CONTENT_W - 130]
    ))
    story.append(spacer(12))

    story.append(h2("Key Relationships"))
    rel_rows = [
        ["User.tenant_id",                    "-> home tenant (string foreign key)"],
        ["RemediationAction.finding_hash",    "-> links to worker finding"],
        ["ApprovalRequest.action_id",         "-> FK to RemediationAction.id"],
        ["UserTenantAccess",                  "UniqueConstraint(user_id, tenant_id)"],
        ["ConnectorCredentialStore",          "UniqueConstraint(tenant_id, connector_id)"],
    ]
    story.append(data_table(["Model / Field", "Relationship"], rel_rows,
        col_widths=[200, CONTENT_W - 200]))
    story.append(PageBreak())

    # ── SECTION 10: Frontend Architecture ─────────────────────────────────
    story.append(h1("10. Frontend Architecture"))
    story.append(section_hr())

    story.append(body(
        "Stack: React 18 (concurrent features), TypeScript (strict mode), Vite (build + HMR), "
        "React Router v6 (client-side routing), Tailwind CSS (utility classes), Lucide React (icons). "
        "All pages lazy-loaded with React.lazy() + Suspense."))
    story.append(spacer(10))

    story.append(h2("File Structure"))
    for line in [
        "frontend/src/",
        "  App.tsx — Router + Suspense wrapper + Sidebar layout",
        "  api/client.ts — Typed API client (all fetch calls, typed request/response)",
        "  components/Sidebar.tsx — Fixed nav with 40+ links grouped by section",
        "  pages/ — 30+ page components (one per route)",
    ]:
        story.append(code(line))
    story.append(spacer(10))

    story.append(h2("API Client Pattern"))
    story.append(body(
        "Single <font name='Courier'>api</font> object exported from "
        "<font name='Courier'>client.ts</font>. Every method is a typed async function with explicit "
        "request/response types. Token passed explicitly. No global auth state."))
    story.append(spacer(10))

    story.append(h2("State Management"))
    story.append(body(
        "No Redux or Zustand. Each page manages its own state with "
        "<font name='Courier'>useState + useEffect</font>. Data fetching in "
        "<font name='Courier'>useEffect</font> with loading/error states. "
        "Keeps bundle small and pages independently understandable."))
    story.append(spacer(10))

    story.append(h2("Build"))
    story.append(body(
        "<font name='Courier'>tsc &amp;&amp; vite build</font>. TypeScript strict mode catches type errors "
        "at build time. Output: <font name='Courier'>dist/</font> directory of static files deployed to Vercel."))
    story.append(PageBreak())

    # ── SECTION 11: Background Services ───────────────────────────────────
    story.append(h1("11. Background Services & Scheduler"))
    story.append(section_hr())

    story.append(h2("Insight Scheduler (scout/scheduler.py)"))
    sched_points = [
        "Daemon thread, 60-second tick interval",
        "On each tick: queries InsightSchedule for all enabled schedules",
        "For each due schedule: calls full 34-worker pipeline, persists InsightSnapshot",
        "One tenant per tick to prevent Neo4j overload",
        "Started in FastAPI lifespan hook: start_scheduler(tick_seconds=60)",
        "Idempotent: _started flag prevents double-start",
    ]
    for p in sched_points:
        story.append(body(f"&bull;  {p}"))
    story.append(spacer(10))

    story.append(h2("Email Digest Scheduler"))
    digest_points = [
        "Runs inside the same daemon thread as the Insight Scheduler",
        "On each tick: checks weekday == 0 and hour == 6 and minute < 2",
        "Module-level _last_digest_date guard prevents double-sends on same Monday",
        "Calls build_and_send_portfolio_digest(db) which queries all active recipients and latest snapshots",
    ]
    for p in digest_points:
        story.append(body(f"&bull;  {p}"))
    story.append(spacer(10))

    story.append(info_box([
        "<b>Background job pattern:</b> Python <font name='Courier'>threading.Thread</font> with "
        "<font name='Courier'>daemon=True</font>. No Celery, no Redis queue, no APScheduler — "
        "keeps deployment simple."
    ]))
    story.append(PageBreak())

    # ── SECTION 12: Deployment Topology ───────────────────────────────────
    story.append(h1("12. Deployment Topology"))
    story.append(section_hr())

    story.append(h2("Backend — Fly.io"))
    story.append(body(
        "Docker container running: "
        "<font name='Courier'>uvicorn scout.api.app:app --host 0.0.0.0 --port 8000</font>"))
    story.append(body(
        "Fly.io deploys to edge regions. SQLite volume mounted for persistence (or DATABASE_URL -> "
        "external PostgreSQL). Environment variables via Fly.io secrets."))
    story.append(spacer(10))

    story.append(h2("Frontend — Vercel"))
    story.append(body(
        "Vite build output (<font name='Courier'>dist/</font>) deployed as static files. "
        "CDN distribution globally. Build command: "
        "<font name='Courier'>tsc &amp;&amp; vite build</font>."))
    story.append(spacer(10))

    story.append(h2("Graph — Neo4j Aura"))
    story.append(body(
        "Managed cloud Neo4j, no server to maintain. Connection via "
        "<font name='Courier'>NEO4J_URI = neo4j+s://...aura.graphdatabase.cloud</font>. "
        "Schema initialised at startup via <font name='Courier'>init_schema(driver)</font> (idempotent)."))
    story.append(spacer(12))

    story.append(h2("Deployment Flow"))
    diagram_lines = [
        "Browser",
        "  -> Vercel CDN",
        "     -> React SPA",
        "        -> Fly.io API  (FastAPI)",
        "           -> Neo4j Aura           (graph queries)",
        "           -> SQLite / PostgreSQL   (relational data)",
        "           -> ClickHouse            (audit logs)",
        "           -> Weaviate              (vector search)",
        "           -> Anthropic/OpenAI/Gemini  (LLM synthesis)",
        "           -> 31 external business systems  (connectors)",
    ]
    story.append(info_box(diagram_lines, bg=HexColor('#EEF1F7')))
    story.append(spacer(14))

    story.append(h2("Environment Matrix"))
    story.append(body(
        "Miragent runs in three named environments. Each environment uses the same codebase; "
        "behaviour is controlled entirely by environment variables."))
    story.append(spacer(6))

    env_rows = [
        ["local",      "sqlite:///./miragent.db", "USE_MOCK_CONNECTORS=true",  "No auth (AUTH_ENABLED=false)", "Ollama / any"],
        ["staging",    "PostgreSQL (Fly volume)",  "USE_MOCK_CONNECTORS=false", "Auth enabled, test JWT secret", "Anthropic / OpenAI"],
        ["production", "PostgreSQL (external)",    "USE_MOCK_CONNECTORS=false", "Auth enabled, prod JWT secret", "Anthropic"],
    ]
    story.append(data_table(
        ["Environment", "Database", "Connectors", "Auth", "LLM"],
        env_rows,
        col_widths=[72, 110, 110, 130, CONTENT_W - 422]
    ))
    story.append(spacer(14))

    story.append(h2("Scalability Considerations"))
    scale_items = [
        ("Horizontal API scaling",
         "FastAPI on Fly.io can run multiple instances behind Fly's load balancer. The only "
         "shared state is the database (PostgreSQL) and Neo4j Aura — both support concurrent connections. "
         "The in-memory rate limiter is per-instance; at scale, move to Redis-backed rate limiting."),
        ("Worker parallelism",
         "The 34 workers currently run sequentially per scan. Each worker is a pure function "
         "(WorkerContext in, list[Finding] out) — they can be parallelised with "
         "concurrent.futures.ThreadPoolExecutor without any API changes."),
        ("Neo4j read replicas",
         "Neo4j Aura supports read replicas. Worker queries (all read-only) can be routed to a "
         "read replica, leaving the primary for ingestion writes. No code changes required — "
         "configure via NEO4J_URI pointing to a reader endpoint."),
        ("ClickHouse partitioning",
         "The audit_log table should be partitioned by month (PARTITION BY toYYYYMM(timestamp)) "
         "for efficient time-range queries and TTL-based data expiry aligned with retention policy."),
    ]
    for title, desc in scale_items:
        story.append(KeepTogether([
            h3(title),
            body(desc),
            spacer(4),
        ]))
    story.append(PageBreak())

    # ── SECTION 13: Configuration & Environment ────────────────────────────
    story.append(h1("13. Configuration & Environment"))
    story.append(section_hr())

    story.append(body(
        "All config via <font name='Courier'>scout/config.py</font> — "
        "<font name='Courier'>Settings</font> class (pydantic-settings). Values from "
        "<font name='Courier'>.env.local</font> in dev, injected secrets in production. "
        "Follows 12-Factor App: code never reads env vars directly, always through "
        "<font name='Courier'>settings.*</font>."))
    story.append(spacer(10))

    config_headers = ["Group", "Key Settings"]
    config_rows = [
        ["Environment",   "ENVIRONMENT, USE_MOCK_CONNECTORS"],
        ["Tenant",        "TENANT_ID, TENANT_NAME"],
        ["Neo4j",         "NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD"],
        ["ClickHouse",    "CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD"],
        ["Weaviate",      "WEAVIATE_URL"],
        ["Security",      "SCOUT_API_KEY, RATE_LIMIT_PER_MINUTE, AUTH_ENABLED, AUDIT_LOG_FILE"],
        ["Auth/JWT",      "DATABASE_URL, JWT_SECRET, JWT_ALGORITHM"],
        ["SSO",           "API_BASE_URL"],
        ["LLM",           "LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL"],
        ["API Keys",      "ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY"],
        ["Email Digest",  "SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, DIGEST_ENABLED"],
        ["Salesforce",    "SF_CLIENT_ID, SF_CLIENT_SECRET, SF_INSTANCE_URL"],
    ]
    story.append(data_table(config_headers, config_rows, col_widths=[110, CONTENT_W - 110]))
    story.append(PageBreak())

    # ── SECTION 14: Testing Architecture ──────────────────────────────────
    story.append(h1("14. Testing Architecture"))
    story.append(section_hr())

    story.append(body(
        "Framework: pytest with pytest-asyncio. "
        "Runner: <font name='Courier'>poetry run pytest tests/</font>."))
    story.append(spacer(8))

    story.append(h2("Isolation Strategy"))
    isolation = [
        ("<b>Test database:</b>", "In-memory SQLite (<font name='Courier'>sqlite:///:memory:</font>) for all API tests — no external dependencies."),
        ("<b>Auth:</b>",          "FastAPI dependency overrides for get_current_user and get_db — tests inject mock users and sessions."),
        ("<b>Neo4j:</b>",         "MagicMock with side_effect chains for sequential query results."),
    ]
    for label, desc in isolation:
        tbl = Table([[Paragraph(label, S_TABLE_CELL_BOLD), Paragraph(desc, S_TABLE_CELL)]],
                    colWidths=[110, CONTENT_W - 110])
        tbl.setStyle(TableStyle([
            ('VALIGN',       (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ]))
        story.append(tbl)
    story.append(spacer(10))

    story.append(h2("Test Suite"))
    test_headers = ["Test File", "Tests", "Area"]
    test_rows = [
        ["test_portfolio.py",       "50",  "Portfolio view, InsightSnapshot, scoring helpers"],
        ["test_digest.py",          "20",  "Email digest, recipients, HTML builder, SMTP"],
        ["test_copilot_actions.py", "18",  "Copilot action loop, create-action endpoint, intent classification"],
        ["test_connectors.py",      "20",  "OAuth2 flow, credential storage, connector status"],
        ["test_access.py",          "24",  "Multi-tenant access grant/revoke, home tenant protection"],
        ["Total",                   "132", "All passing, 0 failures"],
    ]
    test_tbl_data = [
        [Paragraph(h, S_TABLE_HEADER) for h in test_headers]
    ]
    for i, row in enumerate(test_rows):
        style = S_TABLE_CELL_BOLD if row[0] == "Total" else S_TABLE_CELL
        test_tbl_data.append([Paragraph(str(c), style) for c in row])

    test_tbl = Table(test_tbl_data, colWidths=[160, 50, CONTENT_W - 210], repeatRows=1)
    style_cmds = [
        ('BACKGROUND',   (0, 0), (-1, 0), NAVY),
        ('LINEBELOW',    (0, 0), (-1, 0), 1.2, GREEN),
        ('BACKGROUND',   (0, len(test_rows)), (-1, len(test_rows)), HexColor('#E8F8F0')),
        ('LINEABOVE',    (0, len(test_rows)), (-1, len(test_rows)), 1, GREEN),
        ('GRID',         (0, 0), (-1, -1), 0.4, MIDGRAY),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for i in range(1, len(test_rows)):
        bg = LIGHTGRAY if i % 2 == 1 else WHITE
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))
    test_tbl.setStyle(TableStyle(style_cmds))
    story.append(test_tbl)
    story.append(spacer(12))

    story.append(h2("Standard Test Pattern"))
    for line in [
        "TestingEngine = create_engine('sqlite:///:memory:',",
        "                connect_args={'check_same_thread': False})",
        "Base.metadata.create_all(TestingEngine)  # all tables in memory",
        "app.dependency_overrides[get_db] = override_get_db",
        "app.dependency_overrides[get_current_user] = lambda: mock_admin_user",
        "TestClient(app)  # for HTTP assertions",
    ]:
        story.append(code(line))

    return story


# ── DOCUMENT BUILD ────────────────────────────────────────────────────────────

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 20,  # extra bottom room for footer
        title="Miragent Technical Architecture",
        author="Miragent Engineering",
        subject="Technical Architecture Reference v0.83.0",
    )

    story = build_story()
    doc.build(story, canvasmaker=PageNumCanvas)
    print(f"PDF written: {OUTPUT_PATH}")
    size_kb = os.path.getsize(OUTPUT_PATH) // 1024
    print(f"File size: {size_kb} KB")


if __name__ == "__main__":
    build_pdf()
