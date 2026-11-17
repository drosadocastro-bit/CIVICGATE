"""Dormant fresh answer-only host transport. Import is inert; release gate stays closed."""

import asyncio
import time

import httpx

from . import answer_contract71 as schema
from . import host_gate71 as gate
from . import util71 as n
from . import util71 as p

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
MAX_RESPONSE = 32000
DEADLINE = 60


def body(payload):
    request = schema.body(payload)
    request["messages"][0]["content"] = (
        request["messages"][0]["content"]
        .replace("historical", "fresh same-turn")
        .replace("retained", "same-turn")
    )
    wire = p.parse(request["messages"][1]["content"])
    wire["scope"] = (
        "Fresh same-turn partial public READ page. Query filters are search context, not record facts. Human semantic review is required."
    )
    request["messages"][1]["content"] = p.canonical(wire).decode()
    p.require(
        request["model"] == MODEL
        and request["max_tokens"] == 2000
        and request["reasoning_budget"] == 256
        and request["stream"] is False
        and request["chat_template_kwargs"] == {"enable_thinking": False}
        and "tools" not in request
        and "tool_choice" not in request,
        "ANSWER_REQUEST_CONTRACT_HOLD",
    )
    return request


def result(status, error=None, *, test=False, attempted=False):
    return {
        "status": status,
        "error": error,
        "draft_text": None,
        "claims": [],
        "release_allowed": False,
        "publication_allowed": False,
        "verified_answer": False,
        "approved": False,
        "live_allowed": False,
        "retry_allowed": False,
        "write_allowed": False,
        "released_answer": None,
        "text": None,
        "semantic_status": "NOT_VERIFIED",
        "provenance": "MOCK_TRANSPORT_TEST" if test else "HOST71_FRESH_ANSWER_ONLY",
        "dispatch_attempted": attempted,
        "external_requests": 0 if test or not attempted else None,
        "model_executed": False if test or not attempted else None,
        "provider_cost_preflight": "HOST_APPROVAL_REQUIRED_NOT_A_BILLING_GUARANTEE",
    }


def _check(admission, reconcile, proof):
    admission.check_stage("answer")
    p.require(reconcile() == proof, "FRESH_SOURCE_CHANGED_HOLD")


def _bindings(payload, proof, request_raw):
    return {
        "payload_sha256": p.sha(p.canonical(payload)),
        "proof_sha256": p.sha(p.canonical(proof)),
        "request_sha256": p.sha(request_raw),
    }


