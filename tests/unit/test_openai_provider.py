"""Offline SDK-backed tests of the approved provider boundary."""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from email.utils import format_datetime
from threading import Barrier
from typing import Any

import httpx2
import pytest
from openai import APIStatusError, OpenAI
from openai.types.responses import (
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)
from openai.types.responses.response_reasoning_item import Content, Summary

from privilab.adapters.models import openai as adapter
from privilab.adapters.models.openai import (
    OpenAIGeneration,
    OpenAIProvider,
    OpenAIProviderConfig,
    OpenAIProviderError,
    OpenAIUsage,
)
from privilab.application.model_provider import (
    MalformedModelOutputError,
    ModelRequest,
    ModelSourceChunk,
)
from privilab.domain import CitationReference, ResearchResult


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def request() -> ModelRequest:
    return ModelRequest(
        "Summarize the supplied synthetic source.",
        (ModelSourceChunk("source-a", "chunk-a", "Synthetic source text."),),
    )


def response_body(*, tokens: int = 10) -> dict[str, Any]:
    return {
        "id": "synthetic-response",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-terra",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {"id": "reasoning", "type": "reasoning", "summary": []},
            {
                "id": "answer",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "text": json.dumps(
                            {
                                "answer_text": "Synthetic answer.",
                                "citations": [
                                    {"source_id": "source-a", "chunk_id": "chunk-a"}
                                ],
                            }
                        ),
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": tokens,
            "output_tokens": 6,
            "total_tokens": tokens + 6,
            "input_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 1},
        },
    }


class ScriptedAPI:
    def __init__(self, events: list[httpx2.Response | Exception]) -> None:
        self.events = iter(events)
        self.requests: list[httpx2.Request] = []
        self.clients: list[OpenAI] = []
        self.delays: list[float] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        return event

    def client(self, config: OpenAIProviderConfig) -> OpenAI:
        client = OpenAI(
            api_key="synthetic-unit-key",
            base_url="https://api.openai.com/v1",
            max_retries=0,
            timeout=config.timeout_seconds,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handle)),
        )
        self.clients.append(client)
        return client

    def provider(self, config: OpenAIProviderConfig | None = None) -> OpenAIProvider:
        return OpenAIProvider(
            config or OpenAIProviderConfig(),
            _client_factory=self.client,
            _sleep=self.delays.append,
            _clock=lambda: 1_800_000_000.0,
        )


def success(*, tokens: int = 10) -> httpx2.Response:
    return httpx2.Response(200, json=response_body(tokens=tokens))


def test_request_flags_schema_projection_and_mapping() -> None:
    api = ScriptedAPI([success()])
    generation = api.provider().generate_with_usage(request())
    sent = api.requests[0]
    value = json.loads(sent.content)
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.openai.com/v1/responses"
    assert set(value) == {
        "model",
        "store",
        "stream",
        "background",
        "tools",
        "tool_choice",
        "truncation",
        "instructions",
        "input",
        "text",
    }
    assert value["model"] == "gpt-5.6-terra"
    assert value["store"] is value["stream"] is value["background"] is False
    assert value["tools"] == [] and value["tool_choice"] == "none"
    assert value["truncation"] == "disabled"
    assert json.loads(value["input"]) == {
        "task_text": request().task_text,
        "source_chunks": [
            {
                "source_id": "source-a",
                "chunk_id": "chunk-a",
                "text": "Synthetic source text.",
            }
        ],
    }
    schema = value["text"]["format"]
    assert schema["type"] == "json_schema" and schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == ["answer_text", "citations"]
    citation = schema["schema"]["properties"]["citations"]["items"]
    assert citation["required"] == ["source_id", "chunk_id"]
    assert citation["additionalProperties"] is False
    assert generation.result == ResearchResult(
        "Synthetic answer.", (CitationReference("source-a", "chunk-a"),)
    )
    assert generation.usage == OpenAIUsage(10, 6, 16, 3, 2, 1)
    assert api.clients[0].is_closed()
    assert api.clients[0].timeout == 30
    assert sent.extensions["timeout"] == {
        "connect": 30,
        "read": 30,
        "write": 30,
        "pool": 30,
    }
    assert api.clients[0].max_retries == 0


