"""
Miragent Platform Functionality Guide — PDF Generator
Produces a print-ready US Letter PDF using ReportLab Platypus.
"""

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
import os

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OUTPUT_PATH = "/Users/shahriarrafimayeri/Downloads/Miragent_Platform_Functionality.pdf"
MARGIN = 0.75 * inch  # 54pt

NAVY   = colors.HexColor("#1B2A4A")
GREEN  = colors.HexColor("#2ECC71")
LGRAY  = colors.HexColor("#F4F6F9")
MGRAY  = colors.HexColor("#8A94A6")
DGRAY  = colors.HexColor("#4A5568")
WHITE  = colors.white
BLACK  = colors.black
BORDER = colors.HexColor("#D1D9E6")

PAGE_W, PAGE_H = LETTER

# ---------------------------------------------------------------------------
# Footer canvas
# ---------------------------------------------------------------------------
class PageNumCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(self._pageNumber, num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_footer(self, page_num, total):
        self.saveState()
        # Thin separator line
        self.setStrokeColor(BORDER)
        self.setLineWidth(0.5)
        y_line = MARGIN - 14
        self.line(MARGIN, y_line, PAGE_W - MARGIN, y_line)

        # Footer text
        self.setFont("Helvetica", 7.5)
        self.setFillColor(MGRAY)
        left_text = "Miragent Platform — Functionality Guide"
        center_text = f"Page {page_num}"
        right_text = "Confidential"
        self.drawString(MARGIN, y_line - 10, left_text)
        self.drawCentredString(PAGE_W / 2, y_line - 10, center_text)
        self.drawRightString(PAGE_W - MARGIN, y_line - 10, right_text)
        self.restoreState()


# ---------------------------------------------------------------------------
# Style definitions
# ---------------------------------------------------------------------------
def build_styles():
    base = getSampleStyleSheet()

    styles = {}

    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        fontName="Helvetica-Bold",
        fontSize=52,
        textColor=NAVY,
        leading=58,
        spaceAfter=10,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub",
        fontName="Helvetica",
        fontSize=20,
        textColor=DGRAY,
        leading=26,
        spaceAfter=8,
    )
    styles["cover_tagline"] = ParagraphStyle(
        "cover_tagline",
        fontName="Helvetica-Oblique",
        fontSize=12,
        textColor=MGRAY,
        leading=16,
        spaceAfter=6,
    )
    styles["cover_version"] = ParagraphStyle(
        "cover_version",
        fontName="Helvetica",
        fontSize=10,
        textColor=MGRAY,
        leading=14,
        spaceAfter=20,
    )
    styles["cover_box_text"] = ParagraphStyle(
        "cover_box_text",
        fontName="Helvetica",
        fontSize=11,
        textColor=WHITE,
        leading=17,
    )
    styles["h1"] = ParagraphStyle(
        "h1",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=NAVY,
        leading=24,
        spaceBefore=14,
        spaceAfter=8,
    )
    styles["h2"] = ParagraphStyle(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=NAVY,
        leading=18,
        spaceBefore=10,
        spaceAfter=4,
    )
    styles["body"] = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=10,
        textColor=BLACK,
        leading=15,
        spaceAfter=6,
    )
    styles["bullet"] = ParagraphStyle(
        "bullet",
        fontName="Helvetica",
        fontSize=10,
        textColor=BLACK,
        leading=15,
        leftIndent=18,
        firstLineIndent=0,
        spaceAfter=3,
        bulletIndent=6,
    )
    styles["sub_bullet"] = ParagraphStyle(
        "sub_bullet",
        fontName="Helvetica",
        fontSize=9.5,
        textColor=DGRAY,
        leading=14,
        leftIndent=34,
        firstLineIndent=0,
        spaceAfter=2,
        bulletIndent=22,
    )
    styles["toc_title"] = ParagraphStyle(
        "toc_title",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=NAVY,
        leading=24,
        spaceAfter=16,
    )
    styles["toc_item"] = ParagraphStyle(
        "toc_item",
        fontName="Helvetica",
        fontSize=10.5,
        textColor=BLACK,
        leading=18,
        leftIndent=0,
    )
    styles["toc_item_bold"] = ParagraphStyle(
        "toc_item_bold",
        fontName="Helvetica-Bold",
        fontSize=10.5,
        textColor=NAVY,
        leading=18,
    )
    styles["gray_box_text"] = ParagraphStyle(
        "gray_box_text",
        fontName="Helvetica",
        fontSize=10,
        textColor=BLACK,
        leading=15,
    )
    styles["section_label"] = ParagraphStyle(
        "section_label",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=GREEN,
        leading=12,
        spaceAfter=2,
        spaceBefore=2,
    )
    styles["caption"] = ParagraphStyle(
        "caption",
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        textColor=MGRAY,
        leading=12,
        spaceAfter=4,
    )

    return styles


