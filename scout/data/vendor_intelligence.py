"""
scout/data/vendor_intelligence.py — Static vendor intelligence database.

A curated catalog of ~60 common B2B SaaS tools that Miragent's workers
use to enrich vendor analysis, negotiation recommendations, and competitive
intelligence.

Usage:
    from scout.data.vendor_intelligence import (
        lookup_vendor,
        get_negotiation_tips,
        get_alternatives,
        get_category_vendors,
        VENDOR_CATALOG,
    )

Each entry in VENDOR_CATALOG is keyed by a normalized slug (lowercase, hyphenated).
Lookup is case-insensitive and supports fuzzy matching on common name variations.
"""

from __future__ import annotations

import re

# ── Required keys that every VENDOR_CATALOG entry must contain ────────────────
REQUIRED_KEYS = frozenset({
    "canonical_name",
    "category",
    "pricing_model",
    "alternatives",
    "negotiation_leverage",
})

# ── Vendor catalog ────────────────────────────────────────────────────────────

VENDOR_CATALOG: dict[str, dict] = {

    # ── CRM ───────────────────────────────────────────────────────────────────

    "salesforce": {
        "canonical_name": "Salesforce",
        "category": "CRM",
        "subcategory": "Enterprise CRM",
        "typical_use_cases": [
            "Sales pipeline management",
            "Customer data platform",
            "Service Cloud (support ticketing)",
            "Marketing Cloud",
        ],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 15_000, "mid_market": 80_000, "enterprise": 250_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Multi-year deal for 15–25% discount",
            "End-of-quarter pressure (Salesforce reps have aggressive quotas)",
            "Bundle with Tableau or MuleSoft for additional discount",
            "Seat count true-up: audit active vs. licensed users before renewal",
            "Competitive bake-off with HubSpot or Microsoft Dynamics",
        ],
        "alternatives": ["hubspot", "microsoft-dynamics", "pipedrive", "zoho-crm"],
        "red_flags": [
            "Seat count significantly exceeds active users (>20% gap)",
            "Unused Clouds in contract (Marketing Cloud, Service Cloud)",
            "Auto-renew clause with short cancellation window",
            "License tier higher than needed (Enterprise vs. Professional)",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 20,
    },

    "hubspot": {
        "canonical_name": "HubSpot",
        "category": "CRM",
        "subcategory": "SMB/Mid-Market CRM",
        "typical_use_cases": [
            "Sales CRM for SMB and mid-market",
            "Marketing automation (email, landing pages)",
            "Service Hub (support tickets)",
            "Content management",
        ],
        "pricing_model": "per-seat + contact tier",
        "typical_contract_size": {"smb": 6_000, "mid_market": 30_000, "enterprise": 80_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Contact tier negotiation — unused contact capacity is negotiable",
            "Bundle Sales + Marketing + Service Hub for multi-hub discount",
            "Competitive offer from Salesforce Professional tier",
            "Annual prepay for 10–15% discount vs. monthly",
        ],
        "alternatives": ["salesforce", "pipedrive", "zoho-crm", "freshsales"],
        "red_flags": [
            "Contact database growing faster than tier, unexpected overage charges",
            "Paying for Enterprise when Professional features are sufficient",
        ],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "pipedrive": {
        "canonical_name": "Pipedrive",
        "category": "CRM",
        "subcategory": "SMB CRM",
        "typical_use_cases": ["Sales pipeline visualization", "Deal management", "Email integration"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 3_000, "mid_market": 12_000, "enterprise": 30_000},
        "renewal_cycle": "monthly or annual",
        "negotiation_leverage": [
            "Annual prepay for 17% discount",
            "Competitive pressure from HubSpot CRM (free tier)",
        ],
        "alternatives": ["hubspot", "salesforce", "zoho-crm"],
        "red_flags": ["Limited reporting vs. enterprise needs"],
        "g2_category_rank": 5,
        "typical_discount_pct": 17,
    },

    "microsoft-dynamics": {
        "canonical_name": "Microsoft Dynamics 365",
        "category": "CRM",
        "subcategory": "Enterprise CRM",
        "typical_use_cases": ["Enterprise CRM", "ERP integration", "Field service"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 20_000, "mid_market": 100_000, "enterprise": 400_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Microsoft 365 bundle discount",
            "Enterprise Agreement (EA) consolidation",
            "End-of-fiscal-year (June 30) pressure",
        ],
        "alternatives": ["salesforce", "hubspot", "zoho-crm"],
        "red_flags": ["Complex licensing — ensure correct module selection"],
        "g2_category_rank": 3,
        "typical_discount_pct": 18,
    },

    # ── HRIS ──────────────────────────────────────────────────────────────────

    "workday": {
        "canonical_name": "Workday",
        "category": "HRIS",
        "subcategory": "Enterprise HCM",
        "typical_use_cases": [
            "HR core (people records, org chart)",
            "Payroll processing",
            "Talent management and succession planning",
            "Financial management (Workday Financials)",
            "Workforce analytics",
        ],
        "pricing_model": "per-employee",
        "typical_contract_size": {"smb": 50_000, "mid_market": 200_000, "enterprise": 800_000},
        "renewal_cycle": "annual (3–5 year terms common)",
        "negotiation_leverage": [
            "Multi-year deal (3-year) for 20–30% discount",
            "Phased module rollout to reduce initial cost",
            "Competitive bake-off with SAP SuccessFactors or Oracle HCM",
            "Audit worker count — inactive/contractors can inflate seat count",
        ],
        "alternatives": ["bamboohr", "rippling", "adp", "sap-successfactors", "oracle-hcm"],
        "red_flags": [
            "Implementation costs often 2–3x software cost — audit SI partner",
            "Module creep: paying for Adaptive Planning without using it",
            "Worker count includes contractors — verify what's billable",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 22,
    },

    "bamboohr": {
        "canonical_name": "BambooHR",
        "category": "HRIS",
        "subcategory": "SMB HCM",
        "typical_use_cases": ["HR records for SMB", "Time tracking", "Performance reviews", "Onboarding"],
        "pricing_model": "per-employee",
        "typical_contract_size": {"smb": 8_000, "mid_market": 28_000, "enterprise": 60_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Annual prepay discount",
            "Competitive quote from Rippling or Gusto",
            "Module removal if performance/ATS features unused",
        ],
        "alternatives": ["rippling", "gusto", "workday", "adp"],
        "red_flags": ["Limited scalability beyond ~500 employees"],
        "g2_category_rank": 4,
        "typical_discount_pct": 12,
    },

    "rippling": {
        "canonical_name": "Rippling",
        "category": "HRIS",
        "subcategory": "All-in-One HR/IT",
        "typical_use_cases": ["HR + IT unified platform", "Payroll", "Device management", "App provisioning"],
        "pricing_model": "per-employee per module",
        "typical_contract_size": {"smb": 10_000, "mid_market": 35_000, "enterprise": 90_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Bundle HR + IT modules for discount",
            "Competitive pressure from Workday or BambooHR",
        ],
        "alternatives": ["bamboohr", "workday", "gusto", "adp"],
        "red_flags": ["Module proliferation — audit which modules are actively used"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "gusto": {
        "canonical_name": "Gusto",
        "category": "Payroll / HR",
        "subcategory": "SMB Payroll",
        "typical_use_cases": ["Payroll", "Benefits administration", "Compliance"],
        "pricing_model": "per-employee + base fee",
        "typical_contract_size": {"smb": 6_000, "mid_market": 22_000, "enterprise": 50_000},
        "renewal_cycle": "monthly",
        "negotiation_leverage": [
            "Annual prepay for discount",
            "Competitive bake-off with ADP Run or Rippling",
        ],
        "alternatives": ["rippling", "adp", "bamboohr", "paychex"],
        "red_flags": ["Limited scalability for complex multi-state payroll"],
        "g2_category_rank": 3,
        "typical_discount_pct": 10,
    },

    "adp": {
        "canonical_name": "ADP",
        "category": "Payroll / HR",
        "subcategory": "Enterprise Payroll",
        "typical_use_cases": ["Enterprise payroll", "Time and attendance", "Benefits", "Compliance"],
        "pricing_model": "per-employee",
        "typical_contract_size": {"smb": 12_000, "mid_market": 45_000, "enterprise": 150_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Long-term relationship — push for loyalty discount",
            "Competitive bake-off with Rippling or Workday",
            "Module rationalization",
        ],
        "alternatives": ["rippling", "workday", "gusto", "paychex"],
        "red_flags": ["Legacy platform — implementation complexity"],
        "g2_category_rank": 6,
        "typical_discount_pct": 12,
    },

    # ── ERP ───────────────────────────────────────────────────────────────────

    "netsuite": {
        "canonical_name": "Oracle NetSuite",
        "category": "ERP",
        "subcategory": "Cloud ERP",
        "typical_use_cases": [
            "General ledger and financial close",
            "Accounts payable / receivable",
            "Inventory and order management",
            "Revenue recognition (ASC 606)",
            "Multi-subsidiary consolidation",
        ],
        "pricing_model": "per-user + module licensing",
        "typical_contract_size": {"smb": 30_000, "mid_market": 95_000, "enterprise": 300_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Multi-year commitment for 15–20% discount",
            "Module audit: remove unused modules at renewal",
            "Oracle fiscal year end (May 31) creates urgency",
            "Competitive quote from Sage Intacct for mid-market leverage",
        ],
        "alternatives": ["sage-intacct", "quickbooks", "microsoft-dynamics", "acumatica"],
        "red_flags": [
            "User count includes read-only users — often over-licensed",
            "Advanced modules (WMS, Manufacturing) may be unused",
            "SuiteSuccess tier may include features you won't use",
        ],
        "g2_category_rank": 2,
        "typical_discount_pct": 18,
    },

    "sage-intacct": {
        "canonical_name": "Sage Intacct",
        "category": "ERP",
        "subcategory": "Cloud Accounting",
        "typical_use_cases": ["Financial management for mid-market", "Multi-entity consolidation", "Revenue recognition"],
        "pricing_model": "per-user + module",
        "typical_contract_size": {"smb": 15_000, "mid_market": 42_000, "enterprise": 120_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Competitive pressure from NetSuite",
            "Annual prepay discount",
            "Bundle with Salesforce for Sage-SFDC integration discount",
        ],
        "alternatives": ["netsuite", "quickbooks", "acumatica"],
        "red_flags": ["Limited manufacturing/inventory capabilities"],
        "g2_category_rank": 3,
        "typical_discount_pct": 15,
    },

    # ── Analytics / BI ────────────────────────────────────────────────────────

    "tableau": {
        "canonical_name": "Tableau",
        "category": "Analytics",
        "subcategory": "Business Intelligence",
        "typical_use_cases": ["Data visualization", "Self-service BI", "Executive dashboards", "Embedded analytics"],
        "pricing_model": "per-seat (Creator/Explorer/Viewer tiers)",
        "typical_contract_size": {"smb": 20_000, "mid_market": 65_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Bundle with Salesforce (same parent company) for 20–30% discount",
            "Viewer seats often go unused — right-size before renewal",
            "Competitive quote from Looker or Power BI",
            "End-of-Salesforce-fiscal-quarter pressure",
        ],
        "alternatives": ["looker", "power-bi", "domo", "qlik"],
        "red_flags": [
            "Creator seats for users who only view (should be Viewer seats)",
            "Server vs. Cloud pricing — validate deployment model",
        ],
        "g2_category_rank": 2,
        "typical_discount_pct": 25,
    },

    "looker": {
        "canonical_name": "Looker",
        "category": "Analytics",
        "subcategory": "Business Intelligence",
        "typical_use_cases": ["Self-service analytics", "Embedded analytics", "Data exploration", "LookML modeling"],
        "pricing_model": "per-user + platform fee",
        "typical_contract_size": {"smb": 30_000, "mid_market": 85_000, "enterprise": 300_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Google Cloud bundle discount (Looker is owned by Google)",
            "Competitive quote from Tableau or Power BI",
            "Audit developer vs. viewer seats",
        ],
        "alternatives": ["tableau", "power-bi", "domo", "metabase"],
        "red_flags": ["High implementation cost — LookML expertise required"],
        "g2_category_rank": 3,
        "typical_discount_pct": 20,
    },

    "snowflake": {
        "canonical_name": "Snowflake",
        "category": "Data Platform",
        "subcategory": "Cloud Data Warehouse",
        "typical_use_cases": [
            "Cloud data warehousing",
            "Data sharing and marketplace",
            "Data engineering pipelines",
            "ML/AI workloads",
        ],
        "pricing_model": "consumption-based (credits)",
        "typical_contract_size": {"smb": 30_000, "mid_market": 120_000, "enterprise": 500_000},
        "renewal_cycle": "annual commitment (usage-based actual)",
        "negotiation_leverage": [
            "Commit to annual credit volume for 20–30% discount vs. on-demand",
            "Audit compute vs. storage spend — often compute is over-committed",
            "Competitive pressure from Databricks SQL or BigQuery",
            "Multi-year commitment for steeper discount",
        ],
        "alternatives": ["databricks", "bigquery", "redshift", "azure-synapse"],
        "red_flags": [
            "Idle compute clusters — auto-suspend settings not configured",
            "Over-committed credit contract vs. actual usage",
            "Multiple warehouses sized too large for workloads",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 25,
    },

    "databricks": {
        "canonical_name": "Databricks",
        "category": "Data Platform",
        "subcategory": "Data + AI Platform",
        "typical_use_cases": ["Data engineering", "Machine learning", "Streaming analytics", "Delta Lake"],
        "pricing_model": "consumption-based (DBU credits)",
        "typical_contract_size": {"smb": 40_000, "mid_market": 150_000, "enterprise": 600_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": [
            "DBU commit discount — 20–35% vs. on-demand",
            "Cloud provider marketplace credit can offset spend",
            "Competitive bake-off with Snowflake",
        ],
        "alternatives": ["snowflake", "bigquery", "apache-spark-self-hosted"],
        "red_flags": ["Cluster auto-termination — verify configured to prevent runaway costs"],
        "g2_category_rank": 2,
        "typical_discount_pct": 28,
    },

    # ── Productivity / Collaboration ───────────────────────────────────────────

    "microsoft-365": {
        "canonical_name": "Microsoft 365",
        "category": "Productivity",
        "subcategory": "Office Suite",
        "typical_use_cases": ["Email (Outlook)", "Productivity (Word, Excel, PowerPoint)", "Teams collaboration", "SharePoint"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 15_000, "mid_market": 85_000, "enterprise": 300_000},
        "renewal_cycle": "annual (EA or CSP)",
        "negotiation_leverage": [
            "Enterprise Agreement (EA) consolidation discount",
            "Downgrade E5 to E3 for non-power users (saves ~$12/seat/mo)",
            "Teams Phone System add-on often unused — remove",
            "Azure consumption bundle",
        ],
        "alternatives": ["google-workspace", "slack", "zoom"],
        "red_flags": [
            "E5 license for users who only need email (E1 sufficient)",
            "Unused add-ons (Teams Phone, Defender P2)",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "google-workspace": {
        "canonical_name": "Google Workspace",
        "category": "Productivity",
        "subcategory": "Office Suite",
        "typical_use_cases": ["Gmail", "Google Docs/Sheets/Slides", "Meet", "Drive"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 10_000, "mid_market": 50_000, "enterprise": 180_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Annual prepay for 10% discount",
            "GCP bundle discount",
            "Competitive pressure from Microsoft 365",
        ],
        "alternatives": ["microsoft-365"],
        "red_flags": ["Business Plus vs. Enterprise — audit storage needs"],
        "g2_category_rank": 2,
        "typical_discount_pct": 12,
    },

    "slack": {
        "canonical_name": "Slack",
        "category": "Collaboration",
        "subcategory": "Team Messaging",
        "typical_use_cases": ["Team messaging", "Workflow automation", "App integrations", "Customer channels"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 10_000, "mid_market": 38_000, "enterprise": 120_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Salesforce ownership — bundle with Salesforce CRM for discount",
            "Audit active vs. inactive members before renewal",
            "Competitive threat from Microsoft Teams (often already licensed)",
            "Pro vs. Business+ tier — audit guest channel needs",
        ],
        "alternatives": ["microsoft-365", "google-chat", "discord"],
        "red_flags": [
            "Guest/external members count toward billing",
            "Business+ tier for teams that don't use compliance exports",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

    "zoom": {
        "canonical_name": "Zoom",
        "category": "Video Conferencing",
        "subcategory": "Video Collaboration",
        "typical_use_cases": ["Video meetings", "Webinars", "Phone system", "Events"],
        "pricing_model": "per-host",
        "typical_contract_size": {"smb": 5_000, "mid_market": 22_000, "enterprise": 80_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Host count reduction — many organizations over-license hosts",
            "Competitive pressure from Microsoft Teams (already licensed)",
            "Webinar license audit — often unused",
        ],
        "alternatives": ["microsoft-365", "google-workspace", "webex"],
        "red_flags": [
            "Webinar add-on for infrequent use — consider per-event pricing",
            "Phone System add-on overlap with existing phone system",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "notion": {
        "canonical_name": "Notion",
        "category": "Productivity",
        "subcategory": "Wiki / Knowledge Base",
        "typical_use_cases": ["Company wiki", "Project management", "Docs", "Databases"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 3_000, "mid_market": 12_000, "enterprise": 40_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Annual prepay discount", "Competitive pressure from Confluence"],
        "alternatives": ["confluence", "asana", "monday-com"],
        "red_flags": ["Overlap with existing Confluence or SharePoint"],
        "g2_category_rank": 4,
        "typical_discount_pct": 10,
    },

    "asana": {
        "canonical_name": "Asana",
        "category": "Project Management",
        "subcategory": "Work Management",
        "typical_use_cases": ["Project tracking", "Team task management", "Goals and OKRs"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 5_000, "mid_market": 18_000, "enterprise": 60_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Monday.com or Jira", "Annual prepay"],
        "alternatives": ["monday-com", "jira", "notion"],
        "red_flags": ["Overlap with Jira for engineering teams"],
        "g2_category_rank": 3,
        "typical_discount_pct": 15,
    },

    "monday-com": {
        "canonical_name": "Monday.com",
        "category": "Project Management",
        "subcategory": "Work Management",
        "typical_use_cases": ["Project management", "CRM (lightweight)", "Marketing workflows"],
        "pricing_model": "per-seat (minimum 3 seats)",
        "typical_contract_size": {"smb": 4_000, "mid_market": 20_000, "enterprise": 65_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Annual prepay", "Competitive pressure from Asana or Jira"],
        "alternatives": ["asana", "jira", "notion"],
        "red_flags": ["Minimum seat requirements can force over-purchasing"],
        "g2_category_rank": 4,
        "typical_discount_pct": 15,
    },

    "figma": {
        "canonical_name": "Figma",
        "category": "Design",
        "subcategory": "UI/UX Design",
        "typical_use_cases": ["UI design", "Prototyping", "Design systems", "Developer handoff"],
        "pricing_model": "per-editor (viewers free)",
        "typical_contract_size": {"smb": 5_000, "mid_market": 24_000, "enterprise": 80_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Editor seat audit — many 'editors' are actually viewers",
            "Adobe acquisition attempt raised concerns — competitive pressure",
        ],
        "alternatives": ["sketch", "adobe-xd", "miro"],
        "red_flags": ["Editor count often includes people who should be viewers"],
        "g2_category_rank": 1,
        "typical_discount_pct": 12,
    },

    "miro": {
        "canonical_name": "Miro",
        "category": "Collaboration",
        "subcategory": "Visual Collaboration",
        "typical_use_cases": ["Digital whiteboard", "Workshop facilitation", "System diagramming"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 3_000, "mid_market": 15_000, "enterprise": 50_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Mural or FigJam", "Annual prepay"],
        "alternatives": ["mural", "figma", "lucidchart"],
        "red_flags": ["Overlap with Figma's FigJam if already licensed"],
        "g2_category_rank": 2,
        "typical_discount_pct": 12,
    },

    # ── Security ──────────────────────────────────────────────────────────────

    "okta": {
        "canonical_name": "Okta",
        "category": "Security",
        "subcategory": "Identity & Access Management",
        "typical_use_cases": [
            "Single Sign-On (SSO)",
            "Multi-factor authentication (MFA)",
            "Lifecycle management (user provisioning)",
            "API access management",
        ],
        "pricing_model": "per-user",
        "typical_contract_size": {"smb": 15_000, "mid_market": 55_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Workforce vs. Customer Identity — separate pricing, audit overlap",
            "Competitive quote from Microsoft Entra ID (included in M365 E3)",
            "Multi-year deal for 15–20% discount",
            "MFA-only tier vs. full Workforce Identity",
        ],
        "alternatives": ["microsoft-entra", "ping-identity", "onelogin"],
        "red_flags": [
            "External/partner users may have different licensing requirements",
            "Advanced Server Access add-on often underutilized",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

    "crowdstrike": {
        "canonical_name": "CrowdStrike",
        "category": "Security",
        "subcategory": "Endpoint Detection & Response",
        "typical_use_cases": ["Endpoint security (EDR)", "Threat hunting", "XDR", "Cloud security"],
        "pricing_model": "per-endpoint",
        "typical_contract_size": {"smb": 20_000, "mid_market": 78_000, "enterprise": 300_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Endpoint count audit — decommissioned machines inflate count",
            "Bundle Falcon modules for platform discount",
            "Competitive pressure from SentinelOne or Microsoft Defender",
            "Multi-year deal for 10–15% discount",
        ],
        "alternatives": ["sentinelone", "microsoft-defender", "carbon-black"],
        "red_flags": [
            "Falcon modules included in bundle but not deployed",
            "Endpoint count includes decommissioned or test machines",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "qualys": {
        "canonical_name": "Qualys",
        "category": "Security",
        "subcategory": "Vulnerability Management",
        "typical_use_cases": ["Vulnerability scanning", "Compliance monitoring", "Web app scanning"],
        "pricing_model": "per-IP or per-asset",
        "typical_contract_size": {"smb": 10_000, "mid_market": 28_000, "enterprise": 100_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Asset count audit", "Competitive pressure from Tenable"],
        "alternatives": ["tenable", "rapid7", "wiz"],
        "red_flags": ["IP/asset count may include cloud ephemeral instances"],
        "g2_category_rank": 2,
        "typical_discount_pct": 12,
    },

    # ── DevTools ──────────────────────────────────────────────────────────────

    "github": {
        "canonical_name": "GitHub",
        "category": "DevTools",
        "subcategory": "Source Control",
        "typical_use_cases": ["Source code repository", "CI/CD (Actions)", "Code review", "Security scanning"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 5_000, "mid_market": 18_000, "enterprise": 60_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Microsoft ownership — bundle with M365 or Azure for discount",
            "Seat count audit — contractors and external contributors",
            "GitHub Enterprise vs. GitHub Team pricing",
        ],
        "alternatives": ["gitlab", "bitbucket", "azure-devops"],
        "red_flags": ["Actions minutes consumption can spike with poor pipeline design"],
        "g2_category_rank": 1,
        "typical_discount_pct": 10,
    },

    "jira": {
        "canonical_name": "Jira",
        "category": "DevTools",
        "subcategory": "Project Tracking",
        "typical_use_cases": ["Agile project management", "Bug tracking", "Sprint planning", "Roadmapping"],
        "pricing_model": "per-user",
        "typical_contract_size": {"smb": 5_000, "mid_market": 24_000, "enterprise": 80_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Atlassian bundle (Jira + Confluence + others) for 20–30% discount",
            "Cloud vs. Data Center pricing comparison",
            "User count audit — inactive users common",
        ],
        "alternatives": ["asana", "linear", "azure-devops", "monday-com"],
        "red_flags": [
            "Data Center license if Cloud is viable — Cloud is cheaper for most",
            "Apps marketplace add-ons can double total cost",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

    "confluence": {
        "canonical_name": "Confluence",
        "category": "DevTools",
        "subcategory": "Documentation",
        "typical_use_cases": ["Technical documentation", "Team wikis", "Meeting notes"],
        "pricing_model": "per-user",
        "typical_contract_size": {"smb": 3_000, "mid_market": 12_000, "enterprise": 40_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Atlassian bundle (with Jira) for significant discount",
            "Competitive pressure from Notion or SharePoint",
        ],
        "alternatives": ["notion", "sharepoint", "gitbook"],
        "red_flags": ["Often bundled with Jira — audit if standalone cost is visible"],
        "g2_category_rank": 2,
        "typical_discount_pct": 18,
    },

    "datadog": {
        "canonical_name": "Datadog",
        "category": "DevTools",
        "subcategory": "Observability",
        "typical_use_cases": ["Infrastructure monitoring", "APM", "Log management", "Synthetics"],
        "pricing_model": "consumption-based (hosts + custom metrics + logs)",
        "typical_contract_size": {"smb": 30_000, "mid_market": 95_000, "enterprise": 400_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": [
            "Host/custom metric audit — runaway metrics common",
            "Annual commit for 20–25% discount vs. on-demand",
            "Log ingestion vs. retention costs — tune retention policies",
            "Competitive pressure from New Relic or Grafana Cloud",
        ],
        "alternatives": ["new-relic", "dynatrace", "grafana", "pagerduty"],
        "red_flags": [
            "Custom metrics explosion from poorly configured exporters",
            "Log volume without log exclusion rules configured",
            "APM host count includes dev/staging environments",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 22,
    },

    "pagerduty": {
        "canonical_name": "PagerDuty",
        "category": "DevTools",
        "subcategory": "Incident Management",
        "typical_use_cases": ["On-call management", "Incident response", "Alert routing"],
        "pricing_model": "per-user",
        "typical_contract_size": {"smb": 8_000, "mid_market": 22_000, "enterprise": 70_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Stakeholder vs. full-license users — many stakeholders can be read-only",
            "Competitive pressure from Opsgenie (Atlassian bundle)",
        ],
        "alternatives": ["opsgenie", "victorops", "firehydrant"],
        "red_flags": ["Full license for stakeholders who only acknowledge incidents"],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    # ── Marketing ─────────────────────────────────────────────────────────────

    "marketo": {
        "canonical_name": "Adobe Marketo Engage",
        "category": "Marketing",
        "subcategory": "Marketing Automation",
        "typical_use_cases": ["Email marketing automation", "Lead nurturing", "Account-based marketing", "Lead scoring"],
        "pricing_model": "per-database-size (contacts tier)",
        "typical_contract_size": {"smb": 25_000, "mid_market": 72_000, "enterprise": 250_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Database size audit — purge unsubscribed/bounced contacts",
            "Adobe Experience Cloud bundle discount",
            "Competitive quote from HubSpot Marketing Hub",
            "End-of-Adobe-fiscal-quarter (November) pressure",
        ],
        "alternatives": ["hubspot", "pardot", "eloqua", "klaviyo"],
        "red_flags": [
            "Database bloat — unsubscribed contacts still count toward tier",
            "Unused add-ons (Web Personalization, Predictive Content)",
        ],
        "g2_category_rank": 2,
        "typical_discount_pct": 20,
    },

    "pardot": {
        "canonical_name": "Salesforce Marketing Cloud Account Engagement (Pardot)",
        "category": "Marketing",
        "subcategory": "B2B Marketing Automation",
        "typical_use_cases": ["B2B email automation", "Lead scoring", "Salesforce CRM integration"],
        "pricing_model": "per-contact tier",
        "typical_contract_size": {"smb": 15_000, "mid_market": 50_000, "enterprise": 150_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Bundle with Salesforce CRM for significant discount",
            "Contact database audit before renewal",
            "End-of-Salesforce-quarter pressure",
        ],
        "alternatives": ["marketo", "hubspot", "eloqua"],
        "red_flags": ["Tight Salesforce dependency — switching cost high"],
        "g2_category_rank": 3,
        "typical_discount_pct": 20,
    },

    "outreach": {
        "canonical_name": "Outreach",
        "category": "Sales",
        "subcategory": "Sales Engagement",
        "typical_use_cases": ["Sales cadences/sequences", "Email and call automation", "Pipeline management"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 10_000, "mid_market": 48_000, "enterprise": 150_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Audit active users vs. licensed seats (SDR turnover common)",
            "Competitive pressure from Salesloft or Apollo",
            "Annual prepay for additional discount",
        ],
        "alternatives": ["salesloft", "apollo", "hubspot"],
        "red_flags": ["High SDR turnover means licensed seats exceed active reps"],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "salesloft": {
        "canonical_name": "Salesloft",
        "category": "Sales",
        "subcategory": "Sales Engagement",
        "typical_use_cases": ["Sales cadences", "Conversation intelligence", "Deal management"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 12_000, "mid_market": 50_000, "enterprise": 160_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Outreach or Gong", "Seat audit"],
        "alternatives": ["outreach", "gong", "apollo"],
        "red_flags": ["Duplicate with Gong for conversation intelligence"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "zoominfo": {
        "canonical_name": "ZoomInfo",
        "category": "Sales Intelligence",
        "subcategory": "B2B Data",
        "typical_use_cases": ["Prospect contact data", "Company firmographics", "Intent data", "Website visitor ID"],
        "pricing_model": "credit-based or seat-based",
        "typical_contract_size": {"smb": 20_000, "mid_market": 60_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Credit audit — unused credits are common",
            "Competitive pressure from Clearbit, Apollo, or LinkedIn Sales Navigator",
            "Intent data add-on often underused — remove if not tracking",
            "Q4 renewal push — ZoomInfo sales team aggressive at year-end",
        ],
        "alternatives": ["clearbit", "apollo", "linkedin-sales-navigator", "cognism"],
        "red_flags": [
            "Credit rollover policy — unused credits often expire",
            "Data accuracy for SMB contacts can be lower than enterprise",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 20,
    },

    "clearbit": {
        "canonical_name": "Clearbit",
        "category": "Sales Intelligence",
        "subcategory": "B2B Data Enrichment",
        "typical_use_cases": ["Lead enrichment", "Website visitor identification", "Form shortening"],
        "pricing_model": "usage-based (API calls)",
        "typical_contract_size": {"smb": 10_000, "mid_market": 35_000, "enterprise": 100_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["HubSpot acquisition — bundle discount possible", "Competitive pressure from ZoomInfo"],
        "alternatives": ["zoominfo", "apollo", "lusha"],
        "red_flags": ["API call volume can spike with poor integration hygiene"],
        "g2_category_rank": 3,
        "typical_discount_pct": 15,
    },

    # ── Finance / Spend Management ─────────────────────────────────────────────

    "expensify": {
        "canonical_name": "Expensify",
        "category": "Finance",
        "subcategory": "Expense Management",
        "typical_use_cases": ["Employee expense reports", "Corporate card management", "Receipt scanning"],
        "pricing_model": "per-active-user",
        "typical_contract_size": {"smb": 3_000, "mid_market": 12_000, "enterprise": 35_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Brex or Ramp (includes expense mgmt)"],
        "alternatives": ["brex", "ramp", "concur", "divvy"],
        "red_flags": ["Overlap with corporate card platform that includes expense management"],
        "g2_category_rank": 3,
        "typical_discount_pct": 10,
    },

    "coupa": {
        "canonical_name": "Coupa",
        "category": "Finance",
        "subcategory": "Procurement / P2P",
        "typical_use_cases": ["Purchase order management", "Supplier management", "Invoice processing", "Spend analytics"],
        "pricing_model": "per-user + transaction volume",
        "typical_contract_size": {"smb": 20_000, "mid_market": 45_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Module audit — sourcing and risk management often unused",
            "Competitive pressure from Ariba or Ivalua",
        ],
        "alternatives": ["sap-ariba", "ivalua", "procurify"],
        "red_flags": ["User count includes approvers who only occasionally log in"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "brex": {
        "canonical_name": "Brex",
        "category": "Finance",
        "subcategory": "Corporate Cards",
        "typical_use_cases": ["Corporate credit cards", "Expense management", "Spend controls", "Bill pay"],
        "pricing_model": "free or premium per-user",
        "typical_contract_size": {"smb": 0, "mid_market": 8_000, "enterprise": 30_000},
        "renewal_cycle": "monthly",
        "negotiation_leverage": ["Competitive pressure from Ramp", "Premium tier vs. free tier features"],
        "alternatives": ["ramp", "expensify", "divvy", "navan"],
        "red_flags": ["Overlap with existing expense management tool"],
        "g2_category_rank": 2,
        "typical_discount_pct": 10,
    },

    "ramp": {
        "canonical_name": "Ramp",
        "category": "Finance",
        "subcategory": "Corporate Cards",
        "typical_use_cases": ["Corporate cards", "Expense automation", "Bill payments", "Procurement"],
        "pricing_model": "free or premium",
        "typical_contract_size": {"smb": 0, "mid_market": 6_000, "enterprise": 25_000},
        "renewal_cycle": "monthly",
        "negotiation_leverage": ["Competitive pressure from Brex", "Built-in savings insights"],
        "alternatives": ["brex", "expensify", "divvy"],
        "red_flags": ["Overlap with Expensify or Coupa"],
        "g2_category_rank": 1,
        "typical_discount_pct": 8,
    },

    # ── Talent / HR Tech ──────────────────────────────────────────────────────

    "lattice": {
        "canonical_name": "Lattice",
        "category": "HR Tech",
        "subcategory": "Performance Management",
        "typical_use_cases": ["Performance reviews", "OKRs and goal tracking", "1:1 management", "Engagement surveys"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 5_000, "mid_market": 18_000, "enterprise": 60_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Culture Amp or 15Five", "Seat audit"],
        "alternatives": ["culture-amp", "15five", "bamboohr"],
        "red_flags": ["Overlap with HRIS performance module (Workday, BambooHR)"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "culture-amp": {
        "canonical_name": "Culture Amp",
        "category": "HR Tech",
        "subcategory": "Employee Engagement",
        "typical_use_cases": ["Engagement surveys", "360 feedback", "Performance management", "DEI analytics"],
        "pricing_model": "per-employee",
        "typical_contract_size": {"smb": 8_000, "mid_market": 28_000, "enterprise": 90_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Lattice or Glint (LinkedIn)", "Annual prepay"],
        "alternatives": ["lattice", "15five", "glint"],
        "red_flags": ["Survey fatigue if multiple survey tools in use"],
        "g2_category_rank": 1,
        "typical_discount_pct": 12,
    },

    "greenhouse": {
        "canonical_name": "Greenhouse",
        "category": "HR Tech",
        "subcategory": "Applicant Tracking System",
        "typical_use_cases": ["Recruiting workflow", "Job postings", "Candidate tracking", "Offer management"],
        "pricing_model": "per-employee (base) + job slots",
        "typical_contract_size": {"smb": 10_000, "mid_market": 35_000, "enterprise": 100_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Employee count audit at renewal (company size may have changed)",
            "Competitive pressure from Lever or Ashby",
        ],
        "alternatives": ["lever", "ashby", "bamboohr"],
        "red_flags": ["Job slot limits can cause unexpected overages during hiring spikes"],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "lever": {
        "canonical_name": "Lever",
        "category": "HR Tech",
        "subcategory": "Applicant Tracking System",
        "typical_use_cases": ["Recruiting", "Candidate relationship management", "Structured interviews"],
        "pricing_model": "per-employee",
        "typical_contract_size": {"smb": 8_000, "mid_market": 28_000, "enterprise": 80_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Greenhouse or Ashby"],
        "alternatives": ["greenhouse", "ashby", "workday"],
        "red_flags": ["Limited reporting compared to Greenhouse"],
        "g2_category_rank": 2,
        "typical_discount_pct": 12,
    },

    # ── Customer Success ───────────────────────────────────────────────────────

    "gainsight": {
        "canonical_name": "Gainsight",
        "category": "Customer Success",
        "subcategory": "CS Platform",
        "typical_use_cases": [
            "Customer health scoring",
            "CS workflow automation (playbooks)",
            "Customer 360 view",
            "QBR preparation",
            "Churn risk identification",
        ],
        "pricing_model": "per-CSM seat",
        "typical_contract_size": {"smb": 20_000, "mid_market": 65_000, "enterprise": 250_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "CSM headcount audit before renewal",
            "Competitive pressure from Totango or ChurnZero",
            "Module rationalization (NPS, Surveys often unused)",
        ],
        "alternatives": ["churnzero", "totango", "planhat"],
        "red_flags": [
            "PX (product analytics module) often licensed but not deployed",
            "High configuration complexity — audit admin time cost",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 20,
    },

    "churnzero": {
        "canonical_name": "ChurnZero",
        "category": "Customer Success",
        "subcategory": "CS Platform",
        "typical_use_cases": ["Churn prediction", "Customer health scores", "Automated CS workflows"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 12_000, "mid_market": 40_000, "enterprise": 120_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Gainsight", "Seat count audit"],
        "alternatives": ["gainsight", "totango", "planhat"],
        "red_flags": ["Less mature enterprise features than Gainsight"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    "zendesk": {
        "canonical_name": "Zendesk",
        "category": "Customer Support",
        "subcategory": "Support Ticketing",
        "typical_use_cases": ["Customer support ticketing", "Help center / knowledge base", "Live chat", "AI chatbot"],
        "pricing_model": "per-agent",
        "typical_contract_size": {"smb": 10_000, "mid_market": 42_000, "enterprise": 160_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Agent count audit — light agents vs. full agents",
            "Competitive pressure from Intercom or Freshdesk",
            "Suite vs. individual product pricing",
        ],
        "alternatives": ["intercom", "freshdesk", "hubspot-service"],
        "red_flags": [
            "Light agent count can be reduced for internal-only users",
            "Talk (phone) add-on often unused if Zoom Phone deployed",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

    "intercom": {
        "canonical_name": "Intercom",
        "category": "Customer Support",
        "subcategory": "Conversational Support",
        "typical_use_cases": ["Live chat", "In-app messaging", "Customer support", "Proactive messaging"],
        "pricing_model": "per-seat + usage",
        "typical_contract_size": {"smb": 8_000, "mid_market": 35_000, "enterprise": 120_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Competitive pressure from Zendesk", "Usage audit (messages sent)"],
        "alternatives": ["zendesk", "hubspot-service", "freshdesk"],
        "red_flags": ["Resolution-based pricing can be unpredictable"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    # ── Revenue Intelligence ───────────────────────────────────────────────────

    "gong": {
        "canonical_name": "Gong",
        "category": "Revenue Intelligence",
        "subcategory": "Conversation Intelligence",
        "typical_use_cases": ["Call recording and transcription", "Deal intelligence", "Coaching", "Forecasting"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 15_000, "mid_market": 55_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Seat count audit — SDRs vs. AEs may have different tiers",
            "Competitive pressure from Chorus (ZoomInfo) or Salesloft",
            "Multi-year commitment for discount",
        ],
        "alternatives": ["chorus", "salesloft", "outreach"],
        "red_flags": [
            "Overlap with Salesloft or Outreach conversation intelligence features",
            "Storage costs for call recordings can grow unexpectedly",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

    "chorus": {
        "canonical_name": "Chorus (ZoomInfo)",
        "category": "Revenue Intelligence",
        "subcategory": "Conversation Intelligence",
        "typical_use_cases": ["Call recording", "Coaching", "Deal risk identification"],
        "pricing_model": "per-seat",
        "typical_contract_size": {"smb": 10_000, "mid_market": 35_000, "enterprise": 120_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Bundle with ZoomInfo for significant discount", "Competitive pressure from Gong"],
        "alternatives": ["gong", "salesloft", "outreach"],
        "red_flags": ["Overlap with Gong if both deployed"],
        "g2_category_rank": 2,
        "typical_discount_pct": 20,
    },

    # ── Legal Tech ────────────────────────────────────────────────────────────

    "docusign": {
        "canonical_name": "DocuSign",
        "category": "Legal",
        "subcategory": "eSignature",
        "typical_use_cases": ["Contract e-signatures", "Agreement Cloud", "CLM basics"],
        "pricing_model": "per-sender + envelope volume",
        "typical_contract_size": {"smb": 5_000, "mid_market": 18_000, "enterprise": 70_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Envelope volume audit — unused envelopes indicate over-purchasing",
            "Competitive pressure from Adobe Sign or HelloSign",
            "Sender count audit",
        ],
        "alternatives": ["ironclad", "adobe-sign", "hellosign"],
        "red_flags": [
            "Envelope overage charges can be significant",
            "CLM features in Salesforce (Conga) may overlap",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "ironclad": {
        "canonical_name": "Ironclad",
        "category": "Legal",
        "subcategory": "Contract Lifecycle Management",
        "typical_use_cases": ["Contract creation and negotiation", "CLM workflows", "Contract repository", "AI contract review"],
        "pricing_model": "per-seat (legal team)",
        "typical_contract_size": {"smb": 15_000, "mid_market": 28_000, "enterprise": 100_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "Legal team headcount audit",
            "Competitive pressure from ContractPodAi or DocuSign CLM",
        ],
        "alternatives": ["docusign", "contractpodai", "legalsifter"],
        "red_flags": ["Implementation requires legal ops expertise — factor in adoption cost"],
        "g2_category_rank": 2,
        "typical_discount_pct": 15,
    },

    # ── Cloud Infrastructure ───────────────────────────────────────────────────

    "aws": {
        "canonical_name": "Amazon Web Services",
        "category": "Cloud Infrastructure",
        "subcategory": "IaaS/PaaS",
        "typical_use_cases": ["Compute (EC2)", "Storage (S3)", "Database (RDS, Aurora)", "Serverless (Lambda)", "AI/ML (Bedrock, SageMaker)"],
        "pricing_model": "consumption-based",
        "typical_contract_size": {"smb": 30_000, "mid_market": 200_000, "enterprise": 1_000_000},
        "renewal_cycle": "annual commitment (Savings Plans / Reserved Instances)",
        "negotiation_leverage": [
            "Reserved Instance or Savings Plans for 30–60% discount vs. on-demand",
            "Enterprise Discount Program (EDP) for >$1M/yr spend",
            "Rightsizing analysis — oversized instances very common",
            "Spot instances for non-critical workloads (up to 90% off)",
            "AWS Marketplace credits from ISV partnerships",
        ],
        "alternatives": ["azure", "gcp", "oracle-cloud"],
        "red_flags": [
            "On-demand pricing for predictable workloads — should be Reserved",
            "Data egress costs — significant for multi-cloud architectures",
            "Orphaned resources (unattached EBS volumes, unused Elastic IPs)",
            "Dev/test environments running 24/7 at production scale",
        ],
        "g2_category_rank": 1,
        "typical_discount_pct": 35,
    },

    "azure": {
        "canonical_name": "Microsoft Azure",
        "category": "Cloud Infrastructure",
        "subcategory": "IaaS/PaaS",
        "typical_use_cases": ["Compute", "Azure Active Directory", "Azure DevOps", "AI Services", "SQL Database"],
        "pricing_model": "consumption-based",
        "typical_contract_size": {"smb": 20_000, "mid_market": 150_000, "enterprise": 800_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": [
            "Microsoft Enterprise Agreement — consolidate M365 + Azure",
            "Azure Hybrid Benefit (Windows Server / SQL license portability)",
            "Reserved VMs for 30–40% discount",
        ],
        "alternatives": ["aws", "gcp"],
        "red_flags": ["Dev/test subscriptions with production-tier resources"],
        "g2_category_rank": 2,
        "typical_discount_pct": 30,
    },

    "gcp": {
        "canonical_name": "Google Cloud Platform",
        "category": "Cloud Infrastructure",
        "subcategory": "IaaS/PaaS",
        "typical_use_cases": ["Compute (GCE)", "BigQuery (data warehouse)", "Cloud Run (serverless)", "Vertex AI", "Kubernetes (GKE)"],
        "pricing_model": "consumption-based",
        "typical_contract_size": {"smb": 15_000, "mid_market": 100_000, "enterprise": 600_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": [
            "Committed Use Discounts (CUD) for 25–55% off on-demand",
            "Google Workspace bundle discount",
            "BigQuery flat-rate vs. on-demand pricing negotiation",
        ],
        "alternatives": ["aws", "azure"],
        "red_flags": ["BigQuery on-demand scan pricing — implement slot reservations for predictable workloads"],
        "g2_category_rank": 3,
        "typical_discount_pct": 30,
    },

    # ── CDN / Edge ────────────────────────────────────────────────────────────

    "cloudflare": {
        "canonical_name": "Cloudflare",
        "category": "Infrastructure",
        "subcategory": "CDN / Security",
        "typical_use_cases": ["CDN", "DDoS protection", "Zero Trust (SASE)", "DNS", "Workers (edge compute)"],
        "pricing_model": "tiered (Free/Pro/Business/Enterprise)",
        "typical_contract_size": {"smb": 5_000, "mid_market": 25_000, "enterprise": 100_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": ["Bundle SASE + CDN", "Traffic volume discount"],
        "alternatives": ["fastly", "akamai", "aws-cloudfront"],
        "red_flags": ["Zero Trust add-on cost if already paying for Okta ASA"],
        "g2_category_rank": 1,
        "typical_discount_pct": 15,
    },

    "fastly": {
        "canonical_name": "Fastly",
        "category": "Infrastructure",
        "subcategory": "CDN",
        "typical_use_cases": ["CDN", "Edge compute", "Video streaming", "Image optimization"],
        "pricing_model": "consumption-based (bandwidth)",
        "typical_contract_size": {"smb": 10_000, "mid_market": 40_000, "enterprise": 200_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": ["Bandwidth commit for 20–30% discount", "Competitive pressure from Cloudflare"],
        "alternatives": ["cloudflare", "akamai", "aws-cloudfront"],
        "red_flags": ["On-demand bandwidth pricing without commit"],
        "g2_category_rank": 2,
        "typical_discount_pct": 20,
    },

    # ── Communications / Data ──────────────────────────────────────────────────

    "twilio": {
        "canonical_name": "Twilio",
        "category": "Communications",
        "subcategory": "CPaaS",
        "typical_use_cases": ["SMS notifications", "Voice calls", "Verify (2FA)", "Email (SendGrid)", "Video"],
        "pricing_model": "consumption-based",
        "typical_contract_size": {"smb": 10_000, "mid_market": 35_000, "enterprise": 150_000},
        "renewal_cycle": "annual commitment",
        "negotiation_leverage": [
            "Volume commit for 20–35% discount",
            "Competitive pressure from Vonage or AWS Connect",
            "Segment bundle (Twilio acquired Segment)",
        ],
        "alternatives": ["vonage", "messagebird", "aws-connect"],
        "red_flags": ["Usage spike patterns — implement spending alerts", "Phone number inventory audit"],
        "g2_category_rank": 1,
        "typical_discount_pct": 25,
    },

    "segment": {
        "canonical_name": "Segment (Twilio)",
        "category": "Data",
        "subcategory": "Customer Data Platform",
        "typical_use_cases": ["Event data collection", "CDP", "Data routing to 300+ destinations"],
        "pricing_model": "per-MTU (monthly tracked users)",
        "typical_contract_size": {"smb": 12_000, "mid_market": 50_000, "enterprise": 200_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "MTU audit — anonymous vs. identified users",
            "Twilio bundle discount (same parent company)",
            "Competitive pressure from RudderStack or mParticle",
        ],
        "alternatives": ["rudderstack", "mparticle", "amplitude"],
        "red_flags": ["MTU count includes anonymous/bot traffic — implement filtering"],
        "g2_category_rank": 2,
        "typical_discount_pct": 20,
    },

    "amplitude": {
        "canonical_name": "Amplitude",
        "category": "Product Analytics",
        "subcategory": "Product Analytics",
        "typical_use_cases": ["User behavior analytics", "Funnel analysis", "Retention analysis", "A/B testing"],
        "pricing_model": "per-MTU",
        "typical_contract_size": {"smb": 10_000, "mid_market": 40_000, "enterprise": 150_000},
        "renewal_cycle": "annual",
        "negotiation_leverage": [
            "MTU audit before renewal",
            "Competitive pressure from Mixpanel or Heap",
        ],
        "alternatives": ["mixpanel", "heap", "segment"],
        "red_flags": ["MTU count inflated by bot/crawler traffic"],
        "g2_category_rank": 1,
        "typical_discount_pct": 18,
    },

}  # end VENDOR_CATALOG


# ── Alias / normalization map ─────────────────────────────────────────────────
# Maps alternate names/spellings to canonical catalog keys

_ALIASES: dict[str, str] = {
    # Salesforce variations
    "salesforce inc": "salesforce",
    "salesforce.com": "salesforce",
    "sfdc": "salesforce",
    "salesforce crm": "salesforce",
    "salesforce sales cloud": "salesforce",
    # HubSpot
    "hubspot crm": "hubspot",
    "hubspot inc": "hubspot",
    # Workday
    "workday inc": "workday",
    "workday hcm": "workday",
    # BambooHR
    "bamboohr": "bamboohr",
    "bamboo hr": "bamboohr",
    # NetSuite
    "oracle netsuite": "netsuite",
    "netsuite erp": "netsuite",
    "oracle netsuite erp": "netsuite",
    # Sage Intacct
    "sage intacct": "sage-intacct",
    "intacct": "sage-intacct",
    # Tableau
    "tableau software": "tableau",
    "tableau desktop": "tableau",
    "tableau server": "tableau",
    # Looker
    "looker (google)": "looker",
    "google looker": "looker",
    # Snowflake
    "snowflake inc": "snowflake",
    "snowflake data cloud": "snowflake",
    # Microsoft 365
    "microsoft 365": "microsoft-365",
    "microsoft office 365": "microsoft-365",
    "office 365": "microsoft-365",
    "o365": "microsoft-365",
    "m365": "microsoft-365",
    "microsoft corp": "microsoft-365",
    # Google Workspace
    "google workspace": "google-workspace",
    "g suite": "google-workspace",
    "gsuite": "google-workspace",
    # Slack
    "slack technologies": "slack",
    "slack inc": "slack",
    # Zoom
    "zoom video comms": "zoom",
    "zoom video communications": "zoom",
    "zoom.us": "zoom",
    # Okta
    "okta inc": "okta",
    "okta identity": "okta",
    # CrowdStrike
    "crowdstrike inc": "crowdstrike",
    "crowdstrike falcon": "crowdstrike",
    # GitHub
    "github inc": "github",
    "github enterprise": "github",
    # Jira
    "atlassian jira": "jira",
    "jira software": "jira",
    "atlassian corp": "jira",
    # Confluence
    "atlassian confluence": "confluence",
    # Datadog
    "datadog inc": "datadog",
    # PagerDuty
    "pagerduty inc": "pagerduty",
    # Marketo
    "adobe marketo": "marketo",
    "marketo engage": "marketo",
    "adobe marketo engage": "marketo",
    # Pardot
    "salesforce pardot": "pardot",
    "marketing cloud account engagement": "pardot",
    # Outreach
    "outreach inc": "outreach",
    "outreach.io": "outreach",
    # ZoomInfo
    "zoominfo tech": "zoominfo",
    "zoominfo technologies": "zoominfo",
    # Expensify
    "expensify inc": "expensify",
    # Coupa
    "coupa software": "coupa",
    # Brex
    "brex inc": "brex",
    # Gusto
    "gusto inc": "gusto",
    # Lattice
    "lattice inc": "lattice",
    # Greenhouse
    "greenhouse software": "greenhouse",
    "greenhouse io": "greenhouse",
    # Gainsight
    "gainsight inc": "gainsight",
    "gainsight platform": "gainsight",
    # Zendesk
    "zendesk inc": "zendesk",
    "zendesk support": "zendesk",
    # DocuSign
    "docusign inc": "docusign",
    # Ironclad
    "ironclad inc": "ironclad",
    "ironcladapp": "ironclad",
    # AWS
    "amazon web services": "aws",
    "amazon aws": "aws",
    "aws": "aws",
    # Azure
    "microsoft azure": "azure",
    "azure cloud": "azure",
    # GCP
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    # Twilio
    "twilio inc": "twilio",
    # Segment
    "twilio segment": "segment",
    # Monday.com
    "monday.com": "monday-com",
    "monday com": "monday-com",
    # Notion
    "notion labs": "notion",
    # Figma
    "figma inc": "figma",
    # Gong
    "gong.io": "gong",
    "gong.io inc": "gong",
    # Rippling
    "rippling inc": "rippling",
    # Databricks
    "databricks inc": "databricks",
    # Culture Amp
    "culture amp": "culture-amp",
    # Salesloft
    "salesloft inc": "salesloft",
    # Chorus
    "chorus.ai": "chorus",
    "chorus (zoominfo)": "chorus",
    # ChurnZero
    "churnzero inc": "churnzero",
    # Microsoft Dynamics
    "dynamics 365": "microsoft-dynamics",
    "dynamics crm": "microsoft-dynamics",
    "microsoft dynamics": "microsoft-dynamics",
}

# Generic negotiation tips for unknown vendors
_GENERIC_NEGOTIATION_TIPS = [
    "Request a full usage report 90 days before renewal — identify unused seats or features",
    "Ask for a multi-year commitment discount (typically 10–20% for 2-year, 20–30% for 3-year)",
    "Benchmark pricing against 2–3 competitors and share the quotes",
    "Push for annual prepay in exchange for a 10–15% discount",
    "Audit the seat/license count — unused seats are the most common savings opportunity",
    "Negotiate a price cap clause for annual increases (typically 3–5% max)",
    "Request a formal QBR with account team before renewal to surface mutual value",
    "Time your negotiation at the vendor's fiscal quarter-end for maximum leverage",
]


def _normalize_key(name: str) -> str:
    """Normalize a vendor name to a lookup key: lowercase, strip punctuation, collapse spaces."""
    key = name.lower().strip()
    # Remove common legal suffixes for fuzzy matching
    key = re.sub(r"\b(inc|llc|ltd|corp|co|plc|lp|gmbh|bv|ag)\b\.?", "", key)
    key = re.sub(r"[^\w\s-]", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def lookup_vendor(name: str) -> dict | None:
    """
    Fuzzy lookup a vendor by name. Returns the catalog entry or None.

    Matching order:
    1. Exact match on canonical key (e.g. "salesforce")
    2. Alias table match
    3. Normalized name match against catalog keys and aliases
    """
    if not name:
        return None

    # 1. Direct key match
    key = name.lower().strip()
    if key in VENDOR_CATALOG:
        return VENDOR_CATALOG[key]

    # 2. Alias lookup
    normalized = _normalize_key(name)
    if normalized in _ALIASES:
        return VENDOR_CATALOG.get(_ALIASES[normalized])
    if key in _ALIASES:
        return VENDOR_CATALOG.get(_ALIASES[key])

    # 3. Partial / fuzzy: check if normalized name contains or is contained by a key
    for catalog_key in VENDOR_CATALOG:
        if normalized == catalog_key:
            return VENDOR_CATALOG[catalog_key]
        # Try hyphen-normalized version
        key_normalized = catalog_key.replace("-", " ")
        if normalized == key_normalized:
            return VENDOR_CATALOG[catalog_key]

    # 4. Substring match on catalog keys (e.g. "Salesforce Inc" → "salesforce")
    for catalog_key, entry in VENDOR_CATALOG.items():
        if catalog_key in normalized or normalized in catalog_key:
            return entry

    # 5. Check if the canonical name of any entry is a substring match
    for catalog_key, entry in VENDOR_CATALOG.items():
        canonical_normalized = _normalize_key(entry["canonical_name"])
        if canonical_normalized in normalized or normalized in canonical_normalized:
            return entry

    return None


def get_negotiation_tips(vendor_name: str) -> list[str]:
    """
    Return negotiation tips for a vendor.
    Falls back to generic tips if vendor is not in the catalog.
    """
    entry = lookup_vendor(vendor_name)
    if entry and "negotiation_leverage" in entry:
        return entry["negotiation_leverage"]
    return _GENERIC_NEGOTIATION_TIPS


def get_alternatives(vendor_name: str) -> list[str]:
    """
    Return competitor alternatives for a vendor.
    Returns empty list if vendor is not in the catalog.
    """
    entry = lookup_vendor(vendor_name)
    if entry and "alternatives" in entry:
        return entry["alternatives"]
    return []


def get_category_vendors(category: str) -> list[str]:
    """
    Return canonical keys of all vendors in a given category.
    Category matching is case-insensitive.
    """
    cat_lower = category.lower().strip()
    results = []
    for key, entry in VENDOR_CATALOG.items():
        if entry.get("category", "").lower() == cat_lower:
            results.append(key)
    return results
