import pytest

from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway


@pytest.fixture
def gateway() -> Gateway:
    return Gateway(fixture_adapter(), MockProvider(), Trace())


@pytest.fixture
def search_args() -> dict[str, object]:
    return {"start_date": "2024-10-01", "end_date": "2025-09-30", "state_code": "PR"}