def test_generate_delegates_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = OpenAIGeneration(ResearchResult("Exact result."), OpenAIUsage(2))
    calls: list[ModelRequest] = []

    def generate(self: OpenAIProvider, value: ModelRequest) -> OpenAIGeneration:
        calls.append(value)
        return expected

    monkeypatch.setattr(OpenAIProvider, "generate_with_usage", generate)
    supplied = request()
    assert OpenAIProvider().generate(supplied) is expected.result
    assert calls == [supplied]


@pytest.mark.parametrize("item", ["reasoning", "message", "text"])
@pytest.mark.parametrize("tag", ["expected", "missing", "unknown", "tool", "null"])
def test_response_wire_discriminators(item: str, tag: str) -> None:
    body = response_body()
    value = (
        body["output"][0]
        if item == "reasoning"
        else body["output"][1]
        if item == "message"
        else body["output"][1]["content"][0]
    )
    if tag == "missing":
        del value["type"]
    elif tag != "expected":
        value["type"] = {
            "unknown": "synthetic_unknown_type",
            "tool": "function_call",
            "null": None,
        }[tag]
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    if tag == "expected":
        assert api.provider().generate(request()) == ResearchResult(
            "Synthetic answer.", (CitationReference("source-a", "chunk-a"),)
        )
    else:
        with pytest.raises(MalformedModelOutputError) as caught:
            api.provider().generate(request())
        assert caught.value.__cause__ is caught.value.__context__ is None
    assert len(api.requests) == 1 and api.delays == []
    assert api.clients[0].is_closed()


@pytest.mark.parametrize("tag", ["missing", "synthetic_unknown_type"])
def test_sdk_class_does_not_validate_wire_discriminator(tag: str) -> None:
    body = response_body()
    content = body["output"][1]["content"][0]
    if tag == "missing":
        del content["type"]
    else:
        content["type"] = tag
    api = ScriptedAPI([httpx2.Response(200, json=body) for _ in range(2)])
    config = OpenAIProviderConfig()
    with api.client(config) as client:
        parsed = client.responses.create(**adapter._parameters(request(), config))
    message = parsed.output[1]
    assert isinstance(message, ResponseOutputMessage)
    assert isinstance(message.content[0], ResponseOutputText)
    assert content.get("type") != "output_text"
    with pytest.raises(MalformedModelOutputError):
        api.provider().generate(request())
    assert len(api.requests) == 2 and api.delays == []
    assert all(client.is_closed() for client in api.clients)


@pytest.mark.parametrize("field", ["summary", "content"])
@pytest.mark.parametrize(
    "tag", ["expected", "missing", "null", "unknown", "incompatible"]
)
def test_nested_reasoning_wire_discriminators(field: str, tag: str) -> None:
    body = response_body()
    expected = "summary_text" if field == "summary" else "reasoning_text"
    entry: dict[str, Any] = {"type": expected, "text": "Synthetic reasoning."}
    if tag == "missing":
        del entry["type"]
    elif tag != "expected":
        entry["type"] = {
            "null": None,
            "unknown": "synthetic_unknown_type",
            "incompatible": "output_text",
        }[tag]
    body["output"][0][field] = [
        {"type": expected, "text": "Valid preceding reasoning entry."},
        entry,
    ]
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    if tag == "expected":
        assert api.provider().generate(request()).answer_text == "Synthetic answer."
    else:
        with pytest.raises(MalformedModelOutputError) as caught:
            api.provider().generate(request())
        assert caught.value.__cause__ is caught.value.__context__ is None
        assert "Synthetic reasoning." not in str(caught.value)
    assert len(api.requests) == 1 and api.delays == []
    assert api.clients[0].is_closed()


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("summary", "absent", False),
        ("summary", None, False),
        ("summary", {}, False),
        ("summary", "not-a-list", False),
        ("summary", [None], False),
        ("summary", ["not-a-dict"], False),
        ("summary", [], True),
        ("content", "absent", True),
        ("content", None, True),
        ("content", {}, False),
        ("content", "not-a-list", False),
        ("content", [None], False),
        ("content", ["not-a-dict"], False),
        ("content", [], True),
    ],
)
def test_nested_reasoning_container_shapes(field: str, value: Any, valid: bool) -> None:
    body = response_body()
    if value == "absent":
        body["output"][0].pop(field, None)
    else:
        body["output"][0][field] = value
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    if valid:
        assert api.provider().generate(request()).answer_text == "Synthetic answer."
    else:
        with pytest.raises(MalformedModelOutputError):
            api.provider().generate(request())
    assert len(api.requests) == 1 and api.delays == []
    assert api.clients[0].is_closed()


