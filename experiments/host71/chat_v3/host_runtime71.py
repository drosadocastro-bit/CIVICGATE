"""Dormant host-only preparation/runtime. No writes or credential reads on import."""

import time
from pathlib import Path

from . import common
from . import host_gate71 as gate
from . import util71 as n
from . import util71 as p
from .chat_custody_v1 import ChatCustody
from .transport_profile_v1 import ChatProfile, LiveAdmission

COUNTS = {"planner": 1, "judge": 1, "public_read": 1, "answer": 1}
LIMITS = {"planner": 512, "judge": 512, "answer": 2000, "answer_reasoning": 256}


class HostAdmission71:
    def __init__(self, profile, read_anchor, chain_anchor):
        self.profile = profile
        self.base = LiveAdmission(profile, Path(read_anchor))
        self.chain_anchor = p.safe(chain_anchor).resolve()
        p.require(
            not self.chain_anchor.is_relative_to(common.HERE)
            and not self.chain_anchor.is_relative_to(Path(profile.custody_root)),
            "INDEPENDENT_CHAIN_ANCHOR_REQUIRED",
        )
        self.anchor_sha = p.sha(p.read(self.chain_anchor))
        self.check()

    def check(self):
        self.base.check()
        raw = p.read(self.chain_anchor)
        p.require(p.sha(raw) == self.anchor_sha, "CHAIN_ANCHOR_CHANGED")
        value = p.parse(raw)
        p.require(
            set(value)
            == {
                "decision",
                "profile_sha256",
                "source_inventory_sha256",
                "question",
                "counts",
                "limits",
                "issued_at",
                "expires_at",
                "nvidia_free_only",
                "judge_max_usd",
                "billing_risk_accepted",
                "no_retry_no_fallback",
            },
            "CHAIN_APPROVAL_SCHEMA",
        )
        p.require(
            value["decision"] == "HUMAN_APPROVED_HOST71_FRESH_CHAIN"
            and value["profile_sha256"] == self.profile.digest
            and value["source_inventory_sha256"] == self.profile.source_inventory_sha256
            and value["question"] == p.QUESTION
            and type(value["counts"]) is dict
            and type(value["limits"]) is dict
            and value["counts"] == COUNTS
            and all(type(v) is int for v in value["counts"].values())
            and value["limits"] == LIMITS
            and all(type(v) is int for v in value["limits"].values())
            and value["nvidia_free_only"] is True
            and value["judge_max_usd"] == "0.05"
            and value["billing_risk_accepted"] is True
            and value["no_retry_no_fallback"] is True,
            "CHAIN_APPROVAL_SCOPE",
        )
        now = time.time()
        issued = value["issued_at"]
        expires = value["expires_at"]
        p.require(
            type(issued) in (int, float)
            and type(expires) in (int, float)
            and issued <= now < expires
            and 0 < expires - issued <= 300,
            "CHAIN_APPROVAL_EXPIRED",
        )
        p.require(
            self.profile.planner == "nemotron"
            and self.profile.planner_attempt_limit == 1
            and self.profile.judge_attempt_limit == 1
            and self.profile.observation_limit == 1
            and self.profile.public_api_attempt_limit == 1
            and self.profile.smoke_read_only
            and self.profile.allowed_request_sha256 == p.sha(p.QUESTION.encode()),
            "EXACT_PROFILE_REQUIRED",
        )

    def check_stage(self, role):
        p.require(role in COUNTS, "STAGE_SCOPE")
        self.check()


