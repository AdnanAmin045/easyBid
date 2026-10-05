import json

import httpx
import pytest

from app.schemas import AppSettings
from app.services.llm import LLM, LLMError, model_chain, provider_of


def test_model_names_pick_the_provider():
    assert provider_of("gemini-3.5-flash") == "gemini"
    assert provider_of("claude-opus-5-5") == "anthropic"
    assert provider_of("groq/openai/gpt-oss-120b") == "groq"
    assert provider_of("cerebras/gpt-oss-120b") == "cerebras"
    assert model_chain("a", ["b", "a", " ", "c"]) == ["a", "b", "c"]


def test_a_chain_needs_one_usable_model():
    llm = LLM("", "gemini-key")
    s = AppSettings(selection_model="claude-opus-5-5", proposal_model="claude-opus-5-5")
    assert llm.problem(s) is None  # the Gemini fallbacks cover for the missing Anthropic key
    s = s.model_copy(update={"selection_fallback_models": [], "proposal_fallback_models": []})
    assert llm.problem(s) == "ANTHROPIC_API_KEY is not set"


async def test_out_of_quota_moves_to_the_next_model_and_rests_it():
    llm = LLM("", "gemini-key", groq_key="groq-key")
    calls = []

    async def fake_complete(*, model, **kwargs):
        calls.append(model)
        if model == "gemini-3.5-flash":
            raise LLMError("Gemini API error 429: quota", transient=True)
        return f"written by {model}"

    llm._complete = fake_complete
    chain = ["mistral/mistral-small-latest", "gemini-3.5-flash", "groq/llama-3.3-70b-versatile"]
    assert await llm._complete_chain(chain, system="", messages=[]) == "written by gemini-flash-lite-latest"
    # The model without a key is never called; the exhausted one is skipped while it rests.
    assert await llm._complete_chain(chain, system="", messages=[]) == "written by gemini-flash-lite-latest"
    assert calls == ["gemini-3.5-flash", "gemini-flash-lite-latest", "gemini-flash-lite-latest"]


async def test_a_chain_out_of_quota_is_transient_and_other_errors_are_not():
    llm = LLM("", "gemini-key")

    async def busy(*, model, **kwargs):
        raise LLMError("503", transient=True)

    llm._complete = busy
    with pytest.raises(LLMError) as e:
        await llm._complete_chain(["gemini-3.5-flash"], system="", messages=[])
    assert e.value.transient

    async def declined(*, model, **kwargs):
        raise LLMError("The model declined this request")

    llm = LLM("", "gemini-key")
    llm._complete = declined
    with pytest.raises(LLMError) as e:
        await llm._complete_chain(["gemini-3.5-flash", "gemini-flash-lite-latest"], system="", messages=[])
    assert not e.value.transient


async def test_openai_style_providers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        if seen["body"]["model"] == "busy-model":
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"apply": true}'}, "finish_reason": "stop"}]})

    llm = LLM("", "", cerebras_key="c-key")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = await llm._complete(
        model="cerebras/gpt-oss-120b", system="Decide.", messages=[{"role": "user", "content": "job"}],
        effort="low", max_tokens=4000, schema={"type": "object"},
    )
    assert text == '{"apply": true}'
    assert seen["url"] == "https://api.cerebras.ai/v1/chat/completions" and seen["auth"] == "Bearer c-key"
    assert seen["body"]["model"] == "gpt-oss-120b" and seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0]["role"] == "system"

    with pytest.raises(LLMError) as e:
        await llm._complete(model="cerebras/busy-model", system="", messages=[], effort="low", max_tokens=10)
    assert e.value.transient