@pytest.mark.parametrize("field", ["summary", "content"])
@pytest.mark.parametrize("tag", ["missing", "synthetic_unknown_type"])
def test_nested_reasoning_is_validated_before_sdk_parse(
    field: str, tag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = response_body()
    entry = {"text": "Synthetic reasoning."}
    if tag != "missing":
        entry["type"] = tag
    body["output"][0][field] = [entry]
    api = ScriptedAPI([httpx2.Response(200, json=body) for _ in range(2)])
    config = OpenAIProviderConfig()
    with api.client(config) as client:
        raw = client.responses.with_raw_response.create(
            **adapter._parameters(request(), config)
        )
    parsed = raw.parse()
    reasoning = parsed.output[0]
    assert isinstance(reasoning, ResponseReasoningItem)
    if field == "summary":
        assert isinstance(reasoning.summary[0], Summary)
    else:
        assert reasoning.content is not None
        assert isinstance(reasoning.content[0], Content)

    parse_calls: list[bool] = []
    original_parse = type(raw).parse

    def observe_parse(self: Any, *args: Any, **kwargs: Any) -> Any:
        parse_calls.append(True)
        return original_parse(self, *args, **kwargs)

    monkeypatch.setattr(type(raw), "parse", observe_parse)
    with pytest.raises(MalformedModelOutputError):
        api.provider().generate(request())
    assert parse_calls == []
    assert len(api.requests) == 2 and api.delays == []
    assert all(client.is_closed() for client in api.clients)


@pytest.mark.parametrize(
    "change",
    [
        "refusal",
        "incomplete",
        "failed",
        "no-answer",
        "two-answers",
        "tool",
        "invalid-json",
        "duplicate-json-field",
        "wrong-schema",
        "invalid-citation",
        "incomplete-message",
        "wrong-role",
        "multiple-content",
        "error",
        "incomplete-details",
        "incomplete-reasoning",
        "blank-answer",
        "bad-output",
    ],
)
def test_incompatible_output_never_retries(change: str) -> None:
    body = response_body()
    message = body["output"][1]
    content = message["content"][0]
    if change == "refusal":
        message["content"] = [{"type": "refusal", "refusal": "Synthetic refusal."}]
    elif change in ("incomplete", "failed"):
        body["status"] = change
    elif change == "no-answer":
        body["output"] = body["output"][:1]
    elif change == "two-answers":
        body["output"].append(message.copy())
    elif change == "tool":
        body["output"].append(
            {
                "type": "function_call",
                "call_id": "a",
                "name": "forbidden",
                "arguments": "{}",
                "id": "tool",
            }
        )
    elif change == "invalid-json":
        content["text"] = "synthetic unparseable output"
    elif change == "duplicate-json-field":
        content["text"] = '{"answer_text":"one","answer_text":"two","citations":[]}'
    elif change == "wrong-schema":
        content["text"] = '{"unapproved":"field"}'
    elif change == "invalid-citation":
        content["text"] = (
            '{"answer_text":"answer","citations":[{"source_id":2,"chunk_id":"x"}]}'
        )
    elif change == "incomplete-message":
        message["status"] = "incomplete"
    elif change == "wrong-role":
        message["role"] = "user"
    elif change == "multiple-content":
        message["content"].append(content.copy())
    elif change == "error":
        body["error"] = {"code": "server_error", "message": "Untrusted error"}
    elif change == "incomplete-details":
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    elif change == "incomplete-reasoning":
        body["output"][0]["status"] = "incomplete"
    elif change == "blank-answer":
        content["text"] = '{"answer_text":" ","citations":[]}'
    elif change == "bad-output":
        body["output"] = "not a list"
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    with pytest.raises(MalformedModelOutputError) as caught:
        api.provider().generate(request())
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert len(api.requests) == 1 and api.delays == []
    assert api.clients[0].is_closed()


@pytest.mark.parametrize(
    ("status", "code", "kind", "retry"),
    [
        (408, None, None, True),
        (409, None, None, True),
        (429, "rate_limit_exceeded", "rate_limit_error", True),
        (429, "slow_down", "rate_limit_error", True),
        (429, None, "rate_limit_error", True),
        (500, None, None, True),
        (502, None, None, True),
        (503, "server_is_overloaded", "service_unavailable_error", True),
        (504, None, None, True),
        (400, None, None, False),
        (401, None, None, False),
        (403, None, None, False),
        (404, None, None, False),
        (422, None, None, False),
        (501, None, None, False),
        (429, None, None, False),
        (429, "unknown", "rate_limit_error", False),
        (429, "insufficient_quota", "insufficient_quota", False),
        (429, "credit_balance_exhausted", "insufficient_quota", False),
        (429, "organization_spend_limit_exceeded", "insufficient_quota", False),
        (429, "project_spend_limit_exceeded", "insufficient_quota", False),
        (429, "organization_usage_limit_exceeded", "insufficient_quota", False),
        (429, "billing_hard_limit_reached", None, False),
        (429, "slow_down", "insufficient_quota", False),
        (503, "credit_balance_exhausted", None, False),
        (503, "billing_error", None, False),
    ],
)
def test_transient_only_status_retries(
    status: int, code: str | None, kind: str | None, retry: bool
) -> None:
    api = ScriptedAPI(
        [
            httpx2.Response(
                status,
                json={
                    "error": {"message": "Synthetic error", "code": code, "type": kind}
                },
            ),
            success(),
        ]
    )
    if retry:
        assert api.provider().generate(request()).answer_text == "Synthetic answer."
        assert api.delays == [0.5]
        assert len(api.requests) == 2
        assert api.requests[0].content == api.requests[1].content
    else:
        with pytest.raises(OpenAIProviderError):
            api.provider().generate(request())
        assert len(api.requests) == 1 and api.delays == []


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_transient_transport_retry(error: type[httpx2.TransportError]) -> None:
    api = ScriptedAPI([error("Synthetic transport failure"), success()])
    assert api.provider().generate(request()).answer_text
    assert len(api.requests) == 2 and api.delays == [0.5]
    assert api.requests[0].content == api.requests[1].content


@pytest.mark.parametrize("budget", [0, 1, 2])
@pytest.mark.parametrize("failure", ["timeout", "connection", "server"])
def test_exhaustion_is_bounded_and_sanitized(budget: int, failure: str) -> None:
    events: list[httpx2.Response | Exception] = []
    for _ in range(3):
        if failure == "timeout":
            events.append(httpx2.ReadTimeout("synthetic-private-error"))
        elif failure == "connection":
            events.append(httpx2.ConnectError("synthetic-private-error"))
        else:
            events.append(
                httpx2.Response(
                    503, json={"error": {"message": "synthetic-private-error"}}
                )
            )
    api = ScriptedAPI(events)
    with pytest.raises(OpenAIProviderError) as caught:
        api.provider(OpenAIProviderConfig(max_retries=budget)).generate(request())
    assert len(api.requests) == budget + 1
    assert api.delays == [0.5, 1.0][:budget]
    assert len({req.content for req in api.requests}) == 1
    assert "synthetic-private-error" not in str(caught.value)
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert api.clients[0].is_closed()


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("2.5", 2.5),
        ("0", 0.5),
        ("-1", 0.5),
        ("invalid", 0.5),
        ("NaN", 0.5),
        ("Fri, 15 Jan 2027 08:00:04", 0.5),
        ("Fri, 15 Jan 2027 08:00:04 -0000", 0.5),
        ("Fri Jan 15 08:00:04 2027 EXTRA", 0.5),
        (format_datetime(datetime.fromtimestamp(1_800_000_003, UTC), usegmt=True), 3),
        (format_datetime(datetime.fromtimestamp(1_799_999_999, UTC), usegmt=True), 0.5),
        ("Friday, 15-Jan-27 08:00:04 GMT", 4),
        ("Friday, 15-Jan-27 07:59:59 GMT", 0.5),
        ("Friday, 32-Jan-72 08:00:04 GMT", 0.5),
        ("Friday, 15-XYZ-72 08:00:04 GMT", 0.5),
        ("Friday, 15-Jan-72 08:00:04", 0.5),
    ],
)
def test_retry_after_is_a_minimum(header: str, expected: float) -> None:
    api = ScriptedAPI(
        [httpx2.Response(503, headers={"Retry-After": header}), success()]
    )
    api.provider().generate(request())
    assert api.delays == [expected]


