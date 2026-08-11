import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from config import request_id_ctx_var


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Tags every log emitted while handling a request with a request id."""

    async def dispatch(self, request: Request, call_next):
        token = request_id_ctx_var.set(str(uuid.uuid4()))
        try:
            return await call_next(request)
        finally:
            request_id_ctx_var.reset(token)
