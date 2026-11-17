"""Fresh four-stage OFFLINE composition over existing runner/MCP/Gateway seams.
LIVE is hard blocked. All HTTP replies are explicit fixtures, not natural inference.
"""

import asyncio
import sqlite3
import sys
from pathlib import Path

from . import common
from . import runner_host71 as runner
from . import util71 as n
from . import util71 as p

MODE = common.MODE
PROVENANCE = "HOST71_FRESH_CHAIN_PROVIDER_ATTEMPT"
GAPS = [
    "LIVE_PARTIAL_BODY_UNAVAILABLE_IF_BASE_TRANSPORT_FAILS_BEFORE_RETURN",
    "LIVE_HOST_RELEASE_NOT_IMPLEMENTED_OR_AUTHORIZED",
    "NO_NEW_LIVE_APPROVAL_OR_MONETARY_ENFORCEMENT",
    "FIXTURE_NATURAL_TEXT_IS_NOT_REAL_MODEL_GENERATION",
]


def _wire_receipt(read, stage):
    root = read / "captured-wires" / stage
    observed = p.parse(p.read(root / "observed.json"))
    reserved = p.parse(p.read(root / "reserved.json"))
    request = p.read(root / "request.bin")
    raw = p.read(root / "response.bin")
    p.require(not (root / "unknown.json").exists(), "UNKNOWN_WIRE_HOLD")
    if stage == "public_read":
        p.require(
            observed["state"] == "BODY_OBSERVED_NOT_VALIDATED"
            and observed["request_sha256"] == p.sha(request)
            and observed["response_sha256"] == p.sha(raw)
            and observed["status_code"] == 200,
            "PUBLIC_CAPTURE_HOLD",
        )
        return {
            "stage": stage,
            "request_sha256": p.sha(request),
            "response_sha256": p.sha(raw),
            "observed_ns": observed["observed_ns"],
            "status_code": 200,
        }
    p.require(
        reserved["state"] == "CONSUMED_OUTCOME_UNKNOWN"
        and reserved["request_sha256"] == p.sha(request)
        and reserved["provider"] == ("judge" if stage == "judge" else "nemotron")
        and observed["state"] == "BODY_OBSERVED_NOT_TYPED"
        and observed["facts"]["body_sha256"] == p.sha(raw)
        and observed["facts"]["http_status"] == 200,
        "MODEL_CAPTURE_HOLD",
    )
    return {
        "stage": stage,
        "observation": reserved["observation"],
        "response_facts_ack": observed["ack"],
        "request_sha256": p.sha(request),
        "response_sha256": p.sha(raw),
        "status_code": 200,
        "observed_ns": observed["observed_ns"],
    }