@pytest.mark.parametrize(
    "header",
    [
        "6",
        "120",
        "1e999",
        format_datetime(datetime.fromtimestamp(1_800_000_006, UTC), usegmt=True),
        "Friday, 15-Jan-27 08:00:06 GMT",
    ],
)
def test_excessive_server_delay_stops_without_retry(header: str) -> None:
    api = ScriptedAPI([httpx2.Response(503, headers={"Retry-After": header})])
    with pytest.raises(OpenAIProviderError):
        api.provider().generate(request())
    assert api.delays == [] and len(api.requests) == 1


@pytest.mark.parametrize(
    ("weekday", "day_field"), [("Tue", " 5"), ("Tue", "05"), ("Fri", "15")]
)
@pytest.mark.parametrize("server_delay", [4, 6, -1])
def test_asctime_retry_after_uses_utc_and_respects_delay_bound(
    weekday: str, day_field: str, server_delay: int
) -> None:
    now = datetime(2027, 1, int(day_field), 8, tzinfo=UTC).timestamp()
    server_date = datetime.fromtimestamp(now + server_delay, UTC)
    header = f"{weekday} Jan {day_field} {server_date:%H:%M:%S %Y}"
    api = ScriptedAPI(
        [httpx2.Response(503, headers={"Retry-After": header}), success()]
    )
    provider = OpenAIProvider(
        OpenAIProviderConfig(max_retry_delay_seconds=5),
        _client_factory=api.client,
        _sleep=api.delays.append,
        _clock=lambda: now,
    )
    if server_delay > 5:
        with pytest.raises(OpenAIProviderError) as caught:
            provider.generate(request())
        assert caught.value.__cause__ is caught.value.__context__ is None
        assert len(api.requests) == 1 and api.delays == []
    else:
        assert provider.generate(request()).answer_text == "Synthetic answer."
        assert len(api.requests) == 2
        assert api.delays == [max(0.5, server_delay)]
    assert api.clients[0].is_closed()


