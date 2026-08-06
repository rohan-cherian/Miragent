"""
CommunicationAgent — Sprint 73: Communication Analysis

Analyzes customer-facing communications to surface patterns: recurring complaint
themes, sentiment trends, at-risk customers signaling churn, and upsell signals.

DATA SCOPE (GDPR-safe — customer-to-company communications only):
  - Support email queue (support@company.com, help@company.com)
  - Shared Slack channels (#customer-success, #support-general, #enterprise-customers)
  - Zendesk/Freshservice ticket comments from customers

EXPLICITLY EXCLUDED (not in scope):
  - Employee DMs or internal Slack messages
  - Internal email threads
  - Any communication not initiated by or including the customer

Analysis pipeline:
  1. Sentiment classification (keyword-based): positive / negative / urgent /
     churn_risk / expansion_signal
  2. Topic classification: technical_issue / billing_question / feature_request /
     compliance_security / expansion_upsell / churn_risk / onboarding / positive_feedback
  3. Aggregate summary: ARR at churn risk, expansion ARR, sentiment trend
  4. Action suggestions: route to CSM, AE, compliance, or standard queue
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)

# ── Mock communications dataset ───────────────────────────────────────────────
# 25 realistic customer-facing messages from support email queues and shared Slack
# channels. Scope: customer-to-company only. No internal DMs or employee messages.

MOCK_COMMUNICATIONS = [
    # Support emails
    {"id": "msg-001", "channel": "email", "source": "support_queue", "from": "cto@enterprise-client.com",
     "subject": "Critical: API latency degradation affecting our workflows",
     "body": "We've been experiencing significant API latency (>5s) since Tuesday. This is blocking our integration team. Need this escalated immediately. We're evaluating our contract renewal next month.",
     "date": "2026-05-12", "customer": "Enterprise Client Corp", "arr": 180000},

    {"id": "msg-002", "channel": "email", "source": "support_queue", "from": "ops@growthco.io",
     "subject": "Can you help us understand the new dashboard?",
     "body": "Hi team, we updated to the new dashboard version and some of our saved reports aren't showing. Not urgent but would love some guidance. The new UI looks great by the way!",
     "date": "2026-05-13", "customer": "GrowthCo", "arr": 45000},

    {"id": "msg-003", "channel": "email", "source": "support_queue", "from": "finance@bigretail.com",
     "subject": "Invoice discrepancy - urgent",
     "body": "Our last invoice shows a 20% price increase we were not notified about. This is a significant budget impact. We need a credit and an explanation before we process payment.",
     "date": "2026-05-10", "customer": "BigRetail Inc", "arr": 95000},

    {"id": "msg-004", "channel": "slack", "source": "#enterprise-customers", "from": "sarah@tech-unicorn.com",
     "subject": None,
     "body": "Quick question — does Miragent support SSO with Azure AD? Our IT team is asking ahead of our full rollout next quarter.",
     "date": "2026-05-14", "customer": "TechUnicorn", "arr": 220000},

    {"id": "msg-005", "channel": "email", "source": "support_queue", "from": "ceo@startup.io",
     "subject": "Impressed with the results so far",
     "body": "Just wanted to share — we ran the first scan last week and already found 3 things our ops team had missed for months. The vendor benchmark report alone is going to save us $40K. Really impressive product.",
     "date": "2026-05-11", "customer": "Startup.io", "arr": 28000},

    {"id": "msg-006", "channel": "email", "source": "support_queue", "from": "it@manufacturing-co.com",
     "subject": "Integration failure - Workday connector down",
     "body": "The Workday connector stopped syncing 3 days ago. Our HR data is stale and the workforce analytics are showing wrong numbers. This is causing issues with our leadership reports.",
     "date": "2026-05-09", "customer": "Manufacturing Co", "arr": 67000},

    {"id": "msg-007", "channel": "slack", "source": "#customer-success", "from": "pm@scaleup.com",
     "subject": None,
     "body": "We're really struggling with the onboarding. We connected Salesforce 2 weeks ago but still haven't gotten any meaningful insights. Can someone do a call with us?",
     "date": "2026-05-13", "customer": "ScaleUp Inc", "arr": 55000},

    {"id": "msg-008", "channel": "email", "source": "support_queue", "from": "coo@logistics-firm.com",
     "subject": "Feature request: scheduled reports",
     "body": "Love the platform. One thing that would make a huge difference: scheduled weekly email reports so I don't have to log in to check the dashboard. Is this on the roadmap?",
     "date": "2026-05-12", "customer": "Logistics Firm LLC", "arr": 42000},

    {"id": "msg-009", "channel": "email", "source": "support_queue", "from": "vp@consultancy.co",
     "subject": "Cancellation request",
     "body": "We've decided not to renew our subscription. The platform didn't deliver the ROI we expected. Our contract is up June 30th. Please confirm cancellation and send final invoice.",
     "date": "2026-05-08", "customer": "ConsultancyCo", "arr": 36000},

    {"id": "msg-010", "channel": "email", "source": "support_queue", "from": "admin@healthcare.org",
     "subject": "HIPAA compliance question",
     "body": "Before we expand our usage, we need to understand your HIPAA compliance posture. Do you have a BAA available? Our legal team needs this before Q3 expansion.",
     "date": "2026-05-14", "customer": "HealthcareOrg", "arr": 78000},

    {"id": "msg-011", "channel": "slack", "source": "#enterprise-customers", "from": "eng@bigcorp.com",
     "subject": None,
     "body": "The API rate limits are too low for our use case. We're hitting them during our nightly batch jobs. Can we get an enterprise tier with higher limits?",
     "date": "2026-05-13", "customer": "BigCorp Inc", "arr": 250000},

    {"id": "msg-012", "channel": "email", "source": "support_queue", "from": "ops@retailchain.com",
     "subject": "Performance issue during peak hours",
     "body": "Between 9-11am EST the dashboard is really slow. Page loads take 10+ seconds. This is when our team uses it most. Is there a known issue?",
     "date": "2026-05-11", "customer": "RetailChain", "arr": 88000},

    {"id": "msg-013", "channel": "email", "source": "support_queue", "from": "cfo@peportco.com",
     "subject": "ROI documentation for board",
     "body": "Our board meeting is June 15th and I need to present the ROI from our Miragent investment. Can you help us compile the cost savings and efficiency metrics? This will be key for continued approval.",
     "date": "2026-05-14", "customer": "PE Portfolio Co", "arr": 120000},

    {"id": "msg-014", "channel": "slack", "source": "#customer-success", "from": "head-of-ops@series-b.com",
     "subject": None,
     "body": "We just closed our Series B and are scaling from 80 to 150 people. Can we talk about an enterprise plan? We want to deploy Miragent across the whole company.",
     "date": "2026-05-14", "customer": "Series B Startup", "arr": 52000},

    {"id": "msg-015", "channel": "email", "source": "support_queue", "from": "support@fintechco.com",
     "subject": "Data export not working",
     "body": "When I try to export the findings report to CSV the file is empty. Tried Chrome and Safari. Can you fix this?",
     "date": "2026-05-13", "customer": "FintechCo", "arr": 34000},

    {"id": "msg-016", "channel": "email", "source": "support_queue", "from": "cto@insurtech.io",
     "subject": "Excited about the new AI agents",
     "body": "Just saw the release notes for the new agent layer. We want to be an early adopter for the DDQ automation. When can we get access? This will save our team 20+ hours per DDQ cycle.",
     "date": "2026-05-12", "customer": "InsurTech.io", "arr": 65000},

    {"id": "msg-017", "channel": "slack", "source": "#support-general", "from": "ops@nonprofit.org",
     "subject": None,
     "body": "Having trouble getting the Salesforce connector to authenticate. Getting OAuth error 401. We've tried re-authorizing 3 times.",
     "date": "2026-05-11", "customer": "NonProfit Org", "arr": 12000},

    {"id": "msg-018", "channel": "email", "source": "support_queue", "from": "ceo@proptech.co",
     "subject": "This is exactly what we needed",
     "body": "Three months in and I can honestly say Miragent has transformed how we operate. We've saved over $120K in vendor contract renegotiations alone. Recommending to every CEO I know.",
     "date": "2026-05-10", "customer": "PropTech Co", "arr": 58000},

    {"id": "msg-019", "channel": "email", "source": "support_queue", "from": "vp-sales@mediaco.com",
     "subject": "Not seeing Salesforce data in graph",
     "body": "We connected Salesforce last week but the opportunity data doesn't seem to be flowing through. The pipeline view is empty. Did something break in our setup?",
     "date": "2026-05-12", "customer": "Media Co", "arr": 41000},

    {"id": "msg-020", "channel": "slack", "source": "#enterprise-customers", "from": "cso@security-firm.com",
     "subject": None,
     "body": "We need your SOC 2 Type II report and pen test summary before our security team approves the enterprise rollout. How do we get these?",
     "date": "2026-05-13", "customer": "Security Firm", "arr": 195000},

    {"id": "msg-021", "channel": "email", "source": "support_queue", "from": "admin@edtech.com",
     "subject": "Confused about pricing tiers",
     "body": "We're trying to understand if we need the enterprise plan or if the growth plan covers our needs. We have 200 employees and use Salesforce + Workday. Can someone walk us through the options?",
     "date": "2026-05-11", "customer": "EdTech Platform", "arr": 22000},

    {"id": "msg-022", "channel": "email", "source": "support_queue", "from": "coo@govtech.gov",
     "subject": "FedRAMP certification question",
     "body": "For our agency procurement process we need to know if Miragent is FedRAMP authorized or pursuing authorization. This is a blocker for our expansion.",
     "date": "2026-05-14", "customer": "GovTech Agency", "arr": 0},

    {"id": "msg-023", "channel": "slack", "source": "#customer-success", "from": "ops@legaltech.law",
     "subject": None,
     "body": "Our Matter Management integration isn't picking up new clients. The graph shows our client list from 3 months ago. Is there a sync refresh we can trigger?",
     "date": "2026-05-10", "customer": "LegalTech LLC", "arr": 48000},

    {"id": "msg-024", "channel": "email", "source": "support_queue", "from": "finance@ecommerce.shop",
     "subject": "Billing question - annual discount",
     "body": "We're coming up on our annual renewal. Last year we negotiated a 15% discount for paying annually. Is that still available? Our contract is up July 1st.",
     "date": "2026-05-13", "customer": "eCommerce Shop", "arr": 31000},

    {"id": "msg-025", "channel": "email", "source": "support_queue", "from": "cto@mobility.ai",
     "subject": "API documentation needs improvement",
     "body": "The API docs are missing several endpoints that are in production. We've had to reverse-engineer things that should be documented. Would love to contribute to docs if you open source them.",
     "date": "2026-05-12", "customer": "Mobility AI", "arr": 38000},
]


# ── Keyword lists for classification ─────────────────────────────────────────

SENTIMENT_KEYWORDS: dict[str, list[str]] = {
    "positive": [
        "impressed", "love", "great", "excellent", "thank", "saving", "transformed",
        "excited", "recommend", "recommending", "amazing", "fantastic", "saved",
    ],
    "negative": [
        "not working", "failed", "error", "slow", "frustrated", "cancellation",
        "wrong", "broken", "issue", "problem", "blocking", "stale", "empty",
        "discrepancy", "struggling", "trouble",
    ],
    "urgent": [
        "urgent", "immediately", "critical", "blocking", "escalate", "can't",
        "cannot", "blocker",
    ],
    "churn_risk": [
        "cancellation", "not renewing", "cancel", "not renew", "disappointed",
        "didn't deliver", "didn't deliver", "roi", "not renewal",
    ],
    "expansion_signal": [
        "scale", "enterprise plan", "rollout", "expand", "early adopter",
        "series b", "more users", "across the company", "full rollout",
        "scaling", "deploy miragent",
    ],
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "churn_risk": [
        "cancellation", "not renewing", "cancel", "not renew",
    ],
    "compliance_security": [
        "soc 2", "hipaa", "fedramp", "pen test", "baa", "security", "gdpr",
        "compliance", "authorized", "authorization",
    ],
    "expansion_upsell": [
        "enterprise plan", "scale", "rollout", "upgrade", "series b", "more users",
        "across the company", "early adopter",
    ],
    "billing_question": [
        "invoice", "pricing", "discount", "payment", "renewal", "contract",
        "price increase", "credit", "billing",
    ],
    "positive_feedback": [
        "impressed", "love", "transformed", "saved", "recommending", "recommend",
        "excited", "exactly what we needed",
    ],
    "technical_issue": [
        "error", "connector", "not working", "latency", "slow", "oauth", "empty",
        "failed", "not syncing", "not see", "not showing", "stopped syncing",
        "page loads", "not picking", "doesn't seem",
    ],
    "feature_request": [
        "roadmap", "feature", "scheduled", "export", "documentation", "api docs",
        "would love", "would make a huge difference",
    ],
    "onboarding": [
        "setup", "configure", "getting started", "haven't gotten", "struggling",
        "connected salesforce", "authenticate", "re-authorizing",
    ],
}

# Topic evaluation order — first match wins
TOPIC_ORDER = [
    "churn_risk",
    "compliance_security",
    "expansion_upsell",
    "billing_question",
    "positive_feedback",
    "technical_issue",
    "feature_request",
    "onboarding",
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CommMessage:
    id: str
    channel: str
    source: str
    customer: str
    arr: float
    date: str
    subject: str | None
    body_preview: str        # first 150 chars of body
    sentiment: str           # primary sentiment label
    topic: str               # primary topic
    signals: list[str]       # all detected signals (can be multiple)
    requires_action: bool    # True if urgent or churn_risk
    action_suggestion: str | None


@dataclass
class CommAnalysisSummary:
    total_messages: int
    by_sentiment: dict       # {positive: N, negative: N, urgent: N, churn_risk: N, expansion_signal: N}
    by_topic: dict           # {topic: count}
    by_channel: dict         # {email: N, slack: N}
    churn_risk_arr: float    # sum ARR of churn_risk customers
    expansion_arr: float     # sum ARR of expansion_signal customers
    top_customers_at_risk: list      # top 3 by ARR with churn signal
    top_expansion_opportunities: list  # top 3 by ARR with expansion signal
    urgent_unresolved: int           # count of urgent messages
    sentiment_trend: str             # "improving" / "stable" / "declining"
    analysis_date: str


# ── Agent class ────────────────────────────────────────────────────────────────


class CommunicationAgent:
    """
    Customer communication analysis agent.

    Ingests customer-facing communications from support email queues and shared
    Slack channels (GDPR-safe scope — no internal DMs, no employee communications).
    Classifies sentiment and topic, computes churn risk ARR and expansion ARR,
    surfaces at-risk customers and upsell opportunities.

    All keyword matching is local — no LLM required for classification.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze_all(self, tenant_id: str, db) -> CommAnalysisSummary:  # noqa: ARG002
        """
        Run the full analysis pipeline across all customer communications.

        Returns a CommAnalysisSummary with aggregate stats, top at-risk customers,
        and top expansion opportunities. The db parameter is accepted for API
        consistency but the mock dataset is used when db is None.

        Scope: customer-facing only — support email queue + shared Slack channels.
        Internal communications are excluded by design (GDPR compliance).
        """
        messages = self._process_all()

        by_sentiment: dict[str, int] = {
            "positive": 0, "negative": 0, "urgent": 0,
            "churn_risk": 0, "expansion_signal": 0,
        }
        by_topic: dict[str, int] = {}
        by_channel: dict[str, int] = {}

        churn_messages: list[CommMessage] = []
        expansion_messages: list[CommMessage] = []
        urgent_count = 0
        churn_arr = 0.0
        expansion_arr_total = 0.0
        seen_churn_customers: set[str] = set()
        seen_expansion_customers: set[str] = set()

        for msg in messages:
            # Sentiment counts
            if msg.sentiment in by_sentiment:
                by_sentiment[msg.sentiment] += 1

            # Topic counts
            by_topic[msg.topic] = by_topic.get(msg.topic, 0) + 1

            # Channel counts
            by_channel[msg.channel] = by_channel.get(msg.channel, 0) + 1

            # Urgent count
            if "urgent" in msg.signals:
                urgent_count += 1

            # Churn risk ARR (deduplicate by customer)
            if "churn_risk" in msg.signals:
                churn_messages.append(msg)
                if msg.customer not in seen_churn_customers:
                    churn_arr += msg.arr
                    seen_churn_customers.add(msg.customer)

            # Expansion ARR (deduplicate by customer)
            if "expansion_signal" in msg.signals:
                expansion_messages.append(msg)
                if msg.customer not in seen_expansion_customers:
                    expansion_arr_total += msg.arr
                    seen_expansion_customers.add(msg.customer)

        # Top 3 at-risk by ARR
        top_at_risk = sorted(churn_messages, key=lambda m: m.arr, reverse=True)[:3]

        # Top 3 expansion opportunities by ARR
        top_expansion = sorted(expansion_messages, key=lambda m: m.arr, reverse=True)[:3]

        # Sentiment trend: ratio of positive to negative
        pos = by_sentiment.get("positive", 0)
        neg = by_sentiment.get("negative", 0) + by_sentiment.get("churn_risk", 0)
        if pos > neg * 1.5:
            trend = "improving"
        elif neg > pos * 1.5:
            trend = "declining"
        else:
            trend = "stable"

        logger.info(
            "CommunicationAgent.analyze_all tenant=%s total=%d churn_arr=$%.0f expansion_arr=$%.0f trend=%s",
            tenant_id, len(messages), churn_arr, expansion_arr_total, trend,
        )

        return CommAnalysisSummary(
            total_messages=len(messages),
            by_sentiment=by_sentiment,
            by_topic=by_topic,
            by_channel=by_channel,
            churn_risk_arr=churn_arr,
            expansion_arr=expansion_arr_total,
            top_customers_at_risk=top_at_risk,
            top_expansion_opportunities=top_expansion,
            urgent_unresolved=urgent_count,
            sentiment_trend=trend,
            analysis_date=date.today().isoformat(),
        )

    def get_messages(
        self,
        tenant_id: str,  # noqa: ARG002
        db,               # noqa: ARG002
        filter_sentiment: str | None = None,
        filter_topic: str | None = None,
    ) -> list[CommMessage]:
        """
        Return processed messages with optional sentiment/topic filters.

        Scope: customer-facing only. Does not include internal communications.
        """
        messages = self._process_all()

        if filter_sentiment:
            messages = [m for m in messages if m.sentiment == filter_sentiment
                        or filter_sentiment in m.signals]
        if filter_topic:
            messages = [m for m in messages if m.topic == filter_topic]

        return messages

    def get_at_risk(self, tenant_id: str, db) -> list[CommMessage]:  # noqa: ARG002
        """
        Return all messages with churn_risk or urgent signals, sorted by ARR desc.

        These require immediate CSM or engineering intervention.
        """
        messages = self._process_all()
        at_risk = [m for m in messages if m.requires_action]
        return sorted(at_risk, key=lambda m: m.arr, reverse=True)

    def get_expansion_opportunities(self, tenant_id: str, db) -> list[CommMessage]:  # noqa: ARG002
        """
        Return all messages with expansion_signal, sorted by ARR desc.

        Route to Account Executive team for discovery calls.
        """
        messages = self._process_all()
        expansion = [m for m in messages if "expansion_signal" in m.signals]
        return sorted(expansion, key=lambda m: m.arr, reverse=True)

    # ── Private: classification pipeline ──────────────────────────────────────

    def _process_all(self) -> list[CommMessage]:
        """Process all mock communications and return classified CommMessage list."""
        results = []
        for raw in MOCK_COMMUNICATIONS:
            body: str = raw["body"]
            subject: str | None = raw["subject"]
            signals = self._classify_sentiment(body)
            topic = self._classify_topic(subject, body)
            primary_sentiment = signals[0] if signals else "neutral"
            requires = self._requires_action(signals)
            action = self._suggest_action(raw, signals)

            results.append(CommMessage(
                id=raw["id"],
                channel=raw["channel"],
                source=raw["source"],
                customer=raw["customer"],
                arr=float(raw["arr"]),
                date=raw["date"],
                subject=subject,
                body_preview=body[:150],
                sentiment=primary_sentiment,
                topic=topic,
                signals=signals,
                requires_action=requires,
                action_suggestion=action,
            ))
        return results

    def _classify_sentiment(self, body: str) -> list[str]:
        """
        Classify message body into one or more sentiment signals.

        Evaluation order ensures the most actionable signal is primary:
          1. churn_risk — highest impact, override everything
          2. urgent — needs fast response
          3. expansion_signal — revenue opportunity
          4. negative — problems to address
          5. positive — good news

        Returns a list of all matching signals; primary is index 0.
        """
        lower = body.lower()
        detected: list[str] = []

        # Evaluate in priority order
        for label in ("churn_risk", "urgent", "expansion_signal", "negative", "positive"):
            for kw in SENTIMENT_KEYWORDS[label]:
                if kw in lower:
                    if label not in detected:
                        detected.append(label)
                    break

        if not detected:
            detected = ["neutral"]

        return detected

    def _classify_topic(self, subject: str | None, body: str) -> str:
        """
        Classify the primary topic of a message.

        Subject is weighted 2x by prepending it twice. Returns first match
        from TOPIC_ORDER; falls back to "general_inquiry" if nothing matches.
        """
        subj = subject or ""
        # Subject weighted 2x
        text = (subj + " " + subj + " " + body).lower()

        for topic in TOPIC_ORDER:
            for kw in TOPIC_KEYWORDS[topic]:
                if kw in text:
                    return topic

        return "general_inquiry"

    def _requires_action(self, signals: list[str]) -> bool:
        """True if the message has urgent or churn_risk signals."""
        return "urgent" in signals or "churn_risk" in signals

    def _suggest_action(self, msg: dict, signals: list[str]) -> str | None:
        """
        Generate a concrete action suggestion based on signals and message context.

        Priority order (first match wins):
          1. churn_risk → escalate to CSM
          2. urgent → respond within 2h
          3. expansion_signal + ARR > 50k → notify AE
          4. compliance_security topic → route to compliance team
          5. default → standard queue
        """
        topic = self._classify_topic(msg.get("subject"), msg["body"])

        if "churn_risk" in signals:
            return "Escalate to CSM immediately. Schedule executive call."

        if "urgent" in signals:
            return "Respond within 2 hours. Notify engineering if technical issue."

        if "expansion_signal" in signals and float(msg.get("arr", 0)) > 50000:
            return "Notify AE team. Schedule expansion discovery call."

        if topic == "compliance_security":
            return "Route to compliance team. Send SOC 2 report under NDA."

        return "Route to standard support queue."
