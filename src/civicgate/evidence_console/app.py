"""Local evidence views and an explicit, opt-in synthetic demonstration boundary."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from .reader import EvidenceStore, SafeEvidenceError, strict_json

if TYPE_CHECKING:
    from .chat_execution_v1 import ChatExecutor
    from .demo_execution_v1 import DemoExecutor
    from .evidence_advisor_v1 import AdvisorService

HERE = Path(__file__).resolve().parent
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
HOST_PATTERN = re.compile(r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?\Z")
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class LocalReadBoundary(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        csrf_token: str | None = None,
        post_paths: Iterable[str] = (),
    ) -> None:
        super().__init__(app)
        self.csrf_token = csrf_token
        self.post_paths = frozenset(post_paths)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response | None = None
        raw_hosts = [v for k, v in request.scope["headers"] if k.lower() == b"host"]
        host = raw_hosts[0].decode("ascii", errors="replace") if len(raw_hosts) == 1 else ""
        client = request.client.host if request.client else ""
        try:
            local_client = ipaddress.ip_address(client).is_loopback
        except ValueError:
            local_client = False
        raw_origins = [v for k, v in request.scope["headers"] if k.lower() == b"origin"]
        origin = request.headers.get("origin")
        origin_ok = not origin
        if origin:
            try:
                parsed = urlsplit(origin)
                origin_ok = (
                    parsed.scheme == "http"
                    and parsed.netloc == host
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and parsed.username is None
                )
            except ValueError:
                origin_ok = False
        if (
            not local_client
            or not HOST_PATTERN.fullmatch(host)
            or not origin_ok
            or len(raw_origins) > 1
        ):
            response = JSONResponse({"error": "LOCAL_ACCESS_REQUIRED"}, status_code=403)
        elif request.headers.get("sec-fetch-site", "none") not in {"none", "same-origin"}:
            response = JSONResponse({"error": "LOCAL_ACCESS_REQUIRED"}, status_code=403)
        elif (
            request.method == "POST"
            and self.csrf_token is not None
            and request.url.path in self.post_paths
        ):
            headers = [
                value
                for key, value in request.scope["headers"]
                if key.lower() == b"x-civicgate-csrf"
            ]
            supplied = request.headers.get("x-civicgate-csrf", "")
            cookie = request.cookies.get("civicgate_demo_csrf", "")
            if (
                len(raw_origins) != 1
                or not origin
                or len(headers) != 1
                or len(supplied) > 128
                or len(cookie) > 128
                or not hmac.compare_digest(
                    supplied.encode("utf-8"), self.csrf_token.encode("ascii")
                )
                or not hmac.compare_digest(cookie.encode("utf-8"), self.csrf_token.encode("ascii"))
            ):
                response = JSONResponse({"error": "CSRF_REQUIRED"}, status_code=403)
            elif request.url.query:
                response = JSONResponse({"error": "QUERY_OVERRIDES_FORBIDDEN"}, status_code=400)
            elif (
                sum(key.lower() == b"content-type" for key, _ in request.scope["headers"]) != 1
                or request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                response = JSONResponse({"error": "JSON_REQUIRED"}, status_code=415)
        elif request.method != "GET":
            response = JSONResponse(
                {"error": "READ_ONLY_GET_REQUIRED"}, status_code=405, headers={"Allow": "GET"}
            )
        elif len(request.url.path) > 512 or len(request.url.query) > 512:
            response = JSONResponse({"error": "REQUEST_LIMIT"}, status_code=400)
        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                # Never reflect exception strings, local paths or capture contents.
                response = JSONResponse({"error": "EVIDENCE_UNAVAILABLE"}, status_code=503)
        for key, value in HEADERS.items():
            response.headers[key] = value
        return response


def create_app(
    entries: list[dict[str, Any]],
    *,
    executor: DemoExecutor | None = None,
    advisor: AdvisorService | None = None,
    chat: ChatExecutor | None = None,
) -> FastAPI:
    historical_entries = tuple(dict(entry) for entry in entries)
    EvidenceStore(list(historical_entries))
    csrf_token = (
        secrets.token_urlsafe(32)
        if executor is not None or advisor is not None or chat is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if executor is not None:
                await asyncio.to_thread(executor.shutdown)
            if advisor is not None:
                await asyncio.to_thread(advisor.shutdown)
            if chat is not None:
                await asyncio.to_thread(chat.shutdown)

    app = FastAPI(
        title="CIVICGATE Evidence Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    post_paths: list[str] = []
    if executor is not None:
        post_paths.append("/api/demo/executions")
    if advisor is not None:
        post_paths.append("/api/advisor/analyses")
    if chat is not None:
        post_paths.append("/api/chat/turns")
    app.add_middleware(LocalReadBoundary, csrf_token=csrf_token, post_paths=post_paths)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/assets", StaticFiles(directory=str(HERE / "static")), name="assets")

    def checked_id(value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise SafeEvidenceError("NOT_FOUND")
        return value

    def store() -> EvidenceStore:
        fresh = executor.evidence_entries() if executor is not None else []
        chat_entries = chat.evidence_entries() if chat is not None else []
        return EvidenceStore([*historical_entries, *fresh, *chat_entries])

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "active": "runs",
                "interactive": executor is not None,
                "advisor_enabled": advisor is not None,
                "chat_enabled": chat is not None,
                **context,
            },
        )

    @app.exception_handler(SafeEvidenceError)
    async def safe_error(request: Request, exc: SafeEvidenceError) -> Response:
        status = 404 if exc.code in {"NOT_FOUND", "UNKNOWN_RUN", "UNKNOWN_OBSERVATION"} else 503
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"error": "NOT_FOUND" if status == 404 else "EVIDENCE_UNAVAILABLE"},
                status_code=status,
            )
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "active": "runs",
                "status": status,
                "interactive": executor is not None,
                "advisor_enabled": advisor is not None,
                "chat_enabled": chat is not None,
            },
            status_code=status,
        )

    @app.get("/health", response_model=None)
    def health() -> dict[str, str | bool]:
        mode = (
            "SYNTHETIC_CHAT_AND_E2E_LOCAL"
            if chat is not None and executor is not None
            else "SYNTHETIC_CHAT_LOCAL"
            if chat is not None
            else "SYNTHETIC_E2E_LOCAL"
            if executor is not None
            else "READ_ONLY"
        )
        return {
            "service": "evidence-console",
            "mode": mode,
            "execution_authority": False,
        }

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        return render(request, "overview.html", runs=store().list_runs())

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str) -> HTMLResponse:
        return render(request, "run.html", run=store().get_run(checked_id(run_id)))

    @app.get("/runs/{run_id}/observations/{observation_id}", response_class=HTMLResponse)
    def observation_page(request: Request, run_id: str, observation_id: str) -> HTMLResponse:
        observation = store().get_observation(checked_id(run_id), checked_id(observation_id))
        response = render(
            request, "observation.html", observation=observation, csrf_token=csrf_token
        )
        if advisor is not None and csrf_token is not None:
            response.set_cookie(
                "civicgate_demo_csrf",
                csrf_token,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        return response

    @app.get("/api/runs", response_model=None)
    def runs_api() -> dict[str, Any]:
        return {"runs": store().list_runs(), "mode": "READ_ONLY"}

    @app.get("/api/runs/{run_id}", response_model=None)
    def run_api(run_id: str) -> dict[str, Any]:
        return store().get_run(checked_id(run_id))

    @app.get("/api/runs/{run_id}/observations/{observation_id}", response_model=None)
    def observation_api(run_id: str, observation_id: str) -> dict[str, Any]:
        return store().get_observation(checked_id(run_id), checked_id(observation_id))

    if executor is not None:
        active_executor = executor

        @app.get("/demonstrations", response_class=HTMLResponse)
        def demonstration_page(request: Request) -> HTMLResponse:
            response = render(
                request,
                "interactive.html",
                active="execute",
                csrf_token=csrf_token,
                capabilities=active_executor.capabilities(),
            )
            if csrf_token is not None:
                response.set_cookie(
                    "civicgate_demo_csrf",
                    csrf_token,
                    httponly=True,
                    samesite="strict",
                    secure=False,  # Fixed loopback HTTP; no remote deployment claim.
                    path="/",
                )
            return response

        @app.get("/api/demo/capabilities", response_model=None)
        def demo_capabilities() -> dict[str, Any]:
            return active_executor.capabilities()

        @app.get("/api/demo/executions", response_model=None)
        def demo_jobs() -> dict[str, Any]:
            return {"jobs": active_executor.list_jobs(), "mode": "SYNTHETIC_E2E_ONLY"}

        @app.get("/api/demo/executions/{job_id}", response_model=None)
        def demo_job(job_id: str) -> dict[str, Any] | JSONResponse:
            from .demo_execution_v1 import DemoError

            try:
                return active_executor.get_job(checked_id(job_id))
            except DemoError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)

        @app.post("/api/demo/executions")
        async def execute_demonstration(request: Request) -> JSONResponse:
            from .demo_execution_v1 import DemoError

            raw_keys = [
                value
                for key, value in request.scope["headers"]
                if key.lower() == b"idempotency-key"
            ]
            key = request.headers.get("idempotency-key", "")
            if len(raw_keys) != 1 or len(key) != 36:
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            try:
                parsed_key = uuid.UUID(key)
            except (ValueError, AttributeError):
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            if len(raw_keys) != 1 or parsed_key.version != 4 or str(parsed_key) != key:
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            body = bytearray()
            try:
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 256:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
                value = strict_json(bytes(body))
            except TimeoutError:
                return JSONResponse({"error": "REQUEST_TIMEOUT"}, status_code=408)
            except (SafeEvidenceError, ValueError):
                return JSONResponse({"error": "INVALID_SCENARIO_REQUEST"}, status_code=400)
            if (
                not isinstance(value, dict)
                or set(value) != {"scenario"}
                or value["scenario"] not in ("permit", "deny", "review")
            ):
                return JSONResponse({"error": "INVALID_SCENARIO_REQUEST"}, status_code=400)
            try:
                job = active_executor.submit(value["scenario"], key)
            except DemoError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)
            return JSONResponse(job, status_code=202)

    if chat is not None:
        active_chat = chat

        @app.get("/chat", response_class=HTMLResponse)
        def chat_page(request: Request) -> HTMLResponse:
            response = render(
                request,
                "chat.html",
                active="chat",
                csrf_token=csrf_token,
                capabilities=active_chat.capabilities(),
            )
            if csrf_token is not None:
                response.set_cookie(
                    "civicgate_demo_csrf",
                    csrf_token,
                    httponly=True,
                    samesite="strict",
                    secure=False,
                    path="/",
                )
            return response

        @app.get("/api/chat/capabilities", response_model=None)
        def chat_capabilities() -> dict[str, Any]:
            return active_chat.capabilities()

        @app.get("/api/chat/turns", response_model=None)
        def chat_turns() -> dict[str, Any]:
            return {"turns": active_chat.list_turns(), "mode": "SYNTHETIC_GOVERNED_CHAT_ONLY"}

        @app.get("/api/chat/turns/{turn_id}", response_model=None)
        def chat_turn(turn_id: str) -> dict[str, Any] | JSONResponse:
            from .demo_execution_v1 import DemoError

            try:
                return active_chat.get_turn(checked_id(turn_id))
            except DemoError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)

        @app.post("/api/chat/turns")
        async def submit_chat_turn(request: Request) -> JSONResponse:
            from .demo_execution_v1 import DemoError

            raw_keys = [
                value
                for key, value in request.scope["headers"]
                if key.lower() == b"idempotency-key"
            ]
            key = request.headers.get("idempotency-key", "")
            try:
                parsed_key = uuid.UUID(key)
            except (ValueError, AttributeError):
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            if len(raw_keys) != 1 or parsed_key.version != 4 or str(parsed_key) != key:
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            body = bytearray()
            try:
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 16_384:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
                value = strict_json(bytes(body))
            except TimeoutError:
                return JSONResponse({"error": "REQUEST_TIMEOUT"}, status_code=408)
            except (SafeEvidenceError, ValueError):
                return JSONResponse({"error": "INVALID_CHAT_REQUEST"}, status_code=400)
            if (
                type(value) is not dict
                or set(value) != {"prompt"}
                or type(value["prompt"]) is not str
            ):
                return JSONResponse({"error": "INVALID_CHAT_REQUEST"}, status_code=400)
            try:
                turn = active_chat.submit_prompt(value["prompt"], key)
            except DemoError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)
            return JSONResponse(turn, status_code=202)

    if advisor is not None:
        active_advisor = advisor

        @app.get("/api/advisor/capabilities", response_model=None)
        def advisor_capabilities() -> dict[str, Any]:
            return active_advisor.capabilities()

        @app.get("/api/advisor/analyses/{analysis_id}", response_model=None)
        def advisor_analysis(analysis_id: str) -> dict[str, Any] | JSONResponse:
            from .evidence_advisor_v1 import AdvisorError

            try:
                return active_advisor.get_job(checked_id(analysis_id))
            except AdvisorError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)

        @app.post("/api/advisor/analyses")
        async def analyze_evidence(request: Request) -> JSONResponse:
            from .evidence_advisor_v1 import AdvisorError

            keys = [v for k, v in request.scope["headers"] if k.lower() == b"idempotency-key"]
            key = request.headers.get("idempotency-key", "")
            try:
                parsed = uuid.UUID(key)
            except (ValueError, AttributeError):
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            if len(keys) != 1 or parsed.version != 4 or str(parsed) != key:
                return JSONResponse({"error": "IDEMPOTENCY_KEY_REQUIRED"}, status_code=400)
            body = bytearray()
            try:
                async with asyncio.timeout(2):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 512:
                            return JSONResponse({"error": "REQUEST_LIMIT"}, status_code=413)
                value = strict_json(bytes(body))
            except TimeoutError:
                return JSONResponse({"error": "REQUEST_TIMEOUT"}, status_code=408)
            except (SafeEvidenceError, ValueError):
                return JSONResponse({"error": "INVALID_ANALYSIS_REQUEST"}, status_code=400)
            if (
                not isinstance(value, dict)
                or set(value) != {"run_id", "observation_id"}
                or not all(isinstance(v, str) and ID_PATTERN.fullmatch(v) for v in value.values())
            ):
                return JSONResponse({"error": "INVALID_ANALYSIS_REQUEST"}, status_code=400)
            try:
                job = active_advisor.submit(value["run_id"], value["observation_id"], key)
            except AdvisorError as exc:
                return JSONResponse({"error": exc.code}, status_code=exc.status_code)
            return JSONResponse(job, status_code=202)

    return app
