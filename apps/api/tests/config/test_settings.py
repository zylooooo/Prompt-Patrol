import pytest

from config import validate_session_cookie_hosts

# The __Host- cookie prefix forbids a Domain attribute, so the session cookie is
# pinned to whichever host answered the Entra callback. A host mismatch is not a
# runtime error anywhere - sign-in completes, the cookie lands on the wrong host,
# and every later request is 401 with nothing logged. These assert the config is
# rejected at startup instead.


@pytest.mark.parametrize(
    ("frontend", "redirect"),
    [
        # The documented dev setup: same host, different ports. Cookies ignore
        # ports, so this must be accepted.
        ("http://localhost:5173", "http://localhost:8000/api/auth/callback"),
        ("http://localhost:5173", "http://localhost:5173/api/auth/callback"),
        ("http://127.0.0.1:5173", "http://127.0.0.1:8000/api/auth/callback"),
        # Co-hosted deployment behind one origin, which is what nginx.conf does.
        ("https://promptpatrol.smu.edu.sg", "https://promptpatrol.smu.edu.sg/api/auth/callback"),
        # Trailing slash and case in the host must not matter.
        ("https://PromptPatrol.smu.edu.sg/", "https://promptpatrol.smu.edu.sg/api/auth/callback"),
    ],
)
def test_accepts_configurations_that_can_hold_the_cookie(frontend, redirect):
    validate_session_cookie_hosts(frontend, redirect)


@pytest.mark.parametrize(
    ("frontend", "redirect"),
    [
        # The trap this exists for: SPA and API on sibling subdomains.
        ("https://app.smu.edu.sg", "https://api.smu.edu.sg/api/auth/callback"),
        ("https://promptpatrol.smu.edu.sg", "https://promptpatrol.example.com/api/auth/callback"),
        # localhost and 127.0.0.1 are different hosts to a cookie jar.
        ("http://localhost:5173", "http://127.0.0.1:8000/api/auth/callback"),
    ],
)
def test_rejects_a_host_mismatch(frontend, redirect):
    with pytest.raises(ValueError, match="differ"):
        validate_session_cookie_hosts(frontend, redirect)


@pytest.mark.parametrize(
    ("frontend", "redirect"),
    [
        ("http://promptpatrol.smu.edu.sg", "http://promptpatrol.smu.edu.sg/api/auth/callback"),
        ("http://promptpatrol.smu.edu.sg", "https://promptpatrol.smu.edu.sg/api/auth/callback"),
        ("https://promptpatrol.smu.edu.sg", "http://promptpatrol.smu.edu.sg/api/auth/callback"),
        # A LAN address is not a trustworthy origin to a browser, so a Secure
        # cookie is dropped there just as it is on any other plain-http host.
        ("http://192.168.1.5:5173", "http://192.168.1.5:8000/api/auth/callback"),
    ],
)
def test_rejects_plain_http_on_a_non_local_host(frontend, redirect):
    with pytest.raises(ValueError, match="https"):
        validate_session_cookie_hosts(frontend, redirect)


@pytest.mark.parametrize(
    ("frontend", "redirect"),
    [
        ("localhost:5173", "http://localhost:8000/api/auth/callback"),
        ("http://localhost:5173", "/api/auth/callback"),
        ("", ""),
    ],
)
def test_rejects_urls_without_a_scheme_and_host(frontend, redirect):
    with pytest.raises(ValueError, match="absolute URLs"):
        validate_session_cookie_hosts(frontend, redirect)


def test_the_running_configuration_is_valid():
    # settings.py runs this at import time, so reaching this line already proves
    # it passed. Named so the reason a bad .env fails at collection is obvious.
    from config import ENTRA_REDIRECT_URI, FRONTEND_URL

    validate_session_cookie_hosts(FRONTEND_URL, ENTRA_REDIRECT_URI)
