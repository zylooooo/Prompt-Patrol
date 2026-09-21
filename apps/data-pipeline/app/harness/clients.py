"""API clients for the generation harness.

OpenAI, DeepSeek and local Ollama models speak the OpenAI chat
protocol, so one client class covers all three with different base
URLs. Transport failures retry with exponential backoff. A refusal is
not an error at this layer: it arrives as ordinary answer text and is
recorded like any other result.
"""

import os
import random
import time
from dataclasses import dataclass

import anthropic
import openai
from google import genai
from google.genai import errors as genai_errors

MAX_ATTEMPTS = 5
RETRYABLE_CODES = {429, 500, 502, 503, 504}


@dataclass
class GenerationResult:
    """One model call's output.

    params_honoured records only the decoding parameters the request
    actually carried, which differ per provider.
    """

    text: str
    model_version: str
    params_honoured: dict
    usage: dict


def _retry(call, is_retryable):
    """Run call, backing off exponentially with jitter on retryable errors."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return call()
        except Exception as exc:
            if attempt == MAX_ATTEMPTS - 1 or not is_retryable(exc):
                raise
            time.sleep(min(60.0, 2**attempt + random.random()))


class AnthropicClient:
    def __init__(self, model: str):
        self.model = model
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def generate(self, system: str, user: str, decoding: dict) -> GenerationResult:
        def is_retryable(exc):
            return isinstance(
                exc, (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError)
            )

        # the anthropic sdk takes no temperature, sampling is model-managed
        resp = _retry(
            lambda: self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=decoding["max_tokens"],
            ),
            is_retryable,
        )
        return GenerationResult(
            text="".join(b.text for b in resp.content if b.type == "text").strip(),
            model_version=resp.model,
            params_honoured={"max_tokens": decoding["max_tokens"]},
            usage={"prompt_tokens": resp.usage.input_tokens, "completion_tokens": resp.usage.output_tokens},
        )


class OpenAIChatClient:
    """OpenAI, and DeepSeek or local Ollama through their
    OpenAI-compatible endpoints."""

    def __init__(
        self,
        model: str,
        api_key_env: str | None = "OPENAI_API_KEY",
        base_url: str | None = None,
        send_temperature: bool = True,
        token_param: str = "max_tokens",
        extra_body: dict | None = None,
    ):
        self.model = model
        self._send_temperature = send_temperature
        self._token_param = token_param
        self._extra_body = extra_body
        # Ollama ignores the key but the sdk requires a non-empty one
        api_key = os.environ[api_key_env] if api_key_env else "ollama"
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, system: str, user: str, decoding: dict) -> GenerationResult:
        def is_retryable(exc):
            if isinstance(exc, openai.RateLimitError) and "insufficient_quota" in str(exc):
                return False  # billing, not load, retrying cannot help
            return isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError))

        kwargs = {self._token_param: decoding["max_tokens"]}
        if self._send_temperature:
            kwargs["temperature"] = decoding["temperature"]
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        resp = _retry(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **kwargs,
            ),
            is_retryable,
        )
        # reasoning models put their traces in a separate reasoning_content
        # field, so reading .content keeps only the final answer
        return GenerationResult(
            text=(resp.choices[0].message.content or "").strip(),
            model_version=resp.model,
            params_honoured=dict(kwargs),
            usage={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens},
        )


class GeminiClient:
    def __init__(self, model: str):
        self.model = model
        self._client = genai.Client()  # reads GEMINI_API_KEY

    def generate(self, system: str, user: str, decoding: dict) -> GenerationResult:
        def is_retryable(exc):
            # the google sdk distinguishes failures only by the http code
            # on APIError, the other sdks raise a class per condition
            return isinstance(exc, genai_errors.APIError) and exc.code in RETRYABLE_CODES

        resp = _retry(
            lambda: self._client.models.generate_content(
                model=self.model,
                contents=user,
                config={
                    "system_instruction": system,
                    "temperature": decoding["temperature"],
                    "max_output_tokens": decoding["max_tokens"],
                    # thinking shares max_output_tokens, minimal is the
                    # lowest setting on gemini 3.5, there is no off
                    "thinking_config": {"thinking_level": "minimal"},
                },
            ),
            is_retryable,
        )
        meta = resp.usage_metadata
        # a safety-blocked response reports None token counts
        return GenerationResult(
            text=(resp.text or "").strip(),
            model_version=getattr(resp, "model_version", None) or self.model,
            params_honoured={
                "temperature": decoding["temperature"], "max_output_tokens": decoding["max_tokens"],
                "thinking_level": "minimal",
            },
            # thoughts bill like answer tokens, count them the way the
            # other providers do
            usage={
                "prompt_tokens": meta.prompt_token_count or 0,
                "completion_tokens": (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
            },
        )


KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def build_clients(config: dict) -> dict:
    """Map generator name -> client, from the generators list in config."""
    # a blank value from a copied .env.example fails as clearly as a
    # missing one, and before any client construction
    missing = sorted({
        KEY_ENVS[g["provider"]] for g in config["generators"]
        if g["provider"] in KEY_ENVS and not os.environ.get(KEY_ENVS[g["provider"]])
    })
    if missing:
        raise SystemExit(f"missing API keys, fill these in .env: {missing}")
    built = {}
    for gen in config["generators"]:
        provider, model = gen["provider"], gen["model"]
        if provider == "anthropic":
            built[gen["name"]] = AnthropicClient(model)
        elif provider == "openai":
            # gpt-5 models fix their own sampling and use max_completion_tokens
            built[gen["name"]] = OpenAIChatClient(
                model, send_temperature=False, token_param="max_completion_tokens",
                extra_body=gen.get("extra_body"),
            )
        elif provider == "deepseek":
            built[gen["name"]] = OpenAIChatClient(
                model, api_key_env="DEEPSEEK_API_KEY", base_url="https://api.deepseek.com",
                extra_body=gen.get("extra_body"),
            )
        elif provider == "google":
            built[gen["name"]] = GeminiClient(model)
        elif provider == "ollama":
            built[gen["name"]] = OpenAIChatClient(
                model, api_key_env=None, base_url="http://localhost:11434/v1",
                extra_body=gen.get("extra_body"),
            )
        else:
            raise ValueError(f"unknown provider: {provider}")
    return built
