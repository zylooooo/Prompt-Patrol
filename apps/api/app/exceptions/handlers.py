from collections.abc import Mapping
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import request_id_ctx_var

# The code for an HTTPException raised with a plain string detail. A route
# that needs a more specific code raises detail={"code", "message"} instead.
_DEFAULT_CODES = {
    400: "invalid_request",
    403: "forbidden",
    404: "not_found",
    405: "invalid_request",
    409: "conflict",
    413: "payload_too_large",
    502: "upstream_idp_error",
}


def error_response(status_code: int, code: str, message: str, headers: Mapping[str, str] | None = None) -> JSONResponse:
    """The one error body this API returns - the contract's `Error` schema."""
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message, "request_id": request_id_ctx_var.get()},
        headers=headers,
    )


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # Starlette types `detail` as str, but routes pass {"code", "message"} too.
    detail = cast(object, exc.detail)
    if isinstance(detail, dict):
        code, message = detail["code"], detail["message"]
    else:
        code, message = _DEFAULT_CODES.get(exc.status_code, "internal_error"), str(detail)
    return error_response(exc.status_code, code, message, exc.headers)


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    message = "; ".join(
        f"{'.'.join(str(part) for part in e['loc'][1:]) or e['loc'][0]}: {e['msg']}" for e in exc.errors()
    )
    return error_response(400, "invalid_request", message)


def register_exception_handlers(app: FastAPI) -> None:
    """400 for every validation failure, and `Error` for every HTTPException. 
    Unhandled exceptions are caught in RequestIdMiddleware so the 500 
    still carries its request id."""
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
