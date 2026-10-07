import logging
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from config import request_id_ctx_var
from exceptions import error_response

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Tags every log emitted while handling a request with a request id."""

    async def dispatch(self, request: Request, call_next):
        token = request_id_ctx_var.set(str(uuid.uuid4()))
        try:
            return await call_next(request)
        except Exception:
            # Caught here, not in an exception handler: Starlette runs the
            # catch-all handler outside this middleware, after the request id
            # is reset, and a 500 is the response that most needs one.
            logger.exception("Unhandled error.")
            return error_response(
                500, "internal_error", "Something went wrong. Quote the request id if you report this."
            )
        finally:
            request_id_ctx_var.reset(token)