# ---------------------------------------------------------------------------
# Helper flowables
# ---------------------------------------------------------------------------
def navy_box(content_para, styles):
    """A navy background box with white text."""
    t = Table([[content_para]], colWidths=[PAGE_W - 2 * MARGIN - 2])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
    ]))
    return t


def gray_box(content_para, styles):
    """A light gray info box."""
    t = Table([[content_para]], colWidths=[PAGE_W - 2 * MARGIN - 2])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LGRAY),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return t


def green_rule():
    return HRFlowable(
        width="100%", thickness=2, color=GREEN,
        spaceAfter=6, spaceBefore=2
    )


def light_rule():
    return HRFlowable(
        width="100%", thickness=0.5, color=BORDER,
        spaceAfter=4, spaceBefore=4
    )


def bullets(items, styles, sub=False):
    style = styles["sub_bullet"] if sub else styles["bullet"]
    return [Paragraph(f"• {item}", style) for item in items]


def worker_table(groups):
    """Render a two-column table of worker categories."""
    data = [["Category", "Workers"]]
    for cat, workers in groups:
        data.append([cat, ", ".join(workers)])
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.28, 0.72]]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 1), (-1, -1), BLACK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def connector_table(categories):
    """Render connector list as a multi-column table."""
    data = [["Category", "Systems"]]
    for cat, systems in categories:
        data.append([cat, " · ".join(systems)])
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.22, 0.78]]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 1), (-1, -1), BLACK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def build_story(styles):
    story = []

    # -----------------------------------------------------------------------
    # PAGE 1 — COVER
    # -----------------------------------------------------------------------
    # Push content down ~2.2 inches
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("Miragent", styles["cover_title"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Platform Functionality Guide", styles["cover_sub"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Complete feature reference across all 40+ capabilities",
        styles["cover_tagline"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph("v0.83.0 — May 2026", styles["cover_version"]))
    story.append(Spacer(1, 0.35 * inch))

    # Navy box
    box_text = (
        "Miragent is a PE operating platform that connects to 31 business systems, "
        "builds a digital twin of each portfolio company, runs 34 AI workers to surface "
        "findings, and fixes problems automatically — with human approval gates for "
        "high-risk actions."
    )
    story.append(navy_box(Paragraph(box_text, styles["cover_box_text"]), styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # PAGE 2 — TABLE OF CONTENTS
    # -----------------------------------------------------------------------
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Table of Contents", styles["toc_title"]))
    story.append(green_rule())
    story.append(Spacer(1, 8))

    toc_entries = [
        ("1", "Dashboard & Core Navigation"),
        ("2", "Intelligence & Insights Engine"),
        ("3", "Copilot — Natural Language Q&A"),
        ("4", "Portfolio View — Fund-Level Dashboard"),
        ("5", "Mission Control"),
        ("6", "Autonomous Agents (9 Agents)"),
        ("7", "Executive Features — Board Report"),
        ("8", "Health Score & Notifications"),
        ("9", "Scheduling & Automation"),
        ("10", "Knowledge Base & Design Session"),
        ("11", "Communications Analysis"),
        ("12", "User Management & Access Control"),
        ("13", "SSO, MFA & Security"),
        ("14", "Connectors — 31 Business Systems"),
        ("15", "Actions, Approvals & Remediation"),
        ("16", "Email Digest"),
        ("17", "Settings & Integrations"),
    ]

    toc_data = []
    for num, title in toc_entries:
        toc_data.append([
            Paragraph(f"<b>{num}.</b>", styles["toc_item"]),
            Paragraph(title, styles["toc_item"]),
        ])

    toc_table = Table(toc_data, colWidths=[30, PAGE_W - 2 * MARGIN - 34])
    toc_table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.3, BORDER),
    ]))
    story.append(toc_table)
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 1 — Dashboard & Core Navigation
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 1</font>', styles["section_label"]))
    story.append(Paragraph("Dashboard & Core Navigation", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "The Dashboard is the home screen showing real-time signals: scan activity, "
        "top findings summary (CRITICAL / HIGH / MEDIUM / LOW counts), recent action "
        "cards, worker health indicators, and quick-launch links to Insights, Approvals, "
        "and Mission Control.",
        styles["body"]
    ))

    story.append(Paragraph("Navigation Sidebar", styles["h2"]))
    story.append(Paragraph(
        "The sidebar groups all 40+ features into logical clusters for fast access:",
        styles["body"]
    ))
    nav_groups = [
        ("Onboarding", ["Design Session", "Knowledge Base"]),
        ("Operations", ["Mission Control"]),
        ("Core", ["Dashboard", "Insights", "Portfolio", "Copilot", "Users", "Settings"]),
        ("Executive", ["Board Report"]),
        ("Agents", ["9 specialist agents"]),
        ("Intelligence", ["Communications"]),
    ]
    nav_data = [["Group", "Features"]] + [[g, ", ".join(f)] for g, f in nav_groups]
    nav_col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.25, 0.75]]
    nav_table = Table(nav_data, colWidths=nav_col_w, repeatRows=1)
    nav_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(nav_table)
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 2 — Intelligence & Insights Engine
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 2</font>', styles["section_label"]))
    story.append(Paragraph("Intelligence & Insights Engine", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "The <b>/insights</b> endpoint runs all 34 AI workers against the Neo4j digital twin "
        "and produces a comprehensive finding report. The LLM synthesises findings into an "
        "executive memo. Results persist as an <b>InsightSnapshot</b>.",
        styles["body"]
    ))

    story.append(Paragraph("The 34 AI Workers", styles["h2"]))
    worker_groups = [
        ("Sales & Pipeline",    ["ChurnPrediction", "PipelineVelocity", "WinRateAnalysis", "AccountCoverage"]),
        ("Finance & Vendors",   ["VendorBenchmark", "ContractRenewal", "BudgetVariance", "DuplicateSubscriptions"]),
        ("HR & Workforce",      ["WorkforceWorker", "KeyPersonRisk", "AttritionRisk", "HiringVelocity"]),
        ("Compliance & IT",     ["AccessRightSizing", "PolicyCompliance", "SecurityPosture", "DataQuality"]),
        ("Operations",          ["ProcessAdherence", "TicketSLA", "VendorUtilisation", "ChangeVelocity"]),
        ("Executive",           ["RevenueConcentration", "CustomerConcentration", "MarginAnalysis", "RunwayAnalysis"]),
        ("Intelligence",        ["10 additional cross-cutting workers"]),
    ]
    story.append(worker_table(worker_groups))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Output", styles["h2"]))
    story.append(gray_box(Paragraph(
        "<b>292 findings</b> in a typical full scan. Each finding includes: title, description, "
        "severity (CRITICAL / HIGH / MEDIUM / LOW), worker name, and affected entities. "
        "AI memo: ~400-word narrative. InsightSnapshot persisted to SQLite for portfolio view.",
        styles["gray_box_text"]
    ), styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("LLM Providers", styles["h2"]))
    story.append(Paragraph(
        "Anthropic Claude · OpenAI GPT-4o · Google Gemini · Ollama (local). "
        "Fully switchable via config. Falls back to template narrative if LLM unavailable.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 3 — Copilot
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 3</font>', styles["section_label"]))
    story.append(Paragraph("Copilot — Natural Language Q&A", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Ask plain-English questions about any portfolio company. Intent classification "
        "(keyword matching) → pre-written Cypher query against Neo4j → LLM synthesis "
        "→ concise answer. Falls back to InsightSnapshot narrative if graph unavailable.",
        styles["body"]
    ))

    story.append(Paragraph("Six Intent Categories", styles["h2"]))
    intent_data = [
        ["Intent",      "Scope"],
        ["Pipeline",    "Deals, stalled opportunities, win rate"],
        ["Churn",       "At-risk accounts, renewal pressure"],
        ["Workforce",   "Headcount, manager spans, key person risk"],
        ["Vendors",     "SaaS spend, savings opportunities, benchmarks"],
        ["Revenue",     "ARR, expansion, upsell signals"],
        ["Snapshot",    "Catch-all narrative from InsightSnapshot"],
    ]
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.25, 0.75]]
    intent_t = Table(intent_data, colWidths=col_w, repeatRows=1)
    intent_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(intent_t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Copilot to Action Loop", styles["h2"]))
    story.append(Paragraph(
        "After answering, Copilot surfaces 0–3 suggested remediation actions based on data. "
        "One click creates the action. HIGH-risk items auto-route to the Approvals inbox.",
        styles["body"]
    ))
    action_examples = [
        "Stalled deals → reassign accounts (MEDIUM risk)",
        "At-risk customers → schedule meeting (HIGH risk if ARR > $100k)",
        "Underutilised SaaS → cancel subscription (MEDIUM risk)",
    ]
    story.extend(bullets(action_examples, styles))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Supports multi-tenant: operating partners can query any portfolio company "
        "they have been granted access to.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 4 — Portfolio View
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 4</font>', styles["section_label"]))
    story.append(Paragraph("Portfolio View — Fund-Level Dashboard", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Single screen showing health of every portfolio company side by side.",
        styles["body"]
    ))

    story.append(Paragraph("Data Modes", styles["h2"]))
    mode_data = [
        ["Mode",                   "Badge",       "Data Source"],
        ["Full Intelligence",      "Green",       "InsightSnapshot — AI narrative, top findings, vendor savings"],
        ["Graph Signals Only",     "Gray",        "Neo4j heuristics — deal counts, headcount"],
    ]
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.28, 0.12, 0.60]]
    mode_t = Table(mode_data, colWidths=col_w, repeatRows=1)
    mode_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(mode_t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Aggregate Strip", styles["h2"]))
    strip_items = [
        "Total companies and companies with full intelligence",
        "Total CRITICAL and HIGH findings across the fund",
        "Total SaaS spend and total vendor savings opportunity",
    ]
    story.extend(bullets(strip_items, styles))

    story.append(Paragraph("Company Health Cards", styles["h2"]))
    card_items = [
        "Company name, data source badge, severity counts",
        "Health score (0–100)",
        "Top 3 findings",
        "200-character narrative snippet",
        "Vendor savings identified",
        "“Run Intelligence” CTA for graph-only cards",
    ]
    story.extend(bullets(card_items, styles))

    story.append(Spacer(1, 8))
    story.append(gray_box(Paragraph(
        "<b>Multi-tenant:</b> Operating partners see only companies their account "
        "has been explicitly granted access to.",
        styles["gray_box_text"]
    ), styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 5 — Mission Control
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 5</font>', styles["section_label"]))
    story.append(Paragraph("Mission Control", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Operational nerve centre for daily operating reviews. Provides a single-pane view "
        "of all platform activity in real time.",
        styles["body"]
    ))

    story.append(Paragraph("Panels", styles["h2"]))
    panels = [
        ("Worker Health Grid",      "All 34 workers — last-run time and finding counts"),
        ("Action Pipeline Funnel",  "OPEN → IN_PROGRESS → COMPLETE"),
        ("Approval Queue Summary",  "Pending approvals by risk tier"),
        ("Execution Log",           "Last 20 automated actions"),
        ("System Health",           "Connector status, graph freshness, LLM availability"),
    ]
    panel_data = [["Panel", "Description"]] + list(panels)
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.32, 0.68]]
    panel_t = Table(panel_data, colWidths=col_w, repeatRows=1)
    panel_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(panel_t)
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 6 — Autonomous Agents
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 6</font>', styles["section_label"]))
    story.append(Paragraph("Autonomous Agents (9 Agents)", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Each agent is a focused conversational AI handling a specific operational workflow "
        "end-to-end. Agents use the knowledge base, Neo4j graph, and InsightSnapshot data "
        "to produce answers and trigger actions.",
        styles["body"]
    ))

    agents = [
        ("DDQ Agent v2",
         "Automates due diligence questionnaire responses. Upload DDQ, agent maps "
         "questions to knowledge base and graph data, drafts answers, flags gaps. "
         "Status lifecycle: PENDING → PROCESSING → COMPLETE."),
        ("Payroll Documents",
         "Processes payroll documents, extracts structured data, validates against "
         "HR records, flags discrepancies."),
        ("Portal Access",
         "Manages access requests to portfolio portals, routes through approval workflow, "
         "automatically provisions approved access."),
        ("Support Triage",
         "Classifies inbound support requests by urgency and category, routes to the right "
         "team, suggests KB articles for self-service resolution."),
        ("Payment Status",
         "Tracks payment status across vendors and customers, surfaces overdue invoices "
         "and at-risk receivables. Integrates with NetSuite and Bill.com."),
        ("Benefits",
         "Manages employee benefits queries and enrolment, answers questions using the "
         "knowledge base, escalates edge cases to HR."),
        ("Vendor Onboarding",
         "Guides new vendors through onboarding, collects required documentation, checks "
         "compliance requirements, triggers integration setup."),
        ("IT Access",
         "Handles IT access requests (new joiner provisioning, role changes, offboarding). "
         "Integrates with Okta and Azure AD; routes high-privilege requests to Approvals."),
        ("Compliance Response",
         "Drafts responses to compliance questionnaires and audit requests using knowledge "
         "base and InsightSnapshot data. Tracks response status."),
    ]

    for name, desc in agents:
        story.append(KeepTogether([
            Paragraph(name, styles["h2"]),
            Paragraph(desc, styles["body"]),
            Spacer(1, 4),
        ]))

    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 7 — Board Report
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 7</font>', styles["section_label"]))
    story.append(Paragraph("Executive Features — Board Report", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Auto-generates a board-ready portfolio health report from InsightSnapshot data "
        "across all companies. One click → formatted report.",
        styles["body"]
    ))

    story.append(Paragraph("Report Contents", styles["h2"]))
    board_items = [
        "Fund-level summary: companies, aggregate findings, total spend",
        "Per-company health snapshot: top findings, actions taken, improvement vs. last period",
        "Risk heat map across the fund",
        "Vendor savings identified and realised",
        "Recommended focus areas for next 90 days",
    ]
    story.extend(bullets(board_items, styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 8 — Health Score & Notifications
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 8</font>', styles["section_label"]))
    story.append(Paragraph("Health Score & Notifications", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Health Score", styles["h2"]))
    story.append(Paragraph(
        "0–100 score per company. Weighted inputs:",
        styles["body"]
    ))
    hs_items = [
        "Finding severity mix (critical / high count weighted most heavily)",
        "Action completion rate",
        "Data freshness (time since last successful sync)",
        "Connector health (connected vs. failing connectors)",
    ]
    story.extend(bullets(hs_items, styles))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Notification Center", styles["h2"]))
    story.append(Paragraph(
        "Centralised feed for all platform events. Badge count visible in sidebar.",
        styles["body"]
    ))
    notif_items = [
        "New critical findings",
        "Pending approvals",
        "Scheduled run completions",
        "Action status changes",
    ]
    story.extend(bullets(notif_items, styles))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Supports mark-as-read and filter by event type.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 9 — Scheduling & Automation
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 9</font>', styles["section_label"]))
    story.append(Paragraph("Scheduling & Automation", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Insight Scheduling", styles["h2"]))
    story.append(Paragraph(
        "Per-company automatic insight runs. Three cadences:",
        styles["body"]
    ))
    story.extend(bullets([
        "Daily — specified UTC hour",
        "Weekly — specified day and UTC hour",
        "Manual — on-demand only",
    ], styles))

    story.append(Paragraph("Background Scheduler", styles["h2"]))
    story.append(Paragraph(
        "Daemon thread with a 60-second tick. Checks all schedules every minute and fires "
        "due runs one company per tick to avoid Neo4j overload.",
        styles["body"]
    ))

    story.append(Paragraph("Email Digest Automation", styles["h2"]))
    story.append(Paragraph(
        "Every Monday at 06:00 UTC, an HTML digest email is sent automatically to all "
        "configured recipients. Send on demand via <b>POST /digest/send-now</b>.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 10 — Knowledge Base & Design Session
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 10</font>', styles["section_label"]))
    story.append(Paragraph("Knowledge Base & Design Session", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Knowledge Base", styles["h2"]))
    story.append(Paragraph(
        "Stores internal documents, policies, and reference material. Documents are "
        "chunked and stored in <b>Weaviate</b> for semantic vector search. Used by the "
        "DDQ Agent and Compliance Response Agent.",
        styles["body"]
    ))
    story.extend(bullets(["Upload documents", "Semantic search", "Delete documents"], styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Design Session", styles["h2"]))
    story.append(Paragraph(
        "Interactive onboarding mode for configuring Miragent for a new portfolio company. "
        "Walks through:",
        styles["body"]
    ))
    ds_items = [
        "Connector selection",
        "Worker configuration",
        "Playbook rules",
        "Approval thresholds",
        "Notification preferences",
    ]
    story.extend(bullets(ds_items, styles))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Outputs a full configuration blueprint for the company.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 11 — Communications Analysis
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 11</font>', styles["section_label"]))
    story.append(Paragraph("Communications Analysis", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Analyses communication patterns across email and messaging to surface relationship "
        "health signals across the portfolio.",
        styles["body"]
    ))

    story.append(Paragraph("Key Signals", styles["h2"]))
    signal_items = [
        "Account relationship health (communication frequency vs. account health score)",
        "Internal collaboration patterns",
        "Executive attention allocation",
        "Response time trends",
        "Key person single points of failure in customer relationships",
    ]
    story.extend(bullets(signal_items, styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 12 — User Management & Access Control
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 12</font>', styles["section_label"]))
    story.append(Paragraph("User Management & Access Control", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("User Management", styles["h2"]))
    story.append(Paragraph(
        "Full CRUD for users: create, read, update, deactivate. Password hashing via "
        "bcrypt. JWT authentication. API key management for service accounts.",
        styles["body"]
    ))
    story.append(Paragraph("Roles:", styles["body"]))
    story.extend(bullets([
        "<b>admin</b> — full platform access",
        "<b>user</b> — read access + own tenant",
    ], styles))

    story.append(Paragraph("Multi-Tenant Access", styles["h2"]))
    story.append(Paragraph(
        "Each user belongs to a home tenant. Admins grant access to additional tenants via "
        "<b>UserTenantAccess</b>. The <b>GET /access/my-tenants</b> endpoint returns all "
        "tenants the current user can query. The revoke endpoint prevents locking users "
        "out of their home tenant.",
        styles["body"]
    ))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 13 — SSO, MFA & Security
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 13</font>', styles["section_label"]))
    story.append(Paragraph("SSO, MFA & Security", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Single Sign-On (SSO)", styles["h2"]))
    story.append(Paragraph(
        "Enterprise SSO via <b>SAML 2.0</b> and <b>OIDC</b>. Supported identity providers: "
        "Okta, Azure AD, Google Workspace. A domain-check endpoint auto-detects the SSO "
        "provider for an email domain.",
        styles["body"]
    ))

    story.append(Paragraph("Multi-Factor Authentication (MFA)", styles["h2"]))
    story.extend(bullets([
        "TOTP-based MFA (authenticator app)",
        "Enrol via QR code, verify with 6-digit codes",
        "Recovery codes issued at enrolment",
        "Admins can enforce MFA for all users",
    ], styles))

    story.append(Paragraph("Security Middleware Stack", styles["h2"]))
    story.append(Paragraph("Applied to every request:", styles["body"]))
    mw_data = [
        ["Middleware",              "Function"],
        ["SecurityHeadersMiddleware", "X-Content-Type-Options, X-Frame-Options, HSTS"],
        ["AuditLogMiddleware",      "Every call logged with user / tenant / IP / timestamp"],
        ["RateLimitMiddleware",     "60 requests / minute per tenant"],
        ["JWT Validation",          "Token verification on all protected endpoints"],
    ]
    col_w = [(PAGE_W - 2 * MARGIN) * f for f in [0.36, 0.64]]
    mw_t = Table(mw_data, colWidths=col_w, repeatRows=1)
    mw_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(mw_t)
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 14 — Connectors
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 14</font>', styles["section_label"]))
    story.append(Paragraph("Connectors — 31 Business Systems", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    connector_cats = [
        ("CRM",               ["Salesforce", "HubSpot", "Dynamics CRM", "Pipedrive", "Zoho"]),
        ("HR / HCM",          ["Workday", "ADP", "Rippling", "BambooHR", "Gusto", "UKG"]),
        ("ERP / Finance",     ["NetSuite", "SAP", "Oracle ERP", "Dynamics 365", "Dynamics Finance",
                                "QuickBooks", "Sage Intacct", "Acumatica"]),
        ("Identity / IAM",    ["Okta", "Azure AD", "JumpCloud", "Google Workspace"]),
        ("ITSM",              ["ServiceNow", "Jira", "Freshservice", "Zendesk"]),
        ("Spend / Procure",   ["Coupa", "Ramp", "Brex", "Concur", "Bill.com"]),
    ]
    story.append(connector_table(connector_cats))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Connector Framework", styles["h2"]))
    story.append(Paragraph(
        "Every connector implements a standard interface: <b>connect()</b>, "
        "<b>fetch_data()</b>, <b>health_check()</b>, <b>discover_schema()</b>. "
        "A normaliser standardises fields. A resolver deduplicates entities across "
        "connectors. Mock connectors for development — swap to live with one config change.",
        styles["body"]
    ))

    story.append(Paragraph("Salesforce Live Connector (Sprint 83)", styles["h2"]))
    sf_items = [
        "Full OAuth2 flow with credential storage in SQLite",
        "SOQL queries for Users, Accounts, and Opportunities with incremental sync",
        "Rate limited to 5 calls / sec",
        "Test Connection button in Settings UI",
    ]
    story.extend(bullets(sf_items, styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 15 — Actions, Approvals & Remediation
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 15</font>', styles["section_label"]))
    story.append(Paragraph("Actions, Approvals & Remediation", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Remediation Actions", styles["h2"]))
    story.append(Paragraph(
        "Each finding generates a remediation action with:",
        styles["body"]
    ))
    ra_items = [
        "<b>Risk tier:</b> LOW / MEDIUM / HIGH / BLOCKED",
        "<b>Status lifecycle:</b> OPEN → IN_PROGRESS → COMPLETE / DEFERRED / CANCELLED",
        "<b>Evidence verification:</b> system checks source systems for organic completion",
        "<b>Execution payload:</b> exact parameters for the executor",
    ]
    story.extend(bullets(ra_items, styles))

    story.append(Paragraph("Approval Workflow", styles["h2"]))
    story.append(Paragraph(
        "HIGH-risk actions create an <b>ApprovalRequest</b> routed to the Approvals inbox. "
        "Approvers review context, then approve or reject. On approval, the executor runs "
        "against the source system. On rejection, the action is marked DEFERRED with notes.",
        styles["body"]
    ))

    story.append(Paragraph("Audit Trail", styles["h2"]))
    story.append(Paragraph(
        "Every automated action is logged with outcome, timestamp, and evidence — "
        "SOC 2 compliant audit trail.",
        styles["body"]
    ))

    story.append(Spacer(1, 8))
    story.append(gray_box(Paragraph(
        "<b>Copilot Action Loop:</b> Copilot surfaces suggested actions inline after "
        "answering a question. One click creates the action. HIGH-risk items auto-route "
        "to Approvals with full context pre-populated.",
        styles["gray_box_text"]
    ), styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 16 — Email Digest
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 16</font>', styles["section_label"]))
    story.append(Paragraph("Email Digest", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "Auto-generated Monday morning portfolio health email sent at <b>06:00 UTC</b>.",
        styles["body"]
    ))

    story.append(Paragraph("Email Structure", styles["h2"]))
    story.append(Paragraph(
        '<b>Subject:</b> "Miragent Portfolio Digest — Mon DD Mon YYYY"',
        styles["body"]
    ))
    digest_items = [
        "Fund-level summary strip: total companies, companies with critical findings, total findings, average health score",
        "Per-company cards: name, severity counts, top 3 findings, narrative snippet, health score",
        "Unsubscribe footer",
    ]
    story.extend(bullets(digest_items, styles))

    story.append(Paragraph("Recipient Types", styles["h2"]))
    story.extend(bullets([
        "<b>Portfolio-wide</b> — receives full fund digest",
        "<b>Scoped</b> — receives only their company’s section",
    ], styles))

    story.append(Paragraph("Admin Endpoints", styles["h2"]))
    story.extend(bullets([
        "GET / POST / DELETE /digest/recipients",
        "POST /digest/send-now",
    ], styles))
    story.append(PageBreak())

    # -----------------------------------------------------------------------
    # SECTION 17 — Settings & Integrations
    # -----------------------------------------------------------------------
    story.append(Paragraph('<font color="#2ECC71">SECTION 17</font>', styles["section_label"]))
    story.append(Paragraph("Settings & Integrations", styles["h1"]))
    story.append(green_rule())
    story.append(Spacer(1, 4))

    story.append(Paragraph("Settings", styles["h2"]))
    settings_items = [
        "<b>Profile:</b> name, email, password change",
        "<b>Tenant configuration:</b> company name, timezone, default cadence",
        "<b>Notification preferences:</b> channels, severity thresholds",
        "<b>Worker configuration:</b> enable / disable workers, override thresholds",
        "<b>Playbook rules:</b> risk tier assignments for each action type",
    ]
    story.extend(bullets(settings_items, styles))

    story.append(Paragraph("Integrations", styles["h2"]))
    story.append(Paragraph(
        "The Integrations section of Settings surfaces connector status and controls.",
        styles["body"]
    ))
    integ_items = [
        "Salesforce connector: Connected / Not Connected badge, last-connected timestamp",
        "Connect / Disconnect / Test Connection buttons",
        "Framework supports adding all 31 connectors to the same UI",
    ]
    story.extend(bullets(integ_items, styles))

    story.append(Spacer(1, 20))
    story.append(light_rule())
    story.append(Spacer(1, 8))
    story.append(navy_box(Paragraph(
        "This document covers all 17 functional areas and 40+ features of the Miragent "
        "platform as of v0.83.0. For API reference, connector-specific documentation, "
        "or deployment guides, contact the Miragent engineering team.",
        styles["cover_box_text"]
    ), styles))

    return story


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    styles = build_styles()
    story = build_story(styles)

    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=LETTER,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 22,  # extra space for footer
        title="Miragent Platform Functionality Guide",
        author="Miragent",
        subject="Platform Functionality Guide v0.83.0",
    )

    doc.build(story, canvasmaker=PageNumCanvas)
    print(f"PDF written to: {OUTPUT_PATH}")
    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"File size: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