@pytest.mark.parametrize(
    ("current_year", "short_year", "second_offset", "expected_year"),
    [
        (2026, 72, 0, 2072),
        (2026, 77, 0, 1977),
        (2026, 76, -1, 2076),
        (2026, 76, 0, 2076),
        (2026, 76, 1, 1976),
        (2026, 26, 0, 2026),
        (2026, 26, 4, 2026),
        (2026, 25, 0, 2025),
        (1999, 0, 0, 2000),
        (2099, 0, 0, 2100),
        (2080, 29, 0, 2129),
        (2080, 31, 0, 2031),
    ],
)
def test_rfc850_year_rollover_uses_injected_utc_clock(
    current_year: int, short_year: int, second_offset: int, expected_year: int
) -> None:
    current = datetime(current_year, 1, 15, 8, 0, 4, tzinfo=UTC)
    expected = datetime(expected_year, 1, 15, 8, 0, 4 + second_offset, tzinfo=UTC)
    weekdays = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    header = (
        f"{weekdays[expected.weekday()]}, 15-Jan-{short_year:02d} "
        f"08:00:{4 + second_offset:02d} GMT"
    )
    now = current.timestamp()
    error = APIStatusError(
        "Synthetic transient error",
        response=httpx2.Response(
            503,
            headers={"Retry-After": header},
            request=httpx2.Request("POST", "https://api.openai.com/v1/responses"),
        ),
        body=None,
    )
    delay = max(0.0, expected.timestamp() - now)
    assert adapter._rfc850_date(header, current) == expected
    assert adapter._server_delay(error, lambda: now) == delay
    api = ScriptedAPI(
        [httpx2.Response(503, headers={"Retry-After": header}), success()]
    )
    provider = OpenAIProvider(
        OpenAIProviderConfig(max_retry_delay_seconds=5),
        _client_factory=api.client,
        _sleep=api.delays.append,
        _clock=lambda: now,
    )
    if delay > 5:
        with pytest.raises(OpenAIProviderError):
            provider.generate(request())
        assert api.delays == [] and len(api.requests) == 1
    else:
        assert provider.generate(request()).answer_text == "Synthetic answer."
        assert api.delays == [max(0.5, delay)] and len(api.requests) == 2
    assert api.clients[0].is_closed()


