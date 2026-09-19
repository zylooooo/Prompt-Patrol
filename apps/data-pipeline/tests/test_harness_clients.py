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


def test_gemini_safety_block_yields_empty_answer_and_zero_usage():
    client = clients.GeminiClient.__new__(clients.GeminiClient)
    client.model = "gemini-3.5-flash"
    resp = SimpleNamespace(
        text=None,
        model_version=None,
        usage_metadata=SimpleNamespace(
            prompt_token_count=None, candidates_token_count=None, thoughts_token_count=None,
        ),
    )
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: resp))
    result = client.generate("system", "user", {"temperature": 0.8, "max_tokens": 400})
    assert result.text == ""
    assert result.usage == {"prompt_tokens": 0, "completion_tokens": 0}


def test_build_clients_wires_each_provider(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "test-key")
    config = {"generators": [
        {"name": "claude", "provider": "anthropic", "model": "claude-sonnet-5"},
        {"name": "gpt", "provider": "openai", "model": "gpt-5.5-2026-04-23",
         "extra_body": {"service_tier": "flex"}},
        {"name": "gem", "provider": "google", "model": "gemini-3.5-flash"},
        {"name": "ds", "provider": "deepseek", "model": "deepseek-v4-pro",
         "extra_body": {"thinking": {"type": "disabled"}}},
        {"name": "local", "provider": "ollama", "model": "qwen3:8b",
         "extra_body": {"reasoning_effort": "none"}},
    ]}
    built = clients.build_clients(config)
    assert isinstance(built["claude"], clients.AnthropicClient)
    assert isinstance(built["gem"], clients.GeminiClient)
    gpt, ds, local = built["gpt"], built["ds"], built["local"]
    assert gpt._token_param == "max_completion_tokens"
    assert not gpt._send_temperature
    assert gpt._extra_body == {"service_tier": "flex"}
    assert str(ds._client.base_url).startswith("https://api.deepseek.com")
    assert ds._extra_body == {"thinking": {"type": "disabled"}}
    assert str(local._client.base_url).startswith("http://localhost:11434/v1")
    assert local._extra_body == {"reasoning_effort": "none"}


def test_build_clients_rejects_missing_or_blank_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    config = {"generators": [
        {"name": "gpt", "provider": "openai", "model": "m"},
        {"name": "claude", "provider": "anthropic", "model": "m"},
    ]}
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY.*OPENAI_API_KEY"):
        clients.build_clients(config)


def test_anthropic_keeps_only_text_blocks():
    client = clients.AnthropicClient.__new__(clients.AnthropicClient)
    client.model = "claude-sonnet-5"
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="part one"),
            SimpleNamespace(type="tool_use", text="ignored"),
            SimpleNamespace(type="text", text=" part two"),
        ],
        model="claude-sonnet-5",
        usage=SimpleNamespace(input_tokens=4, output_tokens=6),
    )
    client._client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: resp))
    result = client.generate("system", "user", {"max_tokens": 400, "temperature": 0.8})
    assert result.text == "part one part two"
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 6}


def test_gemini_counts_thinking_tokens_in_completion():
    client = clients.GeminiClient.__new__(clients.GeminiClient)
    client.model = "gemini-3.5-flash"
    resp = SimpleNamespace(
        text="ok",
        model_version="gemini-3.5-flash-001",
        usage_metadata=SimpleNamespace(
            prompt_token_count=5, candidates_token_count=7, thoughts_token_count=11,
        ),
    )
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: resp))
    result = client.generate("system", "user", {"temperature": 0.8, "max_tokens": 400})
    assert result.usage == {"prompt_tokens": 5, "completion_tokens": 18}
    