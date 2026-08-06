"""
ITAccessAgent — Sprint 68

Manages IT access provisioning: request submission, authority verification,
approval routing to manager / IT admin / CISO, Okta group assignment, and
provisioning queue management.

Business scenario:
  An employee or manager submits an IT access request: "I need Salesforce
  access for my new hire Maria Rodriguez" or "Please provision GitHub access
  for our contractor." The agent verifies the requester has authority to make
  the request, checks if the system exists in the catalog, determines the
  approval tier, assigns to the right Okta group, and tracks the provisioning
  status.

Approval tiers:
  manager   — requester's direct manager can approve (auto-routed via email)
  it_admin  — requires IT admin approval (it@company.com); SLA 2 business days
  ciso      — requires CISO approval for sensitive systems (AWS, Workday, Okta);
              typical SLA 48 hours / 3-5 business days
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


# ── System catalog ─────────────────────────────────────────────────────────────

SYSTEM_CATALOG: dict[str, dict] = {
    "salesforce": {
        "display_name": "Salesforce CRM",
        "okta_group": "grp-salesforce-users",
        "approval_tier": "manager",
        "license_cost_monthly": 150,
        "requires_training": True,
        "training_url": "https://trailhead.salesforce.com",
        "owner": "sales-ops@company.com",
    },
    "github": {
        "display_name": "GitHub Enterprise",
        "okta_group": "grp-github-engineers",
        "approval_tier": "it_admin",
        "license_cost_monthly": 21,
        "requires_training": False,
        "training_url": None,
        "owner": "engineering@company.com",
    },
    "netsuite": {
        "display_name": "NetSuite ERP",
        "okta_group": "grp-netsuite-finance",
        "approval_tier": "it_admin",
        "license_cost_monthly": 200,
        "requires_training": True,
        "training_url": "https://netsuite.com/training",
        "owner": "finance-ops@company.com",
    },
    "workday": {
        "display_name": "Workday HCM",
        "okta_group": "grp-workday-hr",
        "approval_tier": "ciso",
        "license_cost_monthly": 180,
        "requires_training": True,
        "training_url": "https://workday.com/learning",
        "owner": "hr@company.com",
    },
    "slack": {
        "display_name": "Slack",
        "okta_group": "grp-slack-all",
        "approval_tier": "manager",
        "license_cost_monthly": 15,
        "requires_training": False,
        "training_url": None,
        "owner": "it@company.com",
    },
    "jira": {
        "display_name": "Jira / Confluence",
        "okta_group": "grp-jira-users",
        "approval_tier": "manager",
        "license_cost_monthly": 10,
        "requires_training": False,
        "training_url": None,
        "owner": "engineering@company.com",
    },
    "aws": {
        "display_name": "AWS Console",
        "okta_group": "grp-aws-cloud",
        "approval_tier": "ciso",
        "license_cost_monthly": 0,
        "requires_training": True,
        "training_url": "https://aws.amazon.com/training",
        "owner": "devops@company.com",
    },
    "hubspot": {
        "display_name": "HubSpot Marketing",
        "okta_group": "grp-hubspot-marketing",
        "approval_tier": "manager",
        "license_cost_monthly": 50,
        "requires_training": False,
        "training_url": None,
        "owner": "marketing@company.com",
    },
    "zendesk": {
        "display_name": "Zendesk Support",
        "okta_group": "grp-zendesk-support",
        "approval_tier": "manager",
        "license_cost_monthly": 55,
        "requires_training": True,
        "training_url": "https://training.zendesk.com",
        "owner": "support@company.com",
    },
    "okta": {
        "display_name": "Okta Admin",
        "okta_group": "grp-okta-admins",
        "approval_tier": "ciso",
        "license_cost_monthly": 0,
        "requires_training": True,
        "training_url": "https://okta.com/training",
        "owner": "it-security@company.com",
    },
    "tableau": {
        "display_name": "Tableau / Tableau Cloud",
        "okta_group": "grp-tableau-analysts",
        "approval_tier": "it_admin",
        "license_cost_monthly": 70,
        "requires_training": False,
        "training_url": None,
        "owner": "data@company.com",
    },
    "zoom": {
        "display_name": "Zoom",
        "okta_group": "grp-zoom-all",
        "approval_tier": "manager",
        "license_cost_monthly": 15,
        "requires_training": False,
        "training_url": None,
        "owner": "it@company.com",
    },
    "notion": {
        "display_name": "Notion",
        "okta_group": "grp-notion-users",
        "approval_tier": "manager",
        "license_cost_monthly": 16,
        "requires_training": False,
        "training_url": None,
        "owner": "it@company.com",
    },
    "figma": {
        "display_name": "Figma",
        "okta_group": "grp-figma-design",
        "approval_tier": "manager",
        "license_cost_monthly": 15,
        "requires_training": False,
        "training_url": None,
        "owner": "design@company.com",
    },
}

# ── Fuzzy system name aliases ──────────────────────────────────────────────────

_SYSTEM_ALIASES: dict[str, str] = {
    # salesforce
    "salesforce": "salesforce",
    "sfdc": "salesforce",
    "crm": "salesforce",
    # github
    "github": "github",
    "git": "github",
    # netsuite
    "netsuite": "netsuite",
    "erp": "netsuite",
    # workday
    "workday": "workday",
    "hcm": "workday",
    "hr system": "workday",
    "hrsystem": "workday",
    # slack
    "slack": "slack",
    "chat": "slack",
    # jira
    "jira": "jira",
    "confluence": "jira",
    "atlassian": "jira",
    # aws
    "aws": "aws",
    "amazon web services": "aws",
    "cloud": "aws",
    # hubspot
    "hubspot": "hubspot",
    "marketing": "hubspot",
    # zendesk
    "zendesk": "zendesk",
    "support desk": "zendesk",
    "supportdesk": "zendesk",
    # okta
    "okta": "okta",
    "sso": "okta",
    "identity": "okta",
    # tableau
    "tableau": "tableau",
    "data viz": "tableau",
    "dataviz": "tableau",
    # zoom
    "zoom": "zoom",
    "video": "zoom",
    # notion
    "notion": "notion",
    "wiki": "notion",
    # figma
    "figma": "figma",
    "design": "figma",
}

# ── Employee org chart ─────────────────────────────────────────────────────────

EMPLOYEE_ORG: dict[str, dict] = {
    "sarah.chen@acme-corp.com": {
        "name": "Sarah Chen",
        "title": "Senior Engineer",
        "manager": "david.park@acme-corp.com",
        "department": "Engineering",
        "is_manager": False,
    },
    "james.rodriguez@acme-corp.com": {
        "name": "James Rodriguez",
        "title": "Sales Manager",
        "manager": "nina.lee@acme-corp.com",
        "department": "Sales",
        "is_manager": True,
    },
    "aisha.patel@acme-corp.com": {
        "name": "Aisha Patel",
        "title": "Product Manager",
        "manager": "nina.lee@acme-corp.com",
        "department": "Product",
        "is_manager": True,
    },
    "marcus.johnson@acme-corp.com": {
        "name": "Marcus Johnson",
        "title": "Engineer",
        "manager": "david.park@acme-corp.com",
        "department": "Engineering",
        "is_manager": False,
    },
    "elena.kovacs@acme-corp.com": {
        "name": "Elena Kovacs",
        "title": "Finance Director",
        "manager": "rachel.foster@acme-corp.com",
        "department": "Finance",
        "is_manager": True,
    },
    "david.park@acme-corp.com": {
        "name": "David Park",
        "title": "VP Engineering",
        "manager": None,
        "department": "Engineering",
        "is_manager": True,
    },
    "priya.sharma@acme-corp.com": {
        "name": "Priya Sharma",
        "title": "Marketing Manager",
        "manager": "nina.lee@acme-corp.com",
        "department": "Marketing",
        "is_manager": True,
    },
    "tom.walsh@acme-corp.com": {
        "name": "Tom Walsh",
        "title": "Account Executive",
        "manager": "james.rodriguez@acme-corp.com",
        "department": "Sales",
        "is_manager": False,
    },
    "nina.lee@acme-corp.com": {
        "name": "Nina Lee",
        "title": "Chief People Officer",
        "manager": None,
        "department": "HR",
        "is_manager": True,
    },
    "carlos.mendez@acme-corp.com": {
        "name": "Carlos Mendez",
        "title": "Operations Manager",
        "manager": "nina.lee@acme-corp.com",
        "department": "Operations",
        "is_manager": True,
    },
    "yuki.tanaka@acme-corp.com": {
        "name": "Yuki Tanaka",
        "title": "Senior Engineer",
        "manager": "david.park@acme-corp.com",
        "department": "Engineering",
        "is_manager": False,
    },
    "rachel.foster@acme-corp.com": {
        "name": "Rachel Foster",
        "title": "CFO",
        "manager": None,
        "department": "Finance",
        "is_manager": True,
    },
}

# ── Mock provisioning queue ────────────────────────────────────────────────────

_MOCK_QUEUE: list[dict] = [
    {
        "request_id": "REQ-001",
        "requester_email": "marcus.johnson@acme-corp.com",
        "target_user_email": "marcus.johnson@acme-corp.com",
        "system_key": "github",
        "status": "provisioned",
        "submitted_date": "2024-03-01",
        "completed_date": "2024-03-02",
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "Self-service request — automatically approved.",
        "approver_email": "it@company.com",
    },
    {
        "request_id": "REQ-002",
        "requester_email": "james.rodriguez@acme-corp.com",
        "target_user_email": "tom.walsh@acme-corp.com",
        "system_key": "salesforce",
        "status": "pending_manager",
        "submitted_date": "2024-04-10",
        "completed_date": None,
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "Requester is a manager with authority to request for direct reports.",
        "approver_email": "nina.lee@acme-corp.com",
    },
    {
        "request_id": "REQ-003",
        "requester_email": "aisha.patel@acme-corp.com",
        "target_user_email": "alex.kim@acme-corp.com",
        "system_key": "jira",
        "status": "provisioned",
        "submitted_date": "2024-03-15",
        "completed_date": "2024-03-16",
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "Requester is a manager with authority to request for new hires.",
        "approver_email": "nina.lee@acme-corp.com",
    },
    {
        "request_id": "REQ-004",
        "requester_email": "david.park@acme-corp.com",
        "target_user_email": "yuki.tanaka@acme-corp.com",
        "system_key": "aws",
        "status": "pending_ciso",
        "submitted_date": "2024-04-20",
        "completed_date": None,
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "CISO-tier system — routed to CISO regardless of requester authority.",
        "approver_email": "ciso@company.com",
    },
    {
        "request_id": "REQ-005",
        "requester_email": "elena.kovacs@acme-corp.com",
        "target_user_email": "rachel.foster@acme-corp.com",
        "system_key": "netsuite",
        "status": "pending_it",
        "submitted_date": "2024-04-25",
        "completed_date": None,
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "IT admin-tier system — routed to IT admin for approval.",
        "approver_email": "it@company.com",
    },
    {
        "request_id": "REQ-006",
        "requester_email": "priya.sharma@acme-corp.com",
        "target_user_email": "priya.sharma@acme-corp.com",
        "system_key": "hubspot",
        "status": "provisioned",
        "submitted_date": "2024-02-20",
        "completed_date": "2024-02-21",
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "Self-service request — automatically approved.",
        "approver_email": "nina.lee@acme-corp.com",
    },
    {
        "request_id": "REQ-007",
        "requester_email": "rachel.foster@acme-corp.com",
        "target_user_email": "elena.kovacs@acme-corp.com",
        "system_key": "workday",
        "status": "pending_ciso",
        "submitted_date": "2024-05-01",
        "completed_date": None,
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "CISO-tier system — routed to CISO regardless of requester authority.",
        "approver_email": "ciso@company.com",
    },
    {
        "request_id": "REQ-008",
        "requester_email": "carlos.mendez@acme-corp.com",
        "target_user_email": "temp@contractor.com",
        "system_key": "slack",
        "status": "rejected",
        "submitted_date": "2024-03-10",
        "completed_date": None,
        "rejection_reason": "Contractor must use guest license — contact it@company.com",
        "authority_verified": True,
        "authority_note": "Requester is a manager with authority to request for external users.",
        "approver_email": "nina.lee@acme-corp.com",
    },
    {
        "request_id": "REQ-009",
        "requester_email": "sarah.chen@acme-corp.com",
        "target_user_email": "sarah.chen@acme-corp.com",
        "system_key": "figma",
        "status": "provisioned",
        "submitted_date": "2024-01-15",
        "completed_date": "2024-01-16",
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "Self-service request — automatically approved.",
        "approver_email": "david.park@acme-corp.com",
    },
    {
        "request_id": "REQ-010",
        "requester_email": "nina.lee@acme-corp.com",
        "target_user_email": "it-admin@acme-corp.com",
        "system_key": "okta",
        "status": "pending_ciso",
        "submitted_date": "2024-05-05",
        "completed_date": None,
        "rejection_reason": None,
        "authority_verified": True,
        "authority_note": "CISO-tier system — routed to CISO regardless of requester authority.",
        "approver_email": "ciso@company.com",
    },
]

# ── SLA by tier ────────────────────────────────────────────────────────────────

_SLA_DAYS: dict[str, int] = {
    "manager": 1,
    "it_admin": 2,
    "ciso": 5,
}

# ── Data class ─────────────────────────────────────────────────────────────────


@dataclass
class ITAccessResult:
    request_id: str
    requester_email: str
    requester_name: str
    target_user_email: str
    system_key: str
    system_display_name: str
    okta_group: str
    approval_tier: str
    approver_email: str
    status: str
    submitted_date: str
    completed_date: str | None
    rejection_reason: str | None
    license_cost_monthly: float
    requires_training: bool
    training_url: str | None
    sla_days: int
    authority_verified: bool
    authority_note: str
    next_steps: list[str]


# ── Agent class ────────────────────────────────────────────────────────────────


class ITAccessAgent:
    """
    Autonomous IT access provisioning agent.

    Uses a mock employee org chart and system catalog for demo/dev.
    In production this would query Okta, HR systems, and a CMDB.
    """

    def submit_request(
        self,
        requester_email: str,
        target_user_email: str,
        system_name: str,
        tenant_id: str,
        db,
    ) -> ITAccessResult:
        """
        Submit a new IT access request.

        Validates system name, verifies requester authority, determines the
        correct approval tier and approver, and returns a fully-hydrated result.
        """
        logger.info(
            "ITAccessAgent submit_request requester=%s target=%s system=%s tenant=%s",
            requester_email,
            target_user_email,
            system_name,
            tenant_id,
        )

        # Resolve system
        system_key = self._match_system(system_name)
        if system_key is None:
            # Return a not-found result rather than raising
            return self._not_found_result(requester_email, target_user_email, system_name)

        system = SYSTEM_CATALOG[system_key]
        approval_tier = system["approval_tier"]
        sla_days = _SLA_DAYS[approval_tier]

        # Authority verification
        authority_verified, authority_note = self._verify_authority(
            requester_email, target_user_email, system_key
        )

        # Determine approver
        approver_email = self._determine_approver(approval_tier, requester_email)

        # Determine initial status
        status = self._initial_status(approval_tier)

        # Build request id (mock — not persisted)
        today = date.today().isoformat()
        req_id = f"REQ-NEW-{requester_email.split('@')[0].upper()[:8]}-{system_key.upper()}"

        # Requester name
        requester_info = EMPLOYEE_ORG.get(requester_email.lower())
        requester_name = requester_info["name"] if requester_info else requester_email

        result = ITAccessResult(
            request_id=req_id,
            requester_email=requester_email,
            requester_name=requester_name,
            target_user_email=target_user_email,
            system_key=system_key,
            system_display_name=system["display_name"],
            okta_group=system["okta_group"],
            approval_tier=approval_tier,
            approver_email=approver_email,
            status=status,
            submitted_date=today,
            completed_date=None,
            rejection_reason=None,
            license_cost_monthly=float(system["license_cost_monthly"]),
            requires_training=system["requires_training"],
            training_url=system.get("training_url"),
            sla_days=sla_days,
            authority_verified=authority_verified,
            authority_note=authority_note,
            next_steps=self._build_next_steps(status, approver_email, system),
        )
        return result

    def get_request(self, request_id: str, tenant_id: str, db) -> ITAccessResult | None:
        """Look up a request by ID from the mock queue."""
        for raw in _MOCK_QUEUE:
            if raw["request_id"] == request_id:
                return self._build_result_from_raw(raw)
        return None

    def get_pending_queue(self, tenant_id: str, db) -> list[ITAccessResult]:
        """Return all requests that are not yet provisioned or rejected."""
        pending_statuses = {"pending_manager", "pending_it", "pending_ciso", "in_progress"}
        results = []
        for raw in _MOCK_QUEUE:
            if raw["status"] in pending_statuses:
                results.append(self._build_result_from_raw(raw))
        return results

    # ── System matching ────────────────────────────────────────────────────────

    def _match_system(self, system_name: str) -> str | None:
        """Fuzzy-match a requested system name against catalog keys and aliases."""
        normalized = system_name.lower().strip()
        # Direct catalog key match
        if normalized in SYSTEM_CATALOG:
            return normalized
        # Alias lookup
        return _SYSTEM_ALIASES.get(normalized)

    # ── Authority verification ─────────────────────────────────────────────────

    def _verify_authority(
        self,
        requester_email: str,
        target_email: str,
        system_key: str,
    ) -> tuple[bool, str]:
        """
        Determine whether the requester is authorized to submit this request.

        Rules:
          - CISO-tier: always passes (routed to CISO anyway)
          - IT admin-tier: always passes (routed to IT admin anyway)
          - Manager-tier: requester must be is_manager=True OR requesting for self
        """
        system = SYSTEM_CATALOG[system_key]
        approval_tier = system["approval_tier"]

        # CISO and IT admin tiers bypass authority check — they're escalated anyway
        if approval_tier == "ciso":
            return True, "CISO-tier system — routed to CISO regardless of requester authority."
        if approval_tier == "it_admin":
            return True, "IT admin-tier system — routed to IT admin for approval."

        # Manager tier: self-service always allowed
        if requester_email.lower() == target_email.lower():
            return True, "Self-service request — automatically approved."

        # Manager tier: check if requester is a manager
        requester_info = EMPLOYEE_ORG.get(requester_email.lower())
        if requester_info is None:
            return False, (
                f"Requester {requester_email} not found in employee directory. "
                "Cannot verify authority to request access for others."
            )

        if requester_info["is_manager"]:
            return True, "Requester is a manager with authority to request for direct reports."

        # Non-manager requesting for someone else — not authorized
        return False, (
            f"Requester {requester_info['name']} ({requester_info['title']}) does not have "
            "manager-level authority to request access for other employees. "
            "Please ask your manager to submit this request."
        )

    # ── Approver routing ───────────────────────────────────────────────────────

    def _determine_approver(self, approval_tier: str, requester_email: str) -> str:
        """Resolve the approver email based on the approval tier."""
        if approval_tier == "ciso":
            return "ciso@company.com"
        if approval_tier == "it_admin":
            return "it@company.com"
        # Manager tier: route to requester's manager (or IT as fallback)
        requester_info = EMPLOYEE_ORG.get(requester_email.lower())
        if requester_info and requester_info.get("manager"):
            return requester_info["manager"]
        return "it@company.com"

    # ── Status helpers ─────────────────────────────────────────────────────────

    def _initial_status(self, approval_tier: str) -> str:
        if approval_tier == "manager":
            return "pending_manager"
        if approval_tier == "it_admin":
            return "pending_it"
        return "pending_ciso"

    def _build_next_steps(self, status: str, approver_email: str, system: dict) -> list[str]:
        """Build the next_steps list based on current status."""
        okta_group = system["okta_group"]
        training_url = system.get("training_url")
        requires_training = system["requires_training"]

        if status == "pending_manager":
            return [
                f"Awaiting manager approval. Email sent to {approver_email}.",
                "Typical turnaround: 1 business day.",
            ]
        if status == "pending_it":
            return [
                "Awaiting IT admin review. Email sent to it@company.com.",
                "Typical turnaround: 2 business days.",
            ]
        if status == "pending_ciso":
            return [
                "Awaiting CISO approval. This is a sensitive system.",
                "Typical turnaround: 3-5 business days.",
                "If urgent, contact ciso@company.com directly.",
            ]
        if status == "provisioned":
            steps = [
                "Access has been granted. Check your email for login instructions.",
                f"Okta group assigned: {okta_group}.",
            ]
            if requires_training and training_url:
                steps.append(f"Complete required training: {training_url}")
            return steps
        if status == "rejected":
            return [
                "Request rejected. See rejection reason above.",
                "Contact it@company.com if you believe this is an error.",
            ]
        if status == "in_progress":
            return [
                "IT team is actively provisioning your access.",
                "Expected completion: within 24 hours.",
            ]
        return []

    # ── Result builders ────────────────────────────────────────────────────────

    def _build_result_from_raw(self, raw: dict) -> ITAccessResult:
        """Hydrate an ITAccessResult from a raw mock queue dict."""
        system_key = raw["system_key"]
        system = SYSTEM_CATALOG.get(system_key, {})
        approval_tier = system.get("approval_tier", "manager")
        sla_days = _SLA_DAYS.get(approval_tier, 1)

        requester_info = EMPLOYEE_ORG.get(raw["requester_email"].lower())
        requester_name = requester_info["name"] if requester_info else raw["requester_email"]

        status = raw["status"]
        rejection_reason = raw.get("rejection_reason")

        # Build next_steps, passing rejection_reason through for rejected status
        next_steps = self._build_next_steps(status, raw.get("approver_email", "it@company.com"), system)
        if status == "rejected" and rejection_reason:
            next_steps = [
                f"Request rejected: {rejection_reason}",
                "Contact it@company.com if you believe this is an error.",
            ]

        return ITAccessResult(
            request_id=raw["request_id"],
            requester_email=raw["requester_email"],
            requester_name=requester_name,
            target_user_email=raw["target_user_email"],
            system_key=system_key,
            system_display_name=system.get("display_name", system_key),
            okta_group=system.get("okta_group", ""),
            approval_tier=approval_tier,
            approver_email=raw.get("approver_email", "it@company.com"),
            status=status,
            submitted_date=raw.get("submitted_date", ""),
            completed_date=raw.get("completed_date"),
            rejection_reason=rejection_reason,
            license_cost_monthly=float(system.get("license_cost_monthly", 0)),
            requires_training=system.get("requires_training", False),
            training_url=system.get("training_url"),
            sla_days=sla_days,
            authority_verified=raw.get("authority_verified", True),
            authority_note=raw.get("authority_note", ""),
            next_steps=next_steps,
        )

    def _not_found_result(
        self,
        requester_email: str,
        target_user_email: str,
        system_name: str,
    ) -> ITAccessResult:
        """Return a graceful not-found result when the system cannot be matched."""
        requester_info = EMPLOYEE_ORG.get(requester_email.lower())
        requester_name = requester_info["name"] if requester_info else requester_email
        return ITAccessResult(
            request_id="REQ-ERR-UNKNOWN-SYSTEM",
            requester_email=requester_email,
            requester_name=requester_name,
            target_user_email=target_user_email,
            system_key="unknown",
            system_display_name=system_name,
            okta_group="",
            approval_tier="it_admin",
            approver_email="it@company.com",
            status="rejected",
            submitted_date=date.today().isoformat(),
            completed_date=None,
            rejection_reason=(
                f"System '{system_name}' not found in the IT system catalog. "
                "Please contact it@company.com with the full system name."
            ),
            license_cost_monthly=0.0,
            requires_training=False,
            training_url=None,
            sla_days=2,
            authority_verified=False,
            authority_note="System not recognized — cannot verify authority.",
            next_steps=[
                f"System '{system_name}' is not in the catalog.",
                "Contact it@company.com to add this system or clarify the name.",
            ],
        )
