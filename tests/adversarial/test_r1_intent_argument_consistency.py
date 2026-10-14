"""Explicit name constraints must survive policy-to-dispatch transitions."""

import json
from dataclasses import replace

import pytest

from civicgate.audit.trace import Trace
from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import TOOLS, Proposal, Search
from scripts.evaluate_channel_a_semantics import ScriptedJudge
from tests.adversarial.test_a1_execution_boundary import CountingAdapter
from tests.adversarial.test_r1_named_literals import RecordingSearch

GOOD = JudgeSignal(classification="IN_SCOPE", confidence=1, available=True)
BASE = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
CONTEXT = (True, True, 0.85, 0)
NAMES = [
    ("agency", "awarding_agency", "Example Office", '"Example Office"'),
    ("recipient", "recipient_name", "Cooperativa El Niño", '"Cooperativa El Niño"'),
    ("agencia", "awarding_agency", "Oficina Álamo", r'"Oficina \u00c1lamo"'),
    ("destinatario", "recipient_name", 'O\'Reilly "Research"', json.dumps('O\'Reilly "Research"')),
    ("agency", "awarding_agency", "研究局", r'"\u7814\u7a76\u5c40"'),
    ("recipient", "recipient_name", "Élan Foundation", '"Élan Foundation"'),
    ("agency", "awarding_agency", "Office / Science", r'"Office \/ Science"'),
    ("recipient", "recipient_name", "Science 🧪", r'"Science \ud83e\uddea"'),
]


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("agent_k", [True, False])
@pytest.mark.parametrize("label,field,value,literal", NAMES)
@pytest.mark.parametrize(
    "relationship", ["missing", "different", "wrong_field", "detail", "resolver"]
)
async def test_name_mismatch_receives_no_gateway_authority(
    label, field, value, literal, relationship, required, agent_k
):
    request = f"Get public records for {label} {literal}."
    wrong_field = "recipient_name" if field == "awarding_agency" else "awarding_agency"
    arguments = {
        "missing": BASE,
        "different": BASE | {field: "Other Agency"},
        "wrong_field": BASE | {wrong_field: value},
        "detail": {"award_id": "1"},
        "resolver": {"recipient_name": value},
    }[relationship]
    tool = {"detail": "get_federal_award", "resolver": "resolve_federal_recipient"}.get(
        relationship, "find_federal_awards"
    )
    proposal = Proposal(tool=tool, arguments=arguments)
    original = proposal.model_dump_json()
    backend = CountingAdapter()
    trace = Trace()
    result = await Gateway(
        backend, ScriptedJudge(GOOD), trace, require_judge=required, enable_agent_k=agent_k
    ).call(request, proposal)
    assert result.decision == "REVIEW_REQUIRED"
    assert not result.tool_executed and backend.calls == []
    assert result.dispatch_state == "NOT_DISPATCHED"
    policy = next(e for e in trace.events if e["stage"] == "policy")
    assert policy["policy"]["decision"] == "REVIEW_REQUIRED"
    assert policy["binding_issued"] is False
    assert "execution_started" not in [e["stage"] for e in trace.events]
    assert trace.events[0]["user_request"] == request
    assert proposal.model_dump_json() == original
    assert json.loads(policy["facts"]["arguments_json"]) == TOOLS[tool].model_validate(
        arguments
    ).model_dump(mode="json")


@pytest.mark.parametrize("tool", ["find_federal_awards", "summarize_federal_spending"])
@pytest.mark.parametrize("label,field,value,literal", NAMES)
async def test_matching_names_reach_only_the_exact_effective_search(
    tool, label, field, value, literal
):
    backend = RecordingSearch()
    trace = Trace()
    result = await Gateway(backend, ScriptedJudge(GOOD), trace).call(
        f"Get public records for {label} {literal}.",
        Proposal(tool=tool, arguments=BASE | {field: value}),
    )
    assert result.decision == "PERMIT" and result.tool_executed
    assert len(backend.filters) == 1 and backend.filters[0][field] == value
    assert trace.events[-1]["pre_dispatch_verification"] == "PASS"
    policy = next(e for e in trace.events if e["stage"] == "policy")
    assert policy["binding_issued"] is True
    assert json.loads(policy["facts"]["arguments_json"])[field] == value