def reconcile(root, turn):
    read = root / "read"
    folder = common.public_path(read, turn)
    session = p.parse(p.read(read / "session.json"))
    summary_raw = p.read(folder / "summary.json")
    summary = p.parse(summary_raw)
    intake_raw = p.read(folder / "intake.json")
    intake = p.parse(intake_raw)
    returned = p.parse(p.read(folder / "returned.json"))
    receipt = p.parse(p.read(folder / "server-receipt.json"))
    p.require(
        returned == dict(summary, custody="CLOSED", summary_sha256=p.sha(summary_raw)),
        "RETURNED_LINK_HOLD",
    )
    obs = session["run_id"] + "_" + turn
    p.require(
        intake["question"] == p.QUESTION
        and intake["request_sha256"] == p.sha(p.QUESTION.encode())
        and intake["turn"] == turn
        and intake["owner"] == "PUBLIC_API_READ"
        and intake["planner_selected"] == "nemotron"
        and intake["mode"] == "LIVE"
        and summary["intake_sha256"] == p.sha(intake_raw),
        "INTAKE_HOLD",
    )
    from .public_read_v11.contract import expected_proposal

    expected = expected_proposal(p.QUESTION).model_dump(mode="json")
    p.require(
        summary["proposal"] == expected
        and receipt["proposal_sha256"] == p.sha(p.canonical(expected)),
        "PROPOSAL_HOLD",
    )
    p.require(
        session["mode"] == "LIVE"
        and session["fresh_host71"] is True
        and session["root"] == str(read)
        and summary["run_id"] == session["run_id"]
        and summary["turn"] == turn
        and summary["observation"] == obs
        and summary["request"] == p.QUESTION
        and summary["mode"] == "LIVE"
        and summary["live_authorized"] is True
        and summary["owner"] == "PUBLIC_API_READ"
        and summary["backend_kind"] == "USASPENDING_FIXED_READ_V11"
        and summary["decision"] == "PERMIT"
        and summary["verification"] == "RESULT_VERIFIED"
        and summary["error"] is None
        and summary["graph_status"] == "COMPLETED",
        "FRESH_READ_HOLD",
    )
    for key in ("binding_issued", "binding_consumed", "adapter_entries", "backend_attempts"):
        p.require(summary[key] == receipt[key] == 1, "READ_COUNTS_HOLD")
    p.require(
        receipt["observation"] == obs
        and receipt["request_sha256"] == p.sha(p.QUESTION.encode())
        and receipt["response"] == summary["response"]
        and receipt["governance_sha256"] == p.sha(p.read(folder / "governance-observations.jsonl")),
        "RECEIPT_BINDING_HOLD",
    )
    wires = {stage: _wire_receipt(read, stage) for stage in ("planner", "judge", "public_read")}
    p.require(
        all(wires[role]["observation"] == obs for role in ("planner", "judge")),
        "EXACT_CAPTURE_OBSERVATION_HOLD",
    )
    p.require(
        wires["planner"]["observed_ns"]
        < wires["judge"]["observed_ns"]
        < wires["public_read"]["observed_ns"],
        "STAGE_ORDER_HOLD",
    )
    http = summary["public_http_attempts"]
    p.require(
        len(http) == 1
        and receipt["public_http_attempts"] == http
        and http[0]["outcome"] == "RESPONSE_VALIDATED"
        and http[0]["body_sha256"] == wires["public_read"]["response_sha256"],
        "PUBLIC_WIRE_HOLD",
    )
    dbpath = p.safe(read / "custody.sqlite")
    with sqlite3.connect(dbpath.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        p.require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "DB_HOLD")
        rows = {
            table: [dict(r) for r in db.execute("SELECT * FROM " + table)]
            for table in (
                "meta",
                "observations",
                "observation_fences",
                "mcp_calls",
                "attempts",
                "send_leases",
                "request_contexts",
                "response_facts",
            )
        }
    p.require(
        len(rows["meta"])
        == len(rows["observations"])
        == len(rows["observation_fences"])
        == len(rows["mcp_calls"])
        == 1,
        "DB_COUNTS_HOLD",
    )
    meta = rows["meta"][0]
    fence = rows["observation_fences"][0]
    mcp = rows["mcp_calls"][0]
    p.require(
        meta["run_id"] == session["run_id"]
        and meta["stopped"] == 0
        and p.parse(meta["role_caps"]) == {"planner": 1, "judge": 1},
        "DB_META_HOLD",
    )
    p.require(
        fence["observation_id"] == obs
        and fence["state"] == "CLOSED"
        and fence["summary_sha256"] == p.sha(summary_raw),
        "CLOSED_READ_REQUIRED",
    )
    p.require(
        mcp["observation_id"] == obs
        and mcp["state"] == "TERMINAL"
        and mcp["outcome"] == "CLIENT_RESPONSE_OBSERVED"
        and mcp["proposal_sha256"] == receipt["proposal_sha256"],
        "MCP_HOLD",
    )
    p.require(
        len(rows["attempts"]) == len(rows["send_leases"]) == len(rows["request_contexts"]) == 2
        and {a["role"] for a in rows["attempts"]} == {"planner", "judge"},
        "ATTEMPT_COUNTS_HOLD",
    )
    for attempt in rows["attempts"]:
        role = attempt["role"]
        reservation = p.parse(attempt["reservation_json"])
        context = next(r for r in rows["request_contexts"] if r["role"] == role)
        context = p.parse(context["context_json"])
        lease = next(r for r in rows["send_leases"] if r["attempt_id"] == attempt["attempt_id"])
        p.require(
            attempt["observation_id"] == obs
            and attempt["state"] == "TERMINAL"
            and attempt["outcome"] == "RESPONSE_OBSERVED"
            and attempt["retry_count"] == 0
            and reservation["request_sha256"] == wires[role]["request_sha256"]
            and context["request_sha256"] == reservation["request_sha256"]
            and context["observation_id"] == obs
            and lease["state"] == "CONSUMED"
            and p.parse(lease["binding_json"]) == dict(context, attempt_id=attempt["attempt_id"]),
            "LEASE_LINK_HOLD",
        )
    p.require(len(rows["response_facts"]) == 2, "RESPONSE_FACTS_REQUIRED")
    for attempt in rows["attempts"]:
        facts = next(
            row for row in rows["response_facts"] if row["attempt_id"] == attempt["attempt_id"]
        )
        doc = p.parse(facts["facts_json"])
        ack = wires[attempt["role"]]["response_facts_ack"]
        p.require(
            doc["body_sha256"] == wires[attempt["role"]]["response_sha256"]
            and doc["typed_schema"] == "NOT_PARSED"
            and facts["facts_sha256"] == p.sha(facts["facts_json"].encode())
            and ack["facts_sha256"] == facts["facts_sha256"]
            and facts["acknowledged_at_utc"] <= attempt["completed_at_utc"],
            "RESPONSE_FACTS_LINK_HOLD",
        )
        typed = (
            summary["planner_attempt"] if attempt["role"] == "planner" else receipt["judge_attempt"]
        )
        p.require(typed.get("typed_accepted") is True, "TYPED_ACCEPTANCE_REQUIRED")
    p.require(summary["result"] == summary["response"]["result"], "RESULT_RESPONSE_LINK_HOLD")
    from .public_read_v11.response_contract_v2 import LIVE_PAYLOAD, normalize_search

    raw_public = p.parse(p.read(read / "captured-wires/public_read/response.bin"))
    request_public = p.parse(p.read(read / "captured-wires/public_read/request.bin"))
    p.require(request_public == LIVE_PAYLOAD, "PUBLIC_QUERY_HOLD")
    normalized = normalize_search(raw_public, request_public)
    mapping = {
        "Award ID": "award_id",
        "Recipient Name": "recipient_name",
        "Award Amount": "award_amount",
        "Awarding Agency": "awarding_agency",
    }
    expected_rows = [
        {mapping.get(k, k): v for k, v in row.items()} for row in normalized["results"]
    ]
    p.require(summary["result"]["records"] == expected_rows, "RAW_TO_RECORDS_HOLD")
    records = summary["result"]["records"]
    p.require(len(records) == 5, "EXACT_FIVE_FRESH_ROWS_REQUIRED")
    projected = []
    for index, row in enumerate(records, 1):
        p.require(
            all(
                type(row.get(field)) is str and row[field]
                for field in ("award_id", "recipient_name", "award_amount", "awarding_agency")
            ),
            "FRESH_FIELDS_HOLD",
        )
        projected.append(
            dict(
                record_id=f"R{index}",
                **{
                    field: row[field]
                    for field in ("award_id", "recipient_name", "award_amount", "awarding_agency")
                },
            )
        )
    files = [
        read / "session.json",
        read / "custody.sqlite",
        *folder.iterdir(),
        *(read / "captured-wires").rglob("*"),
    ]
    hashes = {str(file.relative_to(root)): p.sha(p.read(file)) for file in files if file.is_file()}
    payload = {
        "question": p.QUESTION,
        "records": projected,
        "scope": "Fresh same-turn partial public LIVE page.",
        "source": "FRESH_SAME_TURN_LIVE_PUBLIC_READ",
    }
    return {
        "turn": turn,
        "observation": obs,
        "payload": payload,
        "source_files": hashes,
        "snapshot_sha256": p.sha(p.canonical(hashes)),
        "stage_order": ["planner", "judge", "public_read"],
        "response_facts_rows": 2,
    }


