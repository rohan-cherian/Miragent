"""
Task 19b — tests for the resolution-drafting agent.

Nothing skips, for the same reason as tests/agents/test_triage.py: every
external edge of recommend() is a named module-level seam (load_case,
load_message, load_triage_result, next_version, persist_proposed_action,
compile_pack, reasoning.complete, audit.write), so the full decision sequence
runs with no database, no Qdrant and no credentials. A skipped test proves
nothing about Rule A or Rule B.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from scout.agents import reasoning
from scout.agents import resolve as resolve_module
from scout.agents.reasoning import CallMeta
from scout.agents.resolve import (
    ALL_WITHHELD_TEXT,
    NO_CONTEXT_TEXT,
    DraftSentence,
    ResolutionOutput,
    apply_rules,
    claims_completed_action,
    pack_confidence,
    recommend,
    risk_for,
)
from scout.canonical.models import DecisionState, ProposedAction
from scout.config import settings

CASE_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()
TRIAGE_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()

CHUNK_A = "11111111-1111-1111-1111-111111111111"
CHUNK_B = "22222222-2222-2222-2222-222222222222"
UNKNOWN_CHUNK = "99999999-9999-9999-9999-999999999999"

BODY = "My licence key stopped working after the renewal went through."


# ── Fakes ─────────────────────────────────────────────────────────────────


class FakeCitation:
    def __init__(self, chunk_id: str, excerpt: str, broken_dto: bool = False):
        self.chunk_id = chunk_id
        self.excerpt = excerpt
        self.parent_text = excerpt
        self.source_system = "gmail"
        self.source_type = "comment"
        self.object_id = str(MESSAGE_ID)
        self._broken = broken_dto

    def to_dto(self) -> dict:
        if self._broken:
            raise AttributeError("'NoneType' object has no attribute 'isoformat'")
        return {
            "source_system": self.source_system,
            "source_type": self.source_type,
            "object_id": self.object_id,
            "excerpt": self.excerpt,
            "source_ts": "2026-08-18T09:00:00+00:00",
            "deep_link": "https://mail.google.com/mail/u/0/#all/x",
            "access_status": "ok",
        }


class FakePack:
    def __init__(self, low_context: bool = False, citations=None):
        self.low_context = low_context
        self.citations = citations if citations is not None else [
            FakeCitation(CHUNK_A, "The renewal completed on 4 August."),
            FakeCitation(CHUNK_B, "Licence keys are reissued from the admin console."),
        ]


class FakeCase:
    id = CASE_ID
    tenant_id = TENANT_ID
    org_id = ORG_ID
    subject = "Licence key not working after renewal"
    status = "open"
    opened_at = datetime.now(UTC)
    reopened_count = 0


class FakeMessage:
    id = MESSAGE_ID
    case_id = CASE_ID
    body_redacted = BODY
    subject = "Licence key"


def make_triage_view(**overrides) -> resolve_module._TriageView:
    defaults = dict(
        id=TRIAGE_ID,
        case_id=CASE_ID,
        message_id=MESSAGE_ID,
        category="licensing",
        intent_class="activation_failure",
        sub_category=None,
        band="high",
        confidence=0.91,
    )
    defaults.update(overrides)
    return resolve_module._TriageView(**defaults)


def make_output(**overrides) -> ResolutionOutput:
    payload = {
        "resolution_path": "reissue_licence_key",
        "confidence": 0.9,
        "sentences": [
            {"text": "Your renewal completed on 4 August.", "citation_refs": [CHUNK_A]},
            {
                "text": "I recommend reissuing the licence key from the admin console.",
                "citation_refs": [CHUNK_B],
            },
        ],
    }
    payload.update(overrides)
    return ResolutionOutput.model_validate(payload)


def make_meta() -> CallMeta:
    return CallMeta(
        agent="resolve",
        model=settings.llm_tiers[settings.agent_tier["resolve"]],
        tier=settings.agent_tier["resolve"],
        prompt_version="resolve_v1",
        tokens_in=900,
        tokens_out=180,
        cost_usd=0.004,
        latency_ms=1200,
    )


@pytest.fixture
def wired(monkeypatch):
    state = {"persisted": [], "audits": [], "complete_calls": [], "versions": []}

    def fake_compile(**kwargs):
        return state.get("pack") or FakePack()

    def fake_persist(**values):
        row = ProposedAction(**values)
        state["persisted"].append(row)
        return row

    def fake_audit(**kwargs):
        state["audits"].append(kwargs)
        return uuid.uuid4()

    def fake_next_version(case_id):
        state["versions"].append(case_id)
        return len(state["versions"])

    monkeypatch.setattr(resolve_module, "compile_pack", fake_compile)
    monkeypatch.setattr(resolve_module, "load_case", lambda case_id: FakeCase())
    monkeypatch.setattr(resolve_module, "load_message", lambda case_id, message_id: FakeMessage())
    monkeypatch.setattr(
        resolve_module,
        "load_triage_result",
        lambda triage_result_id: state.get("triage") or make_triage_view(),
    )
    monkeypatch.setattr(resolve_module, "next_version", fake_next_version)
    monkeypatch.setattr(resolve_module, "persist_proposed_action", fake_persist)
    monkeypatch.setattr(resolve_module.audit, "write", fake_audit)

    def set_completions(*results):
        queue = list(results)

        async def fake_complete(**kwargs):
            state["complete_calls"].append(kwargs)
            return queue[min(len(state["complete_calls"]) - 1, len(queue) - 1)]

        monkeypatch.setattr(reasoning, "complete", fake_complete)

    state["set_completions"] = set_completions
    set_completions((make_output(), make_meta()))
    return state


def sentences_of(row: ProposedAction) -> list[dict]:
    return row.draft_sentences


# ── Rule B in isolation ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "I have reset your password.",
        "I've issued a replacement licence key.",
        "I already refunded the duplicate charge.",
        "We have updated your subscription.",
        "We've contacted the billing team on your behalf.",
        "I reset the activation counter this morning.",
        "I sent the new key to your registered address.",
        "We refunded the charge yesterday.",
        "I went ahead and reactivated the licence.",
        "We took care of the renewal for you.",
        "As requested, I cancelled the old subscription.",
        "Your licence has been reissued.",
        "The duplicate charge have been refunded.",
        "I fixed the sync issue on our side.",
    ],
)
def test_claims_completed_action_flags_completed_claims(text):
    assert claims_completed_action(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "I recommend resetting your password.",
        "Your password can be reset from the account settings page.",
        "A replacement licence key can be issued from the admin console.",
        "The duplicate charge appears eligible for a refund.",
        "Please confirm the email address on the account.",
        "The renewal completed on 4 August according to the order record.",
        "Support will need the licence serial to proceed.",
        "This looks like an activation failure rather than a billing problem.",
        "",
    ],
)
def test_claims_completed_action_allows_suggestions(text):
    assert claims_completed_action(text) is False


# ── Rule A and Rule B applied together ────────────────────────────────────


def test_uncited_sentence_is_withheld_not_dropped():
    processed = apply_rules(
        [
            {"text": "Cited and fine.", "citation_refs": [CHUNK_A]},
            {"text": "Nothing supports this claim.", "citation_refs": [UNKNOWN_CHUNK]},
            {"text": "No refs at all.", "citation_refs": []},
        ],
        {CHUNK_A, CHUNK_B},
    )

    assert len(processed) == 3, "nothing is ever dropped from the record"
    assert processed[0].withheld is False
    assert processed[1].withheld is True and processed[1].citation_refs == []
    assert processed[2].withheld is True and processed[2].citation_refs == []
    assert "no citation" in processed[1].withheld_reason


def test_hallucinated_ref_is_stripped_but_a_real_one_still_counts():
    processed = apply_rules(
        [{"text": "Partly supported.", "citation_refs": [CHUNK_A, UNKNOWN_CHUNK]}],
        {CHUNK_A, CHUNK_B},
    )

    assert processed[0].withheld is False
    assert processed[0].citation_refs == [CHUNK_A], "the invented id is discarded"


def test_rule_b_overrides_a_valid_citation():
    processed = apply_rules(
        [{"text": "I have reissued your licence key.", "citation_refs": [CHUNK_B]}],
        {CHUNK_A, CHUNK_B},
    )

    assert processed[0].withheld is True, "being well-cited does not excuse the claim"
    assert processed[0].citation_refs == [CHUNK_B], "the citation is kept on the record"
    assert "already completed" in processed[0].withheld_reason


def test_malformed_sentences_are_skipped_not_fatal():
    processed = apply_rules(
        ["not a dict", {"citation_refs": [CHUNK_A]}, {"text": "   "},
         {"text": "Real one.", "citation_refs": CHUNK_A}],
        {CHUNK_A},
    )

    assert len(processed) == 1
    assert processed[0].text == "Real one."
    assert processed[0].citation_refs == [CHUNK_A], "a bare string ref is accepted"


# ── The low-context path ──────────────────────────────────────────────────


async def test_low_context_never_calls_the_model(wired):
    wired["pack"] = FakePack(low_context=True)

    row = await recommend(CASE_ID, TRIAGE_ID)

    assert wired["complete_calls"] == [], "no model call when there is no evidence"
    assert row.recommended_action_text == NO_CONTEXT_TEXT
    assert row.approval_required is True
    assert row.risk == "high"
    assert float(row.confidence) == 0.0
    assert row.model_name == "none"
    assert row.status == DecisionState.DRAFT_PENDING.value
    assert len(sentences_of(row)) == 1 and sentences_of(row)[0]["withheld"] is True
    assert wired["audits"][0]["outputs"]["low_context"] is True


async def test_low_context_still_writes_one_audit_row(wired):
    wired["pack"] = FakePack(low_context=True)

    await recommend(CASE_ID, TRIAGE_ID)

    assert len(wired["audits"]) == 1
    assert wired["audits"][0]["action"] == "recommendation_generated"
    assert wired["audits"][0]["case_id"] == CASE_ID


# ── The drafting path ─────────────────────────────────────────────────────


async def test_clean_draft_is_persisted_with_both_sentences_kept(wired):
    row = await recommend(CASE_ID, TRIAGE_ID)

    records = sentences_of(row)
    assert len(records) == 2
    assert all(record["withheld"] is False for record in records)
    assert "reissuing the licence key" in row.recommended_action_text
    assert row.resolution_path == "reissue_licence_key"
    assert row.approval_required is True
    assert row.status == DecisionState.DRAFT_PENDING.value
    assert row.policy_ref is None
    assert row.recommended_owner is None


async def test_past_tense_sentence_is_withheld_even_with_a_valid_citation(wired):
    wired["set_completions"](
        (
            make_output(
                sentences=[
                    {"text": "I have reissued your licence key.", "citation_refs": [CHUNK_B]},
                    {"text": "The renewal completed on 4 August.", "citation_refs": [CHUNK_A]},
                ]
            ),
            make_meta(),
        )
    )

    row = await recommend(CASE_ID, TRIAGE_ID)

    records = sentences_of(row)
    assert records[0]["withheld"] is True
    assert records[0]["citation_refs"] == [CHUNK_B]
    assert records[1]["withheld"] is False
    assert "I have reissued" not in row.recommended_action_text
    assert wired["audits"][0]["outputs"]["withheld_count"] == 1


async def test_uncited_sentence_survives_into_the_persisted_record(wired):
    wired["set_completions"](
        (
            make_output(
                sentences=[
                    {"text": "The renewal completed on 4 August.", "citation_refs": [CHUNK_A]},
                    {"text": "Your warranty also covers hardware.", "citation_refs": [UNKNOWN_CHUNK]},
                ]
            ),
            make_meta(),
        )
    )

    row = await recommend(CASE_ID, TRIAGE_ID)

    records = sentences_of(row)
    assert len(records) == 2, "the uncitable sentence is kept, marked, not lost"
    assert records[1]["withheld"] is True
    assert records[1]["citation_refs"] == []
    assert "warranty" not in row.recommended_action_text


async def test_every_sentence_withheld_falls_back_to_a_placeholder(wired):
    wired["set_completions"](
        (
            make_output(
                sentences=[
                    {"text": "I have fixed it.", "citation_refs": [CHUNK_A]},
                    {"text": "Unsupported claim.", "citation_refs": []},
                ]
            ),
            make_meta(),
        )
    )

    row = await recommend(CASE_ID, TRIAGE_ID)

    assert row.recommended_action_text == ALL_WITHHELD_TEXT
    assert float(row.confidence) == 0.0
    assert row.risk == "high"


# ── Risk and confidence are ours, not the model's ─────────────────────────


async def test_risk_is_deterministic_not_taken_from_the_model(wired):
    model_said = ResolutionOutput.model_validate(
        {
            "resolution_path": "reissue_licence_key",
            "confidence": 0.95,
            "risk": "low",  # not a schema field — dropped on validation
            "sentences": [
                {"text": "The renewal completed on 4 August.", "citation_refs": [CHUNK_A]},
                {"text": "Unsupported extra claim.", "citation_refs": []},
            ],
        }
    )
    wired["set_completions"]((model_said, make_meta()))

    row = await recommend(CASE_ID, TRIAGE_ID)

    assert not hasattr(model_said, "risk"), "ResolutionOutput has no risk field at all"
    # One of two sentences survived, so confidence is capped at 0.5 whatever
    # the model claimed — and 0.5 is below reco_medium, so risk is high.
    assert float(row.confidence) == pytest.approx(0.5)
    assert row.risk == "high"


def test_risk_thresholds_come_from_the_recommendation_settings():
    assert risk_for(settings.reco_medium - 0.01) == "high"
    assert risk_for(settings.reco_medium) == "medium"
    assert risk_for(settings.reco_high - 0.01) == "medium"
    assert risk_for(settings.reco_high) == "low"
    assert risk_for(1.0) == "low"


def test_confidence_is_capped_by_the_surviving_fraction():
    kept = DraftSentence("ok", [CHUNK_A], withheld=False)
    gone = DraftSentence("no", [], withheld=True)

    assert pack_confidence(0.9, [kept, kept]) == pytest.approx(0.9)
    assert pack_confidence(0.9, [kept, gone]) == pytest.approx(0.5)
    assert pack_confidence(0.9, [gone, gone]) == pytest.approx(0.0)
    assert pack_confidence(0.2, [kept, kept]) == pytest.approx(0.2), "never inflated"
    assert pack_confidence(5.0, [kept, kept]) == pytest.approx(1.0), "clamped to 1.0"
    assert pack_confidence(0.9, []) == 0.0


# ── version_token freshness ───────────────────────────────────────────────


async def test_version_token_is_fresh_for_every_call(wired):
    first = await recommend(CASE_ID, TRIAGE_ID)
    second = await recommend(CASE_ID, TRIAGE_ID)

    assert first.version_token != second.version_token
    uuid.UUID(first.version_token)  # a real uuid4, not a placeholder string
    uuid.UUID(second.version_token)


async def test_version_increments_across_drafts_for_the_same_case(wired):
    first = await recommend(CASE_ID, TRIAGE_ID)
    second = await recommend(CASE_ID, TRIAGE_ID)

    assert second.version > first.version, (
        "Task 20 orders by version DESC to find the latest proposed action"
    )


# ── Evidence, tier, and prompt wiring ─────────────────────────────────────


async def test_evidence_carries_the_packs_citation_dtos(wired):
    row = await recommend(CASE_ID, TRIAGE_ID)

    assert isinstance(row.evidence, list) and len(row.evidence) == 2
    assert {dto["access_status"] for dto in row.evidence} == {"ok"}


async def test_a_citation_that_cannot_serialise_degrades_to_missing(wired):
    wired["pack"] = FakePack(
        citations=[FakeCitation(CHUNK_A, "fine"), FakeCitation(CHUNK_B, "broken", broken_dto=True)]
    )

    row = await recommend(CASE_ID, TRIAGE_ID)

    statuses = [dto["access_status"] for dto in row.evidence]
    assert statuses == ["ok", "missing"], "drafting survives an unserialisable citation"


async def test_tier_is_left_to_config_for_the_resolve_agent(wired):
    await recommend(CASE_ID, TRIAGE_ID)

    call = wired["complete_calls"][0]
    assert call["agent"] == "resolve"
    assert "tier" not in call or call["tier"] is None, (
        "the agent never picks a tier — settings.agent_tier['resolve'] does"
    )
    assert call["schema"] is ResolutionOutput


def test_prompt_version_is_declared_by_the_template():
    assert resolve_module.prompt_version() == "resolve_v1"


def test_prompt_template_states_both_hard_rules():
    text = resolve_module.PROMPT_PATH.read_text(encoding="utf-8")

    for placeholder in ("{{CATEGORY}}", "{{INTENT_CLASS}}", "{{SUB_CATEGORY}}",
                        "{{CITATIONS}}", "{{SUBJECT}}", "{{BODY}}"):
        assert placeholder in text
    assert "citation_refs" in text
    assert "I have reset your password" in text, "forbidden phrasing example"
    assert "I recommend resetting your password" in text, "acceptable alternative"


def test_built_prompt_lists_every_citation_id():
    messages = resolve_module.build_messages(
        FakePack(), make_triage_view(), FakeCase(), FakeMessage()
    )
    content = messages[0]["content"]

    assert CHUNK_A in content and CHUNK_B in content
    assert "licensing" in content and "activation_failure" in content
    assert BODY in content
    assert "{{" not in content, "every placeholder must be filled"