def prepare(root, profile, read_anchor, chain_anchor, secret_store, registry):
    gate.require_release()
    root = p.safe(root).resolve()
    secret_store = p.safe(secret_store)
    p.require(
        root.is_absolute()
        and secret_store.is_absolute()
        and Path(profile.custody_root) == root / "read",
        "HOST_PATH_SCOPE",
    )
    admission = HostAdmission71(profile, read_anchor, chain_anchor)
    registry = p.safe(registry).resolve()
    p.require(
        not registry.is_relative_to(common.HERE)
        and not registry.is_relative_to(root)
        and not root.is_relative_to(registry),
        "INDEPENDENT_HOST_REGISTRY",
    )
    p.require(
        p.parse(p.read(registry / "registry.json")) == {"schema": "HOST71_REAL_CHAIN_REGISTRY_V1"},
        "HOST_REGISTRY_REQUIRED",
    )
    p.require(not root.exists(), "FRESH_HOST_ROOT_REQUIRED")
    reservation = {
        "state": "CONSUMED_OUTCOME_UNKNOWN",
        "question_sha256": p.sha(p.QUESTION.encode()),
        "profile_sha256": profile.digest,
        "anchor_sha256": admission.anchor_sha,
        "source_inventory_sha256": profile.source_inventory_sha256,
        "counts": COUNTS,
        "output": str(root),
        "registry": str(registry),
        "read_anchor_sha256": p.sha(p.read(Path(read_anchor))),
    }
    n._write(registry / (p.sha(p.QUESTION.encode()) + ".consumed.json"), p.canonical(reservation))
    root.mkdir()
    n._write(root / "host-reservation.json", p.canonical(reservation))
    ChatCustody.create_profile(profile, admission=admission)
    read = root / "read"
    (read / "turns").mkdir()
    (read / "captured-wires").mkdir()
    common.save(
        read / "session.json",
        {
            "mode": "LIVE",
            "fresh_host71": True,
            "root": str(read),
            "run_id": profile.experiment,
            "source_sha256": common.verify_sources(),
            "profile": profile.model_dump(mode="json"),
            "anchor": str(p.safe(read_anchor).resolve()),
            "chain_anchor": str(admission.chain_anchor),
            "secret_store": str(secret_store),
            "approved_planners": ["nemotron"],
            "write_host_approval": False,
            "free_text_read": False,
            "write_request": "DISABLED_HOST71",
            "overlay_request": "DISABLED_HOST71",
            "write_query": {},
            "write_store_id": None,
        },
    )
    return admission


class AdmittedSecrets71:
    """Host-controlled store wrapper; exact role/key and fresh approval before lookup."""

    def __init__(self, store, admission, role):
        self.store, self.admission, self.role = store, admission, role

    def get_secret(self, name):
        gate.require_release()
        expected = (
            "CIVICGATE_OPENAI_JUDGE_API_KEY" if self.role == "judge" else "CIVICGATE_NVIDIA_API_KEY"
        )
        p.require(
            name == expected and self.role in ("planner", "judge", "answer"), "ROLE_SECRET_SCOPE"
        )
        self.admission.check_stage(self.role)
        return self.store.get_secret(name)


def open_runtime(record, *, worker_observation=None):
    gate.require_release()
    p.require(
        record["mode"] == "LIVE"
        and record.get("fresh_host71") is True
        and record["write_host_approval"] is False,
        "HOST71_SESSION_REQUIRED",
    )
    profile = ChatProfile.model_validate(record["profile"])
    admission = HostAdmission71(profile, Path(record["anchor"]), Path(record["chain_anchor"]))
    budget = ChatCustody(Path(record["root"]) / "custody.sqlite", record["run_id"])
    p.require(
        budget.mode == "LIVE"
        and budget.profile == profile
        and record["root"] == profile.custody_root,
        "HOST71_CUSTODY_REQUIRED",
    )
    if worker_observation is not None:
        budget.join_observation(*worker_observation)
    budget.ensure_recoverable()
    from civicgate.windows_dpapi import WindowsDPAPIStore

    # Inert constructor only after admission. Existing provider retrieves role key.
    return (
        budget,
        admission,
        AdmittedSecrets71(
            WindowsDPAPIStore(Path(record["secret_store"])),
            admission,
            "judge" if worker_observation else "planner",
        ),
    )
