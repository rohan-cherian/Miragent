"""Tests for Sprint 8 Engagement Intelligence and Sprint 9 Revenue Agent Workers."""

import time
import pytest
from fastapi.testclient import TestClient
from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "agents-test"})
    scan_id = post.json()["scan_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert data["status"] == "completed", f"Scan failed: {data}"

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield driver
    driver.close()


# ─────────────────────────────────────────────────────────────────────────────
class TestEngagementIntelligenceWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        result = EngagementIntelligenceWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "EngagementIntelligenceWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        assert EngagementIntelligenceWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_engagement_metrics(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        stats = EngagementIntelligenceWorker(seeded_driver).run("agents-test").summary_stats
        assert "total_headcount" in stats
        assert "active_headcount" in stats
        assert "inactive_rate_pct" in stats
        assert "resilience_score" in stats

    def test_resilience_score_in_range(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        stats = EngagementIntelligenceWorker(seeded_driver).run("agents-test").summary_stats
        assert 0 <= stats.get("resilience_score", 50) <= 100

    def test_has_findings(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        assert len(EngagementIntelligenceWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        for f in EngagementIntelligenceWorker(seeded_driver).run("agents-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        json.dumps(EngagementIntelligenceWorker(seeded_driver).run("agents-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestOutreachSequenceWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        result = OutreachSequenceWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "OutreachSequenceWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        assert OutreachSequenceWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_sequence_metrics(self, seeded_driver):
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        stats = OutreachSequenceWorker(seeded_driver).run("agents-test").summary_stats
        assert "prospects_found" in stats
        assert "sequences_generated" in stats

    def test_has_findings(self, seeded_driver):
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        assert len(OutreachSequenceWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_sequences_have_5_touches(self, seeded_driver):
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        result = OutreachSequenceWorker(seeded_driver).run("agents-test")
        for f in result.findings:
            seq = f.data.get("sequence")
            if seq is not None:
                assert len(seq) == 5, f"Expected 5 touches, got {len(seq)}"

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        json.dumps(OutreachSequenceWorker(seeded_driver).run("agents-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestLeadEnrichmentWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        result = LeadEnrichmentWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "LeadEnrichmentWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        assert LeadEnrichmentWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_completeness_metrics(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        stats = LeadEnrichmentWorker(seeded_driver).run("agents-test").summary_stats
        assert "total_accounts" in stats
        assert "complete_accounts" in stats
        assert "completeness_rate_pct" in stats

    def test_completeness_rate_is_percentage(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        stats = LeadEnrichmentWorker(seeded_driver).run("agents-test").summary_stats
        assert 0 <= stats.get("completeness_rate_pct", 0) <= 100

    def test_complete_plus_incomplete_equals_total(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        stats = LeadEnrichmentWorker(seeded_driver).run("agents-test").summary_stats
        assert (
            stats.get("complete_accounts", 0) + stats.get("incomplete_accounts", 0)
            == stats.get("total_accounts", 0)
        )

    def test_has_findings(self, seeded_driver):
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        assert len(LeadEnrichmentWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        json.dumps(LeadEnrichmentWorker(seeded_driver).run("agents-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestMeetingPrepWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.meeting_prep import MeetingPrepWorker
        result = MeetingPrepWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "MeetingPrepWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.meeting_prep import MeetingPrepWorker
        assert MeetingPrepWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_brief_metrics(self, seeded_driver):
        from scout.workers.meeting_prep import MeetingPrepWorker
        stats = MeetingPrepWorker(seeded_driver).run("agents-test").summary_stats
        assert "late_stage_deals" in stats
        assert "briefs_generated" in stats

    def test_has_findings(self, seeded_driver):
        from scout.workers.meeting_prep import MeetingPrepWorker
        assert len(MeetingPrepWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_briefs_have_talking_points(self, seeded_driver):
        from scout.workers.meeting_prep import MeetingPrepWorker
        result = MeetingPrepWorker(seeded_driver).run("agents-test")
        for f in result.findings:
            brief = f.data.get("brief")
            if brief is not None:
                assert "talking_points" in brief
                assert len(brief["talking_points"]) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.meeting_prep import MeetingPrepWorker
        json.dumps(MeetingPrepWorker(seeded_driver).run("agents-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestRenewalWorkflowWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        result = RenewalWorkflowWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "RenewalWorkflowWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        assert RenewalWorkflowWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_renewal_metrics(self, seeded_driver):
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        stats = RenewalWorkflowWorker(seeded_driver).run("agents-test").summary_stats
        assert "customer_accounts" in stats
        assert "high_risk_count" in stats
        assert "medium_risk_count" in stats

    def test_risk_counts_non_negative(self, seeded_driver):
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        stats = RenewalWorkflowWorker(seeded_driver).run("agents-test").summary_stats
        assert stats.get("high_risk_count", 0) >= 0
        assert stats.get("medium_risk_count", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        assert len(RenewalWorkflowWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        json.dumps(RenewalWorkflowWorker(seeded_driver).run("agents-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestCrossSellCampaignWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        result = CrossSellCampaignWorker(seeded_driver).run("agents-test")
        assert result.worker_name == "CrossSellCampaignWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        assert CrossSellCampaignWorker(seeded_driver).run("agents-test").error is None

    def test_summary_has_campaign_metrics(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        stats = CrossSellCampaignWorker(seeded_driver).run("agents-test").summary_stats
        assert "eligible_accounts" in stats
        assert "campaigns_generated" in stats
        assert "total_expansion_opportunity" in stats

    def test_campaigns_generated_lte_eligible(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        stats = CrossSellCampaignWorker(seeded_driver).run("agents-test").summary_stats
        assert stats.get("campaigns_generated", 0) <= stats.get("eligible_accounts", 0)

    def test_expansion_opportunity_non_negative(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        stats = CrossSellCampaignWorker(seeded_driver).run("agents-test").summary_stats
        assert stats.get("total_expansion_opportunity", 0) >= 0

    def test_campaign_briefs_have_required_fields(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        result = CrossSellCampaignWorker(seeded_driver).run("agents-test")
        for f in result.findings:
            brief = f.data.get("brief")
            if brief is not None:
                assert "objective" in brief
                assert "messaging_angles" in brief
                assert "channel_mix" in brief

    def test_has_findings(self, seeded_driver):
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        assert len(CrossSellCampaignWorker(seeded_driver).run("agents-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        json.dumps(CrossSellCampaignWorker(seeded_driver).run("agents-test").to_dict())
