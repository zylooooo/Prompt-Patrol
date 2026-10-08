import logging
import uuid
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from config import FRONTEND_URL, request_id_ctx_var
from exceptions import error_response

logger = logging.getLogger(__name__)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_OWN_ORIGIN = "{0.scheme}://{0.netloc}".format(urlsplit(FRONTEND_URL))


class CrossOriginProtectionMiddleware(BaseHTTPMiddleware):
    """Refuses any state-changing request that did not come from our own origin.

    `same-site` is refused too: SameSite counts every *.smu.edu.sg host as the
    same site, and a takeover of any one of them is the threat this exists for.
    A request carrying neither header is refused; a non-browser client opts in
    with `Sec-Fetch-Site: same-origin`, which is harmless because it cannot
    carry a victim's cookie."""

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        if fetch_site is not None:
            allowed = fetch_site in ("same-origin", "none")
        else:
            # Pre-2023 browsers send no Sec-Fetch-Site, but always send Origin on a POST.
            allowed = origin == _OWN_ORIGIN
        if allowed:
            return await call_next(request)
        logger.warning(
            "Cross-site %s %s refused (Sec-Fetch-Site=%r, Origin=%r).",
            request.method,
            request.url.path,
            fetch_site,
            origin,
        )
        return error_response(403, "forbidden", "Cross-site request refused.")


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
