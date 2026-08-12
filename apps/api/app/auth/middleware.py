from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from db import async_session
from services.sessions import authenticate_session

SESSION_COOKIE_NAME = "__Host-session"


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Resolves the session cookie to a user, if present and valid.

    A missing cookie isn't treated as an error, request.state.user just
    stays None and it's up to the route (via require_role) to decide if
    that's ok. A present-but-invalid cookie (expired, revoked, unknown) is
    different though, that shouldn't happen for a legitimate client so we
    fail fast with a 401 instead of quietly falling through as anonymous.
    """

    async def dispatch(self, request, call_next):
        request.state.user = None
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)
        if raw_token:
            async with async_session() as db:
                user = await authenticate_session(db, raw_token)
            if user is None:
                # Exempt /api/auth/* so a dead cookie can't lock a user out
                # of the flow that would replace it.
                if not request.url.path.startswith("/api/auth/"):
                    return Response(status_code=401, content="Session invalid or expired")
            else:
                request.state.user = user
        return await call_next(request)
