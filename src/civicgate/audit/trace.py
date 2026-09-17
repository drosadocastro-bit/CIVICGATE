import json
import re
from pathlib import Path
from typing import Any

from civicgate.models.provenance import utcnow


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(r"key|token|password|credential|authorization|secret", key, re.I)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
        value = re.sub(
            r"(?i)((?:api[_ -]?key|token|password|secret|credential)\s*[:=]\s*)\S+",
            r"\1[REDACTED]",
            value,
        )
        return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


class Trace:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []

    def record(self, request_id: str, stage: str, **fields: Any) -> None:
        event = redact(
            {"request_id": request_id, "timestamp": utcnow().isoformat(), "stage": stage, **fields}
        )
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        self.events.append(event)
        # Process-local diagnostic window, not long-term agent memory.
        del self.events[:-1000]
