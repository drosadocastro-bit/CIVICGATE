"""Exact JSON value spans for source provenance; no normalization or source repair."""

from __future__ import annotations

import json

from civicgate.rq6.core import decode_exact, require


def json_value_slice(raw: bytes, pointer: tuple[str | int, ...]) -> bytes:
    """Resolve a unique structural pointer and retain the original selected bytes.

    Custody adapters must derive pointers from the frozen source schema/selector,
    never filename order or model content. Duplicate keys/nonfinite values STOP.
    """
    decode_exact(raw)
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    selected: tuple[int, int] | None = None

    def whitespace(offset: int) -> int:
        while offset < len(text) and text[offset] in " \r\n\t":
            offset += 1
        return offset

    def value(offset: int, path: tuple[str | int, ...]) -> int:
        nonlocal selected
        start = whitespace(offset)
        offset = start
        if text[offset] == "{":
            offset = whitespace(offset + 1)
            while text[offset] != "}":
                key, offset = decoder.raw_decode(text, offset)
                require(type(key) is str, "SOURCE_OBJECT_KEY")
                offset = whitespace(offset)
                require(text[offset] == ":", "SOURCE_OBJECT_COLON")
                offset = whitespace(value(offset + 1, (*path, key)))
                if text[offset] != ",":
                    break
                offset = whitespace(offset + 1)
            require(text[offset] == "}", "SOURCE_OBJECT_END")
            offset += 1
        elif text[offset] == "[":
            offset = whitespace(offset + 1)
            index = 0
            while text[offset] != "]":
                offset = whitespace(value(offset, (*path, index)))
                index += 1
                if text[offset] != ",":
                    break
                offset = whitespace(offset + 1)
            require(text[offset] == "]", "SOURCE_ARRAY_END")
            offset += 1
        else:
            _, offset = decoder.raw_decode(text, offset)
        if path == pointer:
            require(selected is None, "SOURCE_POINTER_NOT_UNIQUE")
            selected = (start, offset)
        return offset

    value(0, ())
    require(selected is not None, "SOURCE_POINTER_MISSING")
    assert selected is not None
    return text[selected[0] : selected[1]].encode("utf-8")