@pytest.mark.parametrize(
    "literal,proposal_value,expected",
    [
        ('"  Example Office  "', " Example Office ", "PERMIT"),
        (r'"\u0045xample Office"', "Example Office", "PERMIT"),
        ('"Élan"', "E\u0301lan", "REVIEW_REQUIRED"),
        ('"Élan"', "Elan", "REVIEW_REQUIRED"),
        ('"Example Office"', "EXAMPLE OFFICE", "REVIEW_REQUIRED"),
        ('"Example Office"', "Example  Office", "REVIEW_REQUIRED"),
        ('"Example Office"', "Example\u00a0Office", "REVIEW_REQUIRED"),
        ('"ABC"', "ＡＢＣ", "REVIEW_REQUIRED"),
        ('"ABC"', "АBC", "REVIEW_REQUIRED"),
    ],
)
async def test_only_schema_whitespace_and_json_decoding_are_equivalent(
    literal, proposal_value, expected
):
    backend = RecordingSearch()
    result = await Gateway(backend, ScriptedJudge(GOOD), Trace()).call(
        f"Get public records for agency {literal}.",
        Proposal(tool="find_federal_awards", arguments=BASE | {"awarding_agency": proposal_value}),
    )
    assert result.decision == expected
    assert len(backend.filters) == int(expected == "PERMIT")


@pytest.mark.parametrize("tool", ["find_federal_awards", "summarize_federal_spending"])
@pytest.mark.parametrize("agency", ["Example Office", "Other Agency"])
@pytest.mark.parametrize("recipient", ["Example Foundation", "Other Recipient"])
async def test_all_constraints_require_their_own_matching_role(tool, agency, recipient):
    backend = RecordingSearch()
    request = 'Get public records for agency "Example Office" recipient "Example Foundation".'
    result = await Gateway(backend, ScriptedJudge(GOOD), Trace()).call(
        request,
        Proposal(
            tool=tool, arguments=BASE | {"awarding_agency": agency, "recipient_name": recipient}
        ),
    )
    matching = agency == "Example Office" and recipient == "Example Foundation"
    assert result.decision == ("PERMIT" if matching else "REVIEW_REQUIRED")
    assert len(backend.filters) == int(matching)


async def test_conflicting_repeated_literals_cannot_select_just_one_target():
    backend = CountingAdapter()
    result = await Gateway(backend, ScriptedJudge(GOOD), Trace()).call(
        'Get public records for agency "Example Office" agency "Other Agency".',
        Proposal(
            tool="find_federal_awards", arguments=BASE | {"awarding_agency": "Example Office"}
        ),
    )
    assert result.decision == "REVIEW_REQUIRED" and backend.calls == []


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("agent_k", [True, False])
@pytest.mark.parametrize("matching", [True, False])
@pytest.mark.parametrize(
    "label,field",
    [
        ("recipient", "recipient_name"),
        ("recİpient", "recipient_name"),
        ("destİnatario", "recipient_name"),
        ("deſtinatario", "recipient_name"),
        ("agency", "awarding_agency"),
        ("agencİa", "awarding_agency"),
    ],
)
async def test_unicode_label_recognition_cannot_change_the_field_role(
    label, field, matching, required, agent_k
):
    value = "Example Foundation"
    other = "awarding_agency" if field == "recipient_name" else "recipient_name"
    backend = RecordingSearch()
    trace = Trace()
    result = await Gateway(
        backend, ScriptedJudge(GOOD), trace, require_judge=required, enable_agent_k=agent_k
    ).call(
        f'Get public records for {label} "Example Foundation".',
        Proposal(
            tool="find_federal_awards",
            arguments=BASE | {field: value if matching else "Other Entity", other: value},
        ),
    )
    policy = next(e for e in trace.events if e["stage"] == "policy")
    # An unrelated returned recipient may cause a post-result review. The oracle
    # here is the authorization decision and actual pre-dispatch boundary.
    assert policy["policy"]["decision"] == ("PERMIT" if matching else "REVIEW_REQUIRED")
    assert policy["binding_issued"] is matching
    assert result.tool_executed is matching
    assert len(backend.filters) == int(matching)
    if matching:
        assert backend.filters[0][field] == value


