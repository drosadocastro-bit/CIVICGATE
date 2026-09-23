"""Synthetic encrypted entries only; never use native DPAPI or the real store."""

import base64
import json

import pytest

from civicgate.windows_dpapi import WindowsDPAPIStore
from scripts import dpapi_secret

OPENAI = "CIVICGATE_OPENAI_JUDGE_API_KEY"
ANTHROPIC = "CIVICGATE_ANTHROPIC_JUDGE_API_KEY"


class SyntheticStore(WindowsDPAPIStore):
    def __init__(self, path):
        # Portable test double: bypass only the Windows constructor, not get/set/list.
        self.path = path
        self.decrypted = []
        self.encrypted = []

    def _protect(self, value):
        self.encrypted.append(value)
        return b"test-cipher:" + value

    def _unprotect(self, value):
        self.decrypted.append(value)
        if not value.startswith(b"test-cipher:"):
            raise OSError("SENSITIVE_FAILURE_SENTINEL")
        return value.removeprefix(b"test-cipher:")


def blob(value):
    return base64.b64encode(b"test-cipher:" + value.encode()).decode()


@pytest.fixture
def store(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real DPAPI must never be called")

    monkeypatch.setattr(WindowsDPAPIStore, "_windll", forbidden)
    result = SyntheticStore(tmp_path / "synthetic.json")
    result.path.write_text(
        json.dumps({OPENAI: blob("openai-synthetic"), ANTHROPIC: blob("anthropic-synthetic")})
    )
    return result


@pytest.mark.parametrize("method", ["get", "get_secret"])
def test_only_requested_entry_is_decrypted(store, method):
    assert getattr(store, method)(OPENAI) == "openai-synthetic"
    assert store.decrypted == [b"test-cipher:openai-synthetic"]
    assert store.encrypted == []


@pytest.mark.parametrize("method", ["get", "get_secret"])
def test_missing_binding_does_not_decrypt_or_fallback(store, method):
    assert getattr(store, method)("CIVICGATE_JUDGE_API_KEY") is None
    assert store.decrypted == store.encrypted == []


def test_missing_file_does_not_decrypt(tmp_path):
    store = SyntheticStore(tmp_path / "absent.json")
    assert store.get_secret(OPENAI) is None and store.list_names() == []
    assert store.decrypted == store.encrypted == []
    assert not store.path.exists()


def test_list_names_and_cli_list_never_decrypt(store, monkeypatch, capsys):
    monkeypatch.setattr(dpapi_secret, "WindowsDPAPIStore", lambda path: store)
    assert dpapi_secret.main(["--path", str(store.path), "list"]) == 0
    assert capsys.readouterr().out.splitlines() == sorted([OPENAI, ANTHROPIC])
    assert store.decrypted == store.encrypted == []


@pytest.mark.parametrize("bad", ["not-valid-base64!", base64.b64encode(b"corrupt-cipher").decode()])
def test_unrelated_corrupt_ciphertext_is_not_decoded_or_decrypted(store, bad):
    values = json.loads(store.path.read_text())
    values[ANTHROPIC] = bad
    store.path.write_text(json.dumps(values))
    assert store.get_secret(OPENAI) == "openai-synthetic"
    assert store.decrypted == [b"test-cipher:openai-synthetic"]
    assert store.list_names() == sorted([OPENAI, ANTHROPIC])


@pytest.mark.parametrize("bad", ["not-valid-base64!", base64.b64encode(b"corrupt-cipher").decode()])
def test_requested_corrupt_entry_fails_without_fallback_or_value_exposure(store, bad):
    values = json.loads(store.path.read_text())
    values[OPENAI] = bad
    store.path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="Requested DPAPI entry could not be decrypted") as exc:
        store.get_secret(OPENAI)
    assert "SENSITIVE_FAILURE_SENTINEL" not in str(exc.value)
    assert bad not in str(exc.value)
    assert len(store.decrypted) <= 1
    assert b"test-cipher:anthropic-synthetic" not in store.decrypted


def test_update_encrypts_one_value_and_preserves_other_ciphertext(store):
    before = json.loads(store.path.read_text())
    store.set_value(OPENAI, "replacement-synthetic")
    after = json.loads(store.path.read_text())
    assert after[ANTHROPIC] == before[ANTHROPIC]
    assert after[OPENAI] == blob("replacement-synthetic")
    assert store.encrypted == [b"replacement-synthetic"]
    assert store.decrypted == []


def test_add_preserves_existing_and_corrupt_ciphertexts(store):
    values = json.loads(store.path.read_text())
    values[ANTHROPIC] = "corrupt-but-preserved"
    store.path.write_text(json.dumps(values))
    store.set_value("NEW_SYNTHETIC", "new-value")
    after = json.loads(store.path.read_text())
    assert all(after[k] == v for k, v in values.items())
    assert store.decrypted == [] and store.encrypted == [b"new-value"]


def test_failed_encryption_leaves_file_unchanged(store, monkeypatch):
    before = store.path.read_bytes()

    def fail(value):
        raise OSError("SENSITIVE_FAILURE_SENTINEL")

    monkeypatch.setattr(store, "_protect", fail)
    with pytest.raises(OSError):
        store.set_value(OPENAI, "replacement")
    assert store.path.read_bytes() == before and store.decrypted == []


@pytest.mark.parametrize("raw", ["[]", '{"name": 123}', "{"])
def test_malformed_container_fails_before_crypto(store, raw):
    store.path.write_text(raw)
    with pytest.raises(ValueError):
        store.get_secret(OPENAI)
    assert store.decrypted == store.encrypted == []


def test_cli_error_does_not_echo_sensitive_exception(store, monkeypatch, capsys):
    def fail(*args):
        raise ValueError("SENSITIVE_FAILURE_SENTINEL")

    monkeypatch.setattr(dpapi_secret, "WindowsDPAPIStore", lambda path: store)
    monkeypatch.setattr(store, "list_names", fail)
    assert dpapi_secret.main(["--path", str(store.path), "list"]) == 1
    assert "SENSITIVE_FAILURE_SENTINEL" not in capsys.readouterr().out
