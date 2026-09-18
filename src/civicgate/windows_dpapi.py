"""Optional Windows-user DPAPI store.

This module is an edge integration. Core governance imports no DPAPI symbols.
The encrypted JSON file is protected for the current Windows user and machine
using CryptProtectData; it is not a portable credential backup.
"""

import base64
import ctypes
import json
import os
from ctypes import POINTER, Structure, c_char, string_at
from pathlib import Path

from civicgate.runtime_config import ConfigurationProvider, SecretProvider


class _Blob(Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", POINTER(c_char))]


class WindowsDPAPIStore(ConfigurationProvider, SecretProvider):
    """DPAPI-backed mapping for explicit local Windows configuration."""

    def __init__(self, path: Path) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsDPAPIStore requires Windows")
        if not path.is_absolute():
            raise ValueError("DPAPI store path must be absolute")
        self.path = path

    def _protect(self, value: bytes) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = _Blob(len(value), ctypes.cast(source_buffer, POINTER(c_char)))
        destination = _Blob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
        ):
            raise OSError("CryptProtectData failed")
        try:
            return string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(destination.pbData)

    def _unprotect(self, value: bytes) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = _Blob(len(value), ctypes.cast(source_buffer, POINTER(c_char)))
        destination = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)
        ):
            raise OSError("CryptUnprotectData failed")
        try:
            return string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(destination.pbData)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
        ):
            raise ValueError("DPAPI store is malformed")
        return {
            key: self._unprotect(base64.b64decode(value)).decode("utf-8")
            for key, value in raw.items()
        }

    def set_value(self, name: str, value: str) -> None:
        if not name or "\x00" in name or "\x00" in value:
            raise ValueError("DPAPI names and values must be non-empty and NUL-free")
        values = self._read()
        values[name] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = {
            key: base64.b64encode(self._protect(item.encode("utf-8"))).decode("ascii")
            for key, item in values.items()
        }
        self.path.write_text(json.dumps(encoded, indent=2) + "\n", encoding="utf-8")

    def get(self, name: str) -> str | None:
        return self._read().get(name)

    def get_secret(self, name: str) -> str | None:
        return self.get(name)