@pytest.mark.parametrize("raw", [None, "{broken}", '"Example Office"', "[]", "null", "{}"])
def test_named_policy_without_valid_effective_context_requires_review(raw):
    facts = PolicyFacts(
        tool="find_federal_awards",
        text='Get public records for agency "Example Office".',
        arguments_json=raw,
    )
    result = evaluate(facts, GOOD, KSignal())
    assert result.decision == "REVIEW_REQUIRED"
    assert "NAME_LITERAL_PROPOSAL_UNAVAILABLE" in result.reasons


def test_actual_binding_cannot_differ_from_matching_policy_facts():
    request = 'Get public records for agency "Example Office".'
    matching = BASE | {"awarding_agency": "Example Office"}
    facts = PolicyFacts(
        tool="find_federal_awards",
        text=request,
        arguments_json=Search.model_validate(matching).model_dump_json(),
    )
    boundary = ExecutionBoundary(TOOLS)
    with pytest.raises(ExecutionBoundaryError, match="POLICY_ARGUMENTS_MISMATCH"):
        boundary.evaluate(
            request_id="synthetic-consistency",
            facts=facts,
            judge=GOOD,
            agent_k=KSignal(),
            threshold=0.85,
            arguments=BASE | {"awarding_agency": "Other Agency"},
            policy_context=CONTEXT,
        )
    assert boundary._issued == {}
    accepted = boundary.evaluate(
        request_id="synthetic-consistency",
        facts=facts,
        judge=GOOD,
        agent_k=KSignal(),
        threshold=0.85,
        arguments=matching,
        policy_context=CONTEXT,
    )
    assert accepted.policy.decision == "PERMIT" and accepted.envelope is not None
    binding = boundary.consume(
        accepted.envelope,
        request_id="synthetic-consistency",
        tool=facts.tool,
        arguments=matching,
        policy_context=CONTEXT,
    )
    assert json.loads(binding.arguments_json)["awarding_agency"] == "Example Office"
    assert boundary._issued == {}


def test_missing_snapshot_does_not_create_an_a1_envelope_for_a_named_request():
    boundary = ExecutionBoundary(TOOLS)
    result = boundary.evaluate(
        request_id="synthetic-missing",
        facts=PolicyFacts(
            tool="find_federal_awards", text='Get public records for agency "Example Office".'
        ),
        judge=GOOD,
        agent_k=KSignal(),
        threshold=0.85,
        arguments=BASE | {"awarding_agency": "Example Office"},
        policy_context=CONTEXT,
    )
    assert result.policy.decision == "REVIEW_REQUIRED" and result.envelope is None
    assert boundary._issued == {}


def test_legacy_unnamed_facts_and_hard_denial_precedence_remain_intact():
    facts = PolicyFacts(tool="get_federal_award", text="Public award research")
    assert evaluate(facts, GOOD, KSignal()).decision == "PERMIT"
    denied = replace(
        facts,
        text='Execute payment. Get public records for agency "Example Office".',
        arguments_json="{broken}",
    )
    assert evaluate(denied, GOOD, KSignal()).decision == "DENY"


async def test_proposal_hard_denial_is_not_downgraded_to_a_name_mismatch():
    backend = CountingAdapter()
    result = await Gateway(backend, ScriptedJudge(GOOD), Trace()).call(
        'Get public records for agency "Example Office".',
        Proposal(
            tool="find_federal_awards", arguments=BASE | {"awarding_agency": "Execute payment"}
        ),
    )
    assert result.decision == "DENY" and backend.calls == []