def test_configured_retry_delay_bound_and_server_opt_out() -> None:
    for headers in ({"Retry-After": "2"}, {"x-should-retry": "false"}):
        api = ScriptedAPI([httpx2.Response(503, headers=headers)])
        with pytest.raises(OpenAIProviderError):
            api.provider(OpenAIProviderConfig(max_retry_delay_seconds=1)).generate(
                request()
            )
        assert api.delays == [] and len(api.requests) == 1


@pytest.mark.parametrize("missing", ["usage", "details", "individual"])
def test_missing_usage_is_not_fabricated(missing: str) -> None:
    body = response_body()
    if missing == "usage":
        del body["usage"]
    elif missing == "details":
        del body["usage"]["input_tokens_details"]
        del body["usage"]["output_tokens_details"]
    else:
        body["usage"] = {"input_tokens_details": {"cache_write_tokens": 0}}
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    usage = api.provider().generate_with_usage(request()).usage
    expected = {
        "usage": None,
        "details": OpenAIUsage(10, 6, 16),
        "individual": OpenAIUsage(cache_write_tokens=0),
    }
    assert usage == expected[missing]


@pytest.mark.parametrize(
    "field_name",
    [
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    ],
)
@pytest.mark.parametrize("invalid", [-1, True, 1.5, "12"])
def test_invalid_usage_is_rejected_without_retry(field_name: str, invalid: Any) -> None:
    body = response_body()
    usage = body["usage"]
    container = usage
    if field_name in ("cached_tokens", "cache_write_tokens"):
        container = usage["input_tokens_details"]
    elif field_name == "reasoning_tokens":
        container = usage["output_tokens_details"]
    container[field_name] = invalid
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    with pytest.raises(MalformedModelOutputError):
        api.provider().generate_with_usage(request())
    assert len(api.requests) == 1 and not api.delays


