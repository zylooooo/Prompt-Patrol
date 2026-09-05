import pytest

from config import SESSION_SECRET_MIN_LENGTH, validate_session_cookie_hosts, validate_session_secret


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
    from config import AUTH0_REDIRECT_URI, FRONTEND_URL

    validate_session_cookie_hosts(FRONTEND_URL, AUTH0_REDIRECT_URI)


# SESSION_SECRET signs the 'ppauthflow' cookie carrying OAuth state - the
# anti-CSRF token for the whole sign-in flow. It was previously only checked for
# emptiness, so the literal CI value could reach a real deployment unchallenged.

_STRONG_SECRET = "x" * SESSION_SECRET_MIN_LENGTH


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_accepts_a_long_non_placeholder_secret(environment):
    validate_session_secret(_STRONG_SECRET, environment)


@pytest.mark.parametrize(
    "secret",
    [
        # The exact value in .github/workflows/ci.yml, and the one most likely
        # to be copied into a real .env.
        "ci-dummy-session-secret",
        "changeme",
        "  SECRET  ",
    ],
)
@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_rejects_a_known_placeholder(secret, environment):
    with pytest.raises(ValueError, match="placeholder"):
        validate_session_secret(secret, environment)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_rejects_a_secret_below_the_minimum_length(environment):
    with pytest.raises(ValueError, match="characters"):
        validate_session_secret("x" * (SESSION_SECRET_MIN_LENGTH - 1), environment)


@pytest.mark.parametrize("secret", ["ci-dummy-session-secret", "short"])
def test_dev_is_exempt(secret):
    # Local dev and CI both run with throwaway values on purpose; enforcing here
    # would only teach people to weaken the check.
    validate_session_secret(secret, "dev")