async def execute_host(root, profile, read_anchor, chain_anchor, secret_store, registry):
    from . import host_final71 as final
    from . import host_gate71 as gate
    from . import host_runtime71 as host

    gate.require_release()  # Before paths, preparation, secrets or any network.
    admission = host.prepare(root, profile, read_anchor, chain_anchor, secret_store, registry)
    root = Path(root).resolve()
    try:
        async with asyncio.timeout(300):
            view = await runner.run_turn(
                root / "read", p.QUESTION, "nemotron", Path(sys.executable)
            )
            proof = reconcile(root, view["turn"])
            admission.check_stage("answer")
            record = p.parse(p.read(root / "read/session.json"))
            from civicgate.windows_dpapi import WindowsDPAPIStore

            secrets = host.AdmittedSecrets71(
                WindowsDPAPIStore(Path(record["secret_store"])), admission, "answer"
            )
            answer = await final.execute(
                root / "answer",
                proof["payload"],
                proof,
                admission,
                secrets,
                lambda: reconcile(root, view["turn"]),
            )
            p.require(answer["status"] == "REVIEW_REQUIRED", "FINAL_HOST_HOLD")
            terminal = _terminal(view["turn"], proof, answer, profile.source_inventory_sha256)
            n._write(root / "host-terminal.json", p.canonical(terminal))
            return terminal
    except (Exception, asyncio.CancelledError):
        try:
            n._write(
                root / "host-unknown.json",
                p.canonical({"state": "UNKNOWN_CONSUMED", "retry_allowed": False}),
            )
        except OSError:
            pass
        return {
            "state": "UNKNOWN_CONSUMED",
            "retry_allowed": False,
            "release_allowed": False,
            "external_requests": None,
            "stage_counts": {k: None for k in ("planner", "judge", "public_read", "answer")},
        }


