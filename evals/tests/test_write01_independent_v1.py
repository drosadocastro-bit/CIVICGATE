"""Independent custody-channel contradiction probes; genuine SQLite backend."""

import pytest

from evals.write01.authority_v1 import HostApproval
from evals.write01.contract_v1 import READ_TOOL, WRITE_TOOL, digest
from evals.write01.demo_v1 import DATASET, REQUEST, query
from evals.write01.gateway_v1 import AuditSink, WriteGatewayV1
from evals.write01.store_v1 import ReviewStore


def gateway_store(tmp_path):
    store = ReviewStore.initialize(tmp_path / "review.sqlite", DATASET, "STORE")
    proposed = query()
    approvals = (
        HostApproval.for_operation(REQUEST, WRITE_TOOL, proposed, "OWNER", "STORE", "WRITE", True),
        HostApproval.for_operation(
            "Read synthetic review status.",
            READ_TOOL,
            {"award_id": proposed["award_id"]},
            "OWNER",
            "STORE",
            "READ",
            True,
        ),
    )
    gateway = WriteGatewayV1(
        store,
        "OWNER",
        "STORE",
        approvals,
        AuditSink(tmp_path / "audit.jsonl"),
        run_id="INDEPENDENT",
    )
    return gateway, store, proposed


def test_false_closed_ack_does_not_override_actual_open_sqlite(tmp_path, monkeypatch):
    gateway, store, proposed = gateway_store(tmp_path)
    monkeypatch.setattr(
        store,
        "acknowledge",
        lambda operation_id, receipt_sha256: {
            "operation_id": operation_id,
            "receipt_sha256": receipt_sha256,
            "custody": "CLOSED",
            "human_acceptance": "NOT_ESTABLISHED",
        },
    )
    result = gateway.call(REQUEST, WRITE_TOOL, proposed)
    assert result.decision == "PERMIT" and result.binding_consumed
    assert store.checkpoint()["intents"][0]["custody"] == "OPEN"
    assert result.custody != "CLOSED"
    assert result.result_verification != "VERIFIED" and result.result is None


def test_wrong_ack_identity_does_not_release_verified_result(tmp_path, monkeypatch):
    gateway, store, proposed = gateway_store(tmp_path)
    acknowledge = store.acknowledge

    def wrong_identity(operation_id, receipt_sha256):
        ack = acknowledge(operation_id, receipt_sha256)
        return {**ack, "operation_id": "UNRELATED-OPERATION", "receipt_sha256": "0" * 64}

    monkeypatch.setattr(store, "acknowledge", wrong_identity)
    result = gateway.call(REQUEST, WRITE_TOOL, proposed)
    assert result.decision == "PERMIT" and result.binding_consumed
    assert store.checkpoint()["intents"][0]["custody"] == "CLOSED"
    assert result.result_verification != "VERIFIED" and result.result is None


@pytest.mark.parametrize("channel", ["commit", "acknowledge"])
def test_malformed_receipt_type_preserves_stopped_owner(tmp_path, monkeypatch, channel):
    gateway, store, proposed = gateway_store(tmp_path)
    original = getattr(store, channel)

    def malformed(*args):
        original(*args)
        return None

    monkeypatch.setattr(store, channel, malformed)
    result = gateway.call(REQUEST, WRITE_TOOL, proposed)
    assert result.result_verification == "UNKNOWN" and result.result is None
    second = gateway.call(
        "Read synthetic review status.", READ_TOOL, {"award_id": proposed["award_id"]}
    )
    assert second.reasons == ["OWNER_STOPPED_NO_AUTOMATIC_RECOVERY"]
    assert second.adapter_entries == 0 and not second.binding_issued


def test_authorized_overlay_read_preserves_committed_database_bytes(tmp_path):
    gateway, store, proposed = gateway_store(tmp_path)
    write = gateway.call(REQUEST, WRITE_TOOL, proposed)
    assert write.result_verification == "VERIFIED" and write.custody == "CLOSED"
    before = store.path.read_bytes()
    read = gateway.call(
        "Read synthetic review status.", READ_TOOL, {"award_id": proposed["award_id"]}
    )
    assert read.decision == "PERMIT" and read.binding_issued and read.binding_consumed
    assert read.result_verification == "VERIFIED" and read.result["version"] == 1
    assert read.result["notes"] == [proposed["reviewer_note"]]
    assert read.custody == "READ_ONLY_NO_FENCE"
    assert store.path.read_bytes() == before


def test_false_open_ack_prevents_binding_consumption_and_adapter(tmp_path, monkeypatch):
    gateway, store, proposed = gateway_store(tmp_path)

    def false_open(operation_id, operation, binding_sha256):
        return {
            "operation_id": operation_id,
            "custody": "OPEN",
            "operation_sha256": digest(operation),
            "binding_sha256": binding_sha256,
        }

    monkeypatch.setattr(store, "reserve", false_open)
    result = gateway.call(REQUEST, WRITE_TOOL, proposed)
    assert result.decision == "PERMIT" and result.binding_issued
    assert not result.binding_consumed and result.adapter_entries == 0
    assert result.result is None and result.result_verification == "UNKNOWN"
    assert not store.checkpoint()["intents"] and not store.checkpoint()["notes"]
    assert store.snapshot(proposed["award_id"])["version"] == 0


def test_gateway_refuses_mismatched_store_context_at_construction(tmp_path):
    store = ReviewStore.initialize(tmp_path / "review.sqlite", DATASET, "REAL-STORE")
    approval = HostApproval.for_operation(
        REQUEST, WRITE_TOOL, query(), "OWNER", "OTHER-STORE", "WRITE", True
    )
    with pytest.raises(ValueError):
        WriteGatewayV1(
            store,
            "OWNER",
            "OTHER-STORE",
            (approval,),
            AuditSink(tmp_path / "audit.jsonl"),
            run_id="INDEPENDENT",
        )
    assert not store.checkpoint()["intents"] and not store.checkpoint()["notes"]
