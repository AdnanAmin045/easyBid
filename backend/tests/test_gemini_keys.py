from datetime import datetime, timedelta, timezone

import pytest
from google.genai import errors as genai_errors

from app.config import Env
from app.services.llm import GEMINI_LADDER, LLM, LLMError, gemini_error, until_quota_reset


def api_error(code: int, message: str, details: list | None = None) -> LLMError:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    error = genai_errors.ClientError(code, body) if code < 500 else genai_errors.ServerError(code, body)
    return gemini_error(error)


def test_each_key_climbs_the_whole_ladder_before_the_next_key():
    llm = LLM("", ["k1", "k2", " ", "k1", "k3"])
    assert len(llm._gemini) == 3  # blanks and repeats dropped
    chain = ["claude-opus-5-5", "gemini-flash-latest", "groq/llama-3.3-70b-versatile", "gemini-pro-latest"]
    # The Gemini models chosen in Settings first, then the rest of the ladder.
    gemini = ["gemini-flash-latest", "gemini-pro-latest", "gemini-flash-lite-latest", "gemini-3.5-flash"]
    assert llm.slots(chain) == [
        ("claude-opus-5-5", 0),
        *[(m, key) for key in range(3) for m in gemini],
        ("groq/llama-3.3-70b-versatile", 0),
    ]
    assert GEMINI_LADDER[-1] == "gemini-pro-latest"  # the best model is last


async def test_quota_runs_through_every_model_then_moves_to_the_next_key():
    llm = LLM("", ["k1", "k2", "k3"])
    calls = []
    out_of_quota = {(m, 0) for m in GEMINI_LADDER} | {("gemini-flash-lite-latest", 1)}

    async def fake_complete(*, model, key, **kwargs):
        calls.append((model, key))
        if (model, key) in out_of_quota:
            raise LLMError("Gemini API error 429", transient=True, rest=timedelta(minutes=1))
        return f"{model} on key {key + 1}"

    llm._complete = fake_complete
    chain = ["gemini-flash-lite-latest"]
    assert await llm._complete_chain(chain, system="", messages=[]) == "gemini-3.5-flash on key 2"
    assert calls == [*((m, 0) for m in GEMINI_LADDER), ("gemini-flash-lite-latest", 1), ("gemini-3.5-flash", 1)]

    # Resting slots are skipped on the next call: the one that answered is asked straight away.
    calls.clear()
    assert await llm._complete_chain(chain, system="", messages=[]) == "gemini-3.5-flash on key 2"
    assert calls == [("gemini-3.5-flash", 1)]

    # Once the rests are over, key 1 is first in line again.
    llm._resting = {name: datetime.now(timezone.utc) - timedelta(seconds=1) for name in llm._resting}
    out_of_quota.clear()
    assert await llm._complete_chain(chain, system="", messages=[]) == "gemini-flash-lite-latest on key 1"


async def test_every_key_out_of_quota_waits_instead_of_failing():
    llm = LLM("", ["k1", "k2"])
    calls = []

    async def busy(*, model, key, **kwargs):
        calls.append((model, key))
        raise LLMError("Gemini API error 429", transient=True)

    llm._complete = busy
    with pytest.raises(LLMError) as e:
        await llm._complete_chain(["gemini-flash-lite-latest"], system="", messages=[])
    assert e.value.transient  # the project waits for the AI instead of being marked as an error
    assert len(calls) == 2 * len(GEMINI_LADDER)

    # Everything rests now, so nothing is asked until a rest ends; single requests share the same rotation.
    with pytest.raises(LLMError) as e:
        await llm.complete(model="gemini-flash-latest", system="", user="")
    assert e.value.transient and len(calls) == 2 * len(GEMINI_LADDER)


async def test_a_rejected_key_and_an_unknown_model_are_skipped():
    llm = LLM("", ["bad", "good"])
    calls = []

    async def fake_complete(*, model, key, **kwargs):
        calls.append((model, key))
        if key == 0:
            raise api_error(400, "API key not valid. Please pass a valid API key.")
        if model == "gemini-3.5-flash":
            raise api_error(404, "models/gemini-3.5-flash is not found")
        return f"{model} on key {key + 1}"

    llm._complete = fake_complete
    chain = ["gemini-3.5-flash"]
    assert await llm._complete_chain(chain, system="", messages=[]) == "gemini-flash-lite-latest on key 2"
    assert calls == [("gemini-3.5-flash", 0), ("gemini-3.5-flash", 1), ("gemini-flash-lite-latest", 1)]

    # The bad key and the unknown model are not asked again while they rest.
    calls.clear()
    assert await llm._complete_chain(chain, system="", messages=[]) == "gemini-flash-lite-latest on key 2"
    assert calls == [("gemini-flash-lite-latest", 1)]


async def test_a_refusal_still_stops_the_chain():
    llm = LLM("", ["k1", "k2"])

    async def declined(*, model, key, **kwargs):
        raise api_error(400, "Invalid JSON schema")

    llm._complete = declined
    with pytest.raises(LLMError) as e:
        await llm._complete_chain(["gemini-flash-latest"], system="", messages=[])
    assert not e.value.transient


def test_gemini_errors_say_how_long_to_rest():
    retry = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}
    per_minute = api_error(429, "Quota exceeded", [retry])
    assert per_minute.transient and per_minute.rest == timedelta(seconds=38)

    daily = {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}
    per_day = api_error(429, "Quota exceeded", [daily, retry])
    assert per_day.transient and timedelta(0) < per_day.rest <= timedelta(hours=25)
    assert api_error(429, "Resource exhausted").rest is None  # the chain's default rest applies

    overloaded = api_error(503, "The model is overloaded")
    assert overloaded.transient and overloaded.skip is None
    assert api_error(403, "Permission denied").skip == "key"
    bad_request = api_error(400, "Invalid JSON schema")
    assert not bad_request.transient and bad_request.skip is None


def test_daily_quota_resets_at_midnight_pacific():
    # 12:00 UTC in July is 05:00 PDT; midnight PDT is 07:00 UTC the next day.
    assert until_quota_reset(datetime(2026, 7, 1, 12, tzinfo=timezone.utc)) == timedelta(hours=19)
    # 12:00 UTC in December is 04:00 PST; midnight PST is 08:00 UTC the next day.
    assert until_quota_reset(datetime(2026, 12, 1, 12, tzinfo=timezone.utc)) == timedelta(hours=20)


async def test_a_gemini_request_uses_the_key_it_was_given():
    llm = LLM("", ["k1", "k2"])
    used = []

    class Response:
        text = '{"apply": true, "reason": "fits"}'

    class Models:
        def __init__(self, name):
            self.name = name

        async def generate_content(self, **kwargs):
            used.append(self.name)
            return Response()

    class Aio:
        def __init__(self, name):
            self.models = Models(name)

    class Client:
        def __init__(self, name):
            self.aio = Aio(name)

    llm._gemini = [Client("k1"), Client("k2")]
    messages = [{"role": "user", "content": "job"}]
    text = await llm._complete(model="gemini-flash-latest", key=1, system="", messages=messages, effort="low", max_tokens=10)
    assert text == Response.text and used == ["k2"]


def test_env_collects_every_gemini_key(monkeypatch):
    for name, value in {"GEMINI_API_KEY": "a", "GEMINI_API_KEY_2": "b", "GEMINI_API_KEY_3": "a",
                        "GEMINI_API_KEY_4": " ", "GEMINI_API_KEY_5": "c"}.items():
        monkeypatch.setenv(name, value)
    assert Env(_env_file=None).gemini_api_keys == ["a", "b", "c"]
