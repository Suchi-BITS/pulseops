from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.agent import router as agent_router
from app.api.incidents import router as incidents_router
from app.api.retrieval import router as retrieval_router
from app.api.routes import router
from app.api.workflow import router as workflow_router
from app.core.config import get_settings, validate_runtime_security
from app.core.errors import ErrorResponse, PulseOpsError, code_for_status
from app.core.limits import BodySizeLimitMiddleware
from app.core.logging import configure_logging, get_logger
from app.core.request_context import REQUEST_ID_HEADER, get_request_id, sanitize_request_id, set_request_id
from app.ui import mount_ui, security_headers_for

settings = get_settings()
validate_runtime_security(settings)  # fail closed: unsafe/missing security configuration stops the process here
configure_logging()
logger = get_logger("pulseops.http")

app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
    description="PulseOps incident intelligence foundation",
    # Interactive docs describe the whole API surface: development only.
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
)

# Every API error uses one envelope (P9.0): {"detail", "code", "request_id"}.
ERROR_RESPONSES = {status: {"model": ErrorResponse} for status in (400, 401, 403, 404, 409, 422)}


def error_response(request: Request, status_code: int, detail: str, code: str, headers: dict[str, str] | None = None,
                   **extra: object) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return JSONResponse(
        status_code=status_code, headers=headers,
        content={"detail": detail, "code": code, "request_id": request_id, **extra},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = getattr(exc, "code", None) or code_for_status(exc.status_code)
    return error_response(request, exc.status_code, detail, code, headers=getattr(exc, "headers", None))


@app.exception_handler(PulseOpsError)
async def domain_error_handler(request: Request, exc: PulseOpsError) -> JSONResponse:
    return error_response(request, exc.status_code, str(exc), exc.code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Location and message only: never echo the submitted input back.
    errors = [{"loc": list(error.get("loc", ())), "msg": str(error.get("msg", "")), "type": str(error.get("type", ""))}
              for error in exc.errors()]
    first = errors[0] if errors else {"loc": [], "msg": "invalid request"}
    where = ".".join(str(part) for part in first["loc"] if part != "body")
    detail = f"{where}: {first['msg']}" if where else str(first["msg"])
    return error_response(request, 422, f"Request validation failed ({detail})", "validation_error", errors=errors)


# Added before the request-context middleware so it sits INSIDE it: a 413 still gets the request id, headers and log line.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Request ID (sanitised or generated), structured access log, security headers, generic 500 body (no internals)."""
    request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
    set_request_id(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    error_class: str | None = None
    try:
        response = await call_next(request)
    except Exception as exc:  # never leak internals to the client
        error_class = type(exc).__name__
        response = JSONResponse(
            status_code=500, content={"detail": "Internal server error", "code": "internal_error", "request_id": request_id}
        )
    response.headers[REQUEST_ID_HEADER] = request_id
    for name, value in security_headers_for(request.url.path).items():
        response.headers.setdefault(name, value)
    principal = getattr(request.state, "principal", None)
    route = request.scope.get("route")
    logger.info(
        "request completed",
        extra={
            "operation": "http_request",
            "method": request.method,
            "path": request.url.path,
            "route": getattr(route, "path", None),
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "outcome": "error" if error_class or response.status_code >= 500 else "ok" if response.status_code < 400 else "rejected",
            "error_class": error_class,
            "principal_type": principal.principal_type.value if principal else None,
            "principal_id": principal.principal_id if principal else None,
            "tenant_id": principal.tenant_id if principal else None,
        },
    )
    return response


app.include_router(router, responses=ERROR_RESPONSES)
app.include_router(incidents_router, responses=ERROR_RESPONSES)
app.include_router(retrieval_router, responses=ERROR_RESPONSES)
app.include_router(agent_router, responses=ERROR_RESPONSES)
app.include_router(workflow_router, responses=ERROR_RESPONSES)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} is running"}


mount_ui(app)  # the built React UI at /ui, when a build exists (see frontend/)