async def execute(root, payload, proof, admission, secrets, reconcile, *, _test_transport=None):
    # No filesystem, admission, credential or transport work before this gate.
    gate.require_release()
    test = _test_transport is not None
    p.require(
        not test or type(_test_transport) is httpx.MockTransport,
        "EXACT_MOCK_TEST_TRANSPORT_REQUIRED",
    )
    root = p.safe(root).resolve()
    p.require(root.parent.is_dir() and not root.exists(), "EXCLUSIVE_ANSWER_ROOT_REQUIRED")
    p.require(proof.get("payload") == payload, "PAYLOAD_PROOF_HOLD")
    request = body(payload)
    request_raw = p.canonical(request)
    p.require(len(request_raw) <= 32768, "ANSWER_REQUEST_SIZE_HOLD")
    _check(admission, reconcile, proof)
    root.mkdir(exist_ok=False)
    attempted = False
    raw = bytearray()
    key_bytes = None
    response = None
    transport = None
    bindings = _bindings(payload, proof, request_raw)
    try:
        n._write(
            root / "reserved.json",
            p.canonical(
                dict(
                    bindings,
                    state="CONSUMED_OUTCOME_UNKNOWN",
                    test_transport=test,
                    model=MODEL,
                    endpoint=ENDPOINT,
                    retry_allowed=False,
                )
            ),
        )
        _check(admission, reconcile, proof)
        key = secrets.get_secret("CIVICGATE_NVIDIA_API_KEY")
        p.require(
            type(key) is str and 1 <= len(key) <= 2048 and all(33 <= ord(c) <= 126 for c in key),
            "CREDENTIAL_MISSING_OR_UNSAFE",
        )
        key_bytes = key.encode("ascii")
        p.require(key_bytes not in request_raw, "SENSITIVE_REQUEST_HOLD")
        n._write(root / "request.json", request_raw)
        _check(admission, reconcile, proof)
        if not test:
            transport = httpx.AsyncHTTPTransport(
                retries=0,
                trust_env=False,
                http2=False,
                verify=True,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            )
        else:
            transport = _test_transport
        sent = httpx.Request(
            "POST",
            ENDPOINT,
            content=request_raw,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        sent.extensions["timeout"] = {
            name: DEADLINE for name in ("connect", "read", "write", "pool")
        }
        # Exact final admission/source recheck before the only delegate entry.
        _check(admission, reconcile, proof)
        async with asyncio.timeout(DEADLINE):
            attempted = True
            response = await transport.handle_async_request(sent)
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > MAX_RESPONSE:
                    raise ValueError("RESPONSE_SIZE_HOLD")
                raw.extend(chunk)
            p.require(key_bytes not in raw, "SENSITIVE_RESPONSE_HOLD")
        n._write(root / "response.bin", bytes(raw))
        n._write(
            root / "observed.json",
            p.canonical(
                {
                    "state": "BODY_OBSERVED_NOT_TYPED",
                    "response_sha256": p.sha(bytes(raw)),
                    "status_code": response.status_code,
                    "observed_ns": time.time_ns(),
                    "test_transport": test,
                    "dispatch_attempted": True,
                }
            ),
        )
        p.require(response.status_code == 200, "HTTP_OUTCOME_HOLD")
        _check(admission, reconcile, proof)
        checked = schema.validate(bytes(raw), payload)
        p.require(checked["status"] == "REVIEW_REQUIRED", "DRAFT_VALIDATION_HOLD")
        value = result("REVIEW_REQUIRED", test=test, attempted=True)
        value.update(
            draft_text=checked["draft_text"],
            claims=checked["claims"],
            deterministic_checks=checked["deterministic_checks"],
            request_sha256=p.sha(request_raw),
            response_sha256=p.sha(bytes(raw)),
            proof_sha256=bindings["proof_sha256"],
            model_response_observed=True,
        )
        n._write(
            root / "terminal.json",
            p.canonical({"result": value, "result_sha256": p.sha(p.canonical(value)), **bindings}),
        )
        return read_run(root, payload, proof)
    except BaseException as error:
        sensitive = key_bytes is not None and key_bytes in raw
        if raw and not sensitive and not (root / "response.bin").exists():
            n._write(root / "partial.bin", bytes(raw))
        value = result("UNKNOWN_CONSUMED", "ANSWER_HELD_NO_RETRY", test=test, attempted=attempted)
        try:
            n._write(
                root / "unknown.json",
                p.canonical({"result": value, "sensitive_capture_withheld": sensitive}),
            )
        except (ValueError, OSError):
            pass
        if isinstance(error, asyncio.CancelledError):
            raise asyncio.CancelledError() from None
        return value
    finally:
        # Cleanup errors never release a draft or retry the request.
        if response is not None:
            try:
                await response.aclose()
            except Exception:
                pass
        if transport is not None:
            try:
                await transport.aclose()
            except Exception:
                pass
        key_bytes = None


def read_run(root, payload, proof):
    try:
        root = p.safe(root).resolve()
        p.require(proof.get("payload") == payload, "PAYLOAD_PROOF_HOLD")
        p.require(not (root / "unknown.json").exists(), "UNKNOWN_CAPTURE_HOLD")
        reserved = p.parse(p.read(root / "reserved.json"))
        terminal = p.parse(p.read(root / "terminal.json"))
        request_raw = p.read(root / "request.json")
        raw = p.read(root / "response.bin")
        observed = p.parse(p.read(root / "observed.json"))
        bindings = _bindings(payload, proof, request_raw)
        p.require(
            request_raw == p.canonical(body(payload))
            and all(reserved[k] == terminal[k] == v for k, v in bindings.items()),
            "FRESH_BINDINGS_HOLD",
        )
        p.require(
            reserved["state"] == "CONSUMED_OUTCOME_UNKNOWN"
            and reserved["model"] == MODEL
            and reserved["endpoint"] == ENDPOINT
            and reserved["retry_allowed"] is False
            and type(reserved["test_transport"]) is bool,
            "RESERVATION_HOLD",
        )
        p.require(
            observed["state"] == "BODY_OBSERVED_NOT_TYPED"
            and observed["status_code"] == 200
            and observed["response_sha256"] == p.sha(raw)
            and observed["test_transport"] == reserved["test_transport"]
            and observed["dispatch_attempted"] is True,
            "OBSERVED_HOLD",
        )
        checked = schema.validate(raw, payload)
        value = terminal["result"]
        expected = result("REVIEW_REQUIRED", test=reserved["test_transport"], attempted=True)
        expected.update(
            draft_text=checked.get("draft_text"),
            claims=checked.get("claims"),
            deterministic_checks=checked.get("deterministic_checks"),
            request_sha256=p.sha(request_raw),
            response_sha256=p.sha(raw),
            proof_sha256=bindings["proof_sha256"],
            model_response_observed=True,
        )
        p.require(
            checked["status"] == "REVIEW_REQUIRED"
            and value == expected
            and terminal["result_sha256"] == p.sha(p.canonical(value)),
            "DRAFT_READBACK_HOLD",
        )
        return value
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, RecursionError):
        return result("UNKNOWN_CONSUMED", "ANSWER_READBACK_HOLD")
