"""Tests-only bootstrap for a received HTTP200 followed by a synthetic body fault.

The actual v4 composition, producer, Gateway, budget and guarded adapter methods
remain unchanged. This launcher has no live transport or production authority.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

from evals.harness import eval_002b_composition_v4 as composition
from evals.harness.evidence import write_new


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mini04-stream-fault", choices=("timeout", "readerror"), required=True)
    options, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    original_adapter = composition.GuardedSyntheticAdapter

    class ReceivedFailureAdapter(original_adapter):
        def __init__(self, ledger, mode, budget):
            super().__init__(ledger, mode, budget)
            original = self.transport
            assert type(original) is httpx.MockTransport and original is self._retained_transport
            assert mode == "normal" and self.max_attempts == 1 and self.fixture is True
            stats = {
                "selected_fault": options.mini04_stream_fault,
                "body_stream_entered": False,
                "chunks_yielded": 0,
                "raised_error_class": None,
                "original_mock_type_exact": True,
                "retained_mock_type_exact": False,
                "retained_identity_matches": False,
                "composition_module": composition.__name__,
                "composition_path": str(Path(composition.__file__).resolve()),
                "composition_sha256": hashlib.sha256(
                    Path(composition.__file__).read_bytes()
                ).hexdigest(),
                "worker_fixture_path": str(Path(__file__).resolve()),
                "worker_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }

            class FailingBody(httpx.AsyncByteStream):
                def __init__(self, request):
                    self.request = request

                async def __aiter__(self):
                    stats["body_stream_entered"] = True
                    stats["chunks_yielded"] += 1
                    yield b'{"synthetic":'
                    exc_type = (
                        httpx.ReadTimeout
                        if options.mini04_stream_fault == "timeout"
                        else httpx.ReadError
                    )
                    stats["raised_error_class"] = exc_type.__name__
                    write_new(ledger.directory / "mini04-stream-evidence.json", stats)
                    raise exc_type("MINI04_SYNTHETIC_RECEIVED_BODY_FAILURE", request=self.request)

                async def aclose(self):
                    return None

            async def respond(request):
                # The original MockTransport logs its genuine entered/HTTP200
                # return. Only the returned body stream is a new test fixture.
                response = await original.handle_async_request(request)
                assert response.status_code == 200
                headers = dict(response.headers)
                await response.aclose()
                return httpx.Response(
                    200, headers=headers, stream=FailingBody(request), request=request
                )

            retained = httpx.MockTransport(respond)
            self.transport = retained
            self._retained_transport = retained
            stats["retained_mock_type_exact"] = type(self.transport) is httpx.MockTransport
            stats["retained_identity_matches"] = self.transport is self._retained_transport

    composition.GuardedSyntheticAdapter = ReceivedFailureAdapter
    composition.main()


if __name__ == "__main__":
    main()