def test_sequential_generations_retain_independent_usage_and_clients() -> None:
    api = ScriptedAPI([success(tokens=10), success(tokens=20)])
    provider = api.provider()
    first = provider.generate_with_usage(request())
    second = provider.generate_with_usage(request())
    assert first.usage == OpenAIUsage(10, 6, 16, 3, 2, 1)
    assert second.usage == OpenAIUsage(20, 6, 26, 3, 2, 1)
    assert first.result == second.result
    assert len(api.clients) == 2 and all(client.is_closed() for client in api.clients)
    assert {f.name for f in fields(provider)} == {
        "config",
        "_client_factory",
        "_sleep",
        "_clock",
    }


def test_overlapping_executions_bind_usage_to_their_own_result() -> None:
    barrier = Barrier(2)

    def handle(req: httpx2.Request) -> httpx2.Response:
        task = json.loads(json.loads(req.content)["input"])["task_text"]
        barrier.wait(timeout=10)
        count = int(task)
        body = response_body(tokens=count)
        body["output"][1]["content"][0]["text"] = json.dumps(
            {"answer_text": task, "citations": []}
        )
        return httpx2.Response(200, json=body)

    def client(config: OpenAIProviderConfig) -> OpenAI:
        return OpenAI(
            api_key="synthetic-unit-key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
        )

    provider = OpenAIProvider(_client_factory=client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                provider.generate_with_usage,
                [ModelRequest("11", ()), ModelRequest("22", ())],
            )
        )
    for generation, expected in zip(results, (11, 22), strict=True):
        assert generation.result.answer_text == str(expected)
        assert generation.usage is not None
        assert generation.usage.input_tokens == expected


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("model", "another-model"),
        ("timeout_seconds", 0),
        ("timeout_seconds", 121),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", True),
        ("max_retries", True),
        ("max_retries", 3),
        ("max_retries", -1),
        ("max_retries", 1.0),
        ("max_retry_delay_seconds", 0),
        ("max_retry_delay_seconds", 6),
        ("max_retry_delay_seconds", float("nan")),
    ],
)
def test_invalid_configuration_is_rejected(name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        OpenAIProviderConfig(**{name: value})


def test_value_objects_and_provider_are_frozen() -> None:
    config = OpenAIProviderConfig(
        timeout_seconds=1, max_retries=0, max_retry_delay_seconds=1
    )
    assert OpenAIProviderConfig(timeout_seconds=120).timeout_seconds == 120
    generation = OpenAIGeneration(ResearchResult("Answer."), OpenAIUsage(1))
    for value, name in [
        (config, "model"),
        (generation, "usage"),
        (generation.usage, "input_tokens"),
        (OpenAIProvider(), "config"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, None)


def test_missing_credentials_are_lazy_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise credential behavior only beyond the independently tested live hold.
    monkeypatch.setattr(adapter, "_require_live_qualification", lambda: None)
    provider = OpenAIProvider()
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "synthetic-admin-must-not-substitute")
    with pytest.raises(OpenAIProviderError) as caught:
        provider.generate(request())
    assert str(caught.value) == "OpenAI model execution failed"
    assert caught.value.__cause__ is caught.value.__context__ is None


def test_production_client_uses_official_endpoint_and_explicit_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Constructor inspection only; the module's offline fixture forbids sockets.
    monkeypatch.setattr(adapter, "_require_live_qualification", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-runtime-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://alternate.invalid/v1")
    with adapter._new_client(OpenAIProviderConfig(timeout_seconds=7)) as client:
        assert str(client.base_url) == "https://api.openai.com/v1/"
        assert client.timeout == 7
        assert client.max_retries == 0


def test_citation_support_remains_evaluator_responsibility() -> None:
    body = response_body()
    body["output"][1]["content"][0]["text"] = (
        '{"answer_text":"Answer.","citations":[{"source_id":"unsupported","chunk_id":"unsupported"}]}'
    )
    api = ScriptedAPI([httpx2.Response(200, json=body)])
    assert api.provider().generate(request()).citations == (
        CitationReference("unsupported", "unsupported"),
    )