def _terminal(turn, proof, answer, inventory):
    return {
        "state": "HOST71_REVIEW_REQUIRED",
        "turn": turn,
        "read_proof": proof,
        "answer": answer,
        "stage_counts": {"planner": 1, "judge": 1, "public_read": 1, "answer": 1},
        "source_inventory_sha256": inventory,
        "external_requests": 4,
        "release_allowed": False,
        "publication_allowed": False,
        "verified_answer": False,
        "write_allowed": False,
    }


def read_host(root):
    from . import host_final71 as final

    try:
        root = p.safe(root).resolve()
        p.require(not (root / "host-unknown.json").exists(), "HOST_UNKNOWN_HOLD")
        terminal = p.parse(p.read(root / "host-terminal.json"))
        from .transport_profile_v1 import ChatProfile, verify_candidate

        session = p.parse(p.read(root / "read/session.json"))
        profile = ChatProfile.model_validate(session["profile"])
        verify_candidate(profile.source_inventory_sha256, profile.catalog_sha256)
        reservation = p.parse(p.read(root / "host-reservation.json"))
        registry = p.safe(reservation["registry"]).resolve()
        p.require(
            not registry.is_relative_to(root) and not root.is_relative_to(registry),
            "FENCE_PATH_HOLD",
        )
        p.require(
            p.read(registry / (p.sha(p.QUESTION.encode()) + ".consumed.json"))
            == p.read(root / "host-reservation.json")
            and p.sha(p.read(Path(session["anchor"]))) == reservation["read_anchor_sha256"]
            and p.sha(p.read(Path(session["chain_anchor"]))) == reservation["anchor_sha256"],
            "EXTERNAL_HOST_BINDING_HOLD",
        )
        p.require(
            reservation["profile_sha256"] == profile.digest
            and reservation["source_inventory_sha256"] == profile.source_inventory_sha256
            and reservation["output"] == str(root)
            and p.canonical(reservation["counts"])
            == p.canonical({"planner": 1, "judge": 1, "public_read": 1, "answer": 1}),
            "HOST_RESERVATION_HOLD",
        )
        proof = reconcile(root, terminal["turn"])
        p.require(proof == terminal["read_proof"], "FRESH_READ_BINDING_HOLD")
        answer = final.read_run(root / "answer", proof["payload"], proof)
        p.require(
            answer.get("status") == "REVIEW_REQUIRED"
            and p.canonical(terminal)
            == p.canonical(
                _terminal(terminal["turn"], proof, answer, profile.source_inventory_sha256)
            ),
            "EXACT_HOST_TERMINAL_HOLD",
        )
        return terminal
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, sqlite3.Error):
        return {"state": "UNKNOWN_CONSUMED", "release_allowed": False, "retry_allowed": False}
