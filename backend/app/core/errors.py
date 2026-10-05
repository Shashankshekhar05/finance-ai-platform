"""Structured error envelope + exception handlers.

Single envelope for the whole API (see DEVELOPMENT_RULES.md §5):
    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}

Handlers never leak tracebacks, SQL, connection strings, or secrets.
Use `raise_api_error(status_code, code)` from services/routes so every
error — including automatic 401s from the auth scheme and 422 validation
failures — renders in this shape.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Public, stable error codes with safe human-readable messages.
ERROR_MESSAGES: dict[str, str] = {
    "invalid_credentials": "Invalid email or password.",
    "email_already_registered": "This email is already registered.",
    "authentication_required": "Authentication required.",
    "invalid_token": "Invalid authentication token.",
    "token_expired": "Authentication token has expired.",
    "inactive_user": "This account is no longer active.",
    "insufficient_permissions": "You do not have permission to perform this action.",
    "tenant_mismatch": "The requested company does not match your membership.",
    "not_found": "The requested resource was not found.",
    "method_not_allowed": "Method not allowed.",
    "unsupported_media_type": "Only PDF documents are accepted.",
    "file_too_large": "The uploaded file exceeds the maximum allowed size.",
    "too_many_pages": "The PDF exceeds the maximum page count.",
    "corrupt_document": "The uploaded file is not a readable PDF.",
    "invalid_state": "The requested action is not valid for the current state.",
    "unsupported_calculation": "The requested calculation is not supported.",
    "invalid_filter": "The requested filter is invalid for this dataset.",
    "invalid_group_by": "The requested grouping is invalid for this dataset.",
    "invalid_period": "The requested period is invalid.",
    "mixed_currency": "Records span multiple currencies; aggregation refused.",
    "llm_unavailable": "The AI provider is currently unavailable.",
    "llm_error": "The AI provider returned an error.",
    "validation_error": "Request validation failed.",
    "internal_error": "An unexpected error occurred.",
}


def error_body(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, object] | list[object] | None = None,
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else {},
            "request_id": request_id,
        }
    }


def raise_api_error(status_code: int, code: str) -> FastAPIHTTPException:
    """Raise a domain error that the handler below renders as an envelope."""
    return FastAPIHTTPException(status_code=status_code, detail=code)


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return str(rid) if rid else "unknown"


async def api_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Render HTTPException (ours + FastAPI's own 401/403/404) as envelope."""
    request_id = _request_id(request)
    code = (
        exc.detail
        if isinstance(exc.detail, str) and exc.detail in ERROR_MESSAGES
        else None
    )
    if code is None:
        # Never forward framework internals; map by status to a safe code.
        code = {
            status.HTTP_401_UNAUTHORIZED: "authentication_required",
            status.HTTP_403_FORBIDDEN: "insufficient_permissions",
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "file_too_large",
            status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
        }.get(exc.status_code, "internal_error")
        status_code = (
            exc.status_code
            if exc.status_code < 500
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    else:
        status_code = exc.status_code
    if status_code >= 500:
        logger.exception("server error request_id=%s code=%s", request_id, code)
    return JSONResponse(
        status_code=status_code,
        content=error_body(
            code=code,
            message=ERROR_MESSAGES[code],
            request_id=request_id,
        ),
    )


def _safe_validation_details(exc: RequestValidationError) -> list[object]:
    """Pydantic error ctx can hold raw exception objects (e.g. from
    AfterValidator); stringify anything that is not plain JSON first."""
    safe: list[object] = []
    for err in exc.errors():
        err = dict(err)
        ctx = err.get("ctx")
        if isinstance(ctx, dict):
            err["ctx"] = {
                key: value
                if isinstance(value, (str, int, float, bool, type(None), list, dict))
                else str(value)
                for key, value in ctx.items()
            }
        safe.append(err)
    return safe


async def api_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_body(
            code="validation_error",
            message=ERROR_MESSAGES["validation_error"],
            request_id=request_id,
            details=_safe_validation_details(exc),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception("unhandled error request_id=%s", request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body(
            code="internal_error",
            message=ERROR_MESSAGES["internal_error"],
            request_id=request_id,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Both classes: ours + framework 401s are the FastAPI subclass, while
    # Starlette internals (e.g. 404/405) raise the parent. Same envelope either way.
    app.add_exception_handler(FastAPIHTTPException, api_http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, api_http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, api_validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
