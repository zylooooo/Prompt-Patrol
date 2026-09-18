from types import SimpleNamespace

import pytest

from harness import clients
from harness.clients import _retry


class Boom(Exception):
    pass


def _no_sleep(monkeypatch):
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)


def test_retries_then_succeeds(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Boom()
        return "ok"

    assert _retry(flaky, lambda exc: isinstance(exc, Boom)) == "ok"
    assert calls["n"] == 3


def test_non_retryable_raises_immediately(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise Boom()

    with pytest.raises(Boom):
        _retry(broken, lambda exc: False)
    assert calls["n"] == 1


def test_gives_up_after_max_attempts(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise Boom()

    with pytest.raises(Boom):
        _retry(always_fails, lambda exc: True)
    assert calls["n"] == clients.MAX_ATTEMPTS


def test_extra_body_is_sent_and_recorded():
    client = clients.OpenAIChatClient("qwen3:8b", api_key_env=None, extra_body={"reasoning_effort": "none"})
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" hi "))],
            model="qwen3:8b",
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        )

    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = client.generate("system", "user", {"temperature": 0.8, "max_tokens": 400})
    assert captured["extra_body"] == {"reasoning_effort": "none"}
    assert result.params_honoured["extra_body"] == {"reasoning_effort": "none"}
    assert result.text == "hi"