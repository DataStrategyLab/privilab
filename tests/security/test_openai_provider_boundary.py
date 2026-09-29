"""Credential, outbound-content, and SDK failure boundaries without networking."""

from __future__ import annotations

import ast
import json
import logging
import socket
import traceback
from dataclasses import fields
from inspect import signature
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import OpenAI

from privilab.adapters.models import openai as adapter
from privilab.adapters.models.openai import (
    OpenAIProvider,
    OpenAIProviderConfig,
    OpenAIProviderError,
)
from privilab.application import ModelRequest, ModelSourceChunk, RunOutcome
from privilab.application.model_provider import MalformedModelOutputError, ModelProvider
from privilab.application.provenance import RunConfiguration, RunProvenance
from privilab.config import load_settings
from privilab.domain import ResearchResult


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.mark.parametrize(
    "failure", ["success", "auth", "timeout", "malformed", "creation", "close"]
)
def test_sensitive_values_do_not_escape_sdk_boundary(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    credential = "synthetic-credential-" + "do-not-log"
    private_error = "synthetic-sdk-error-" + "do-not-retain"
    task = "synthetic-task-" + "not-telemetry"
    source = "synthetic-source-" + "not-telemetry"
    raw_response = "synthetic-raw-response-" + "not-telemetry"
    monkeypatch.setenv("OPENAI_API_KEY", credential)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://forbidden.invalid")
    caplog.set_level(logging.DEBUG)
    observed: list[dict[str, Any]] = []
    constructed: list[OpenAI] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer " + credential
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        observed.append(body)
        if failure == "auth":
            return httpx2.Response(
                401,
                json={"error": {"message": f"{credential} {private_error} {source}"}},
            )
        if failure == "timeout":
            raise httpx2.ReadTimeout(
                f"{credential} {private_error} {source}", request=request
            )
        text = json.dumps({"answer_text": "Synthetic answer.", "citations": []})
        if failure == "malformed":
            text = f"{credential} {private_error} {source}"
        return httpx2.Response(
            200,
            json={
                "id": raw_response,
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.6-terra",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "id": "message",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": text, "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 7,
                    "input_tokens_details": {
                        "cached_tokens": 2,
                        "cache_write_tokens": 3,
                    },
                },
            },
        )

    def fake_constructor(**kwargs: Any) -> OpenAI:
        assert kwargs["api_key"] == credential
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        assert kwargs["max_retries"] == 0 and kwargs["timeout"] == 30
        if failure == "creation":
            raise RuntimeError(f"{credential} {private_error}")
        client = OpenAI(
            **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        )
        if failure == "close":
            close = client.close

            def fail_close() -> None:
                close()
                raise RuntimeError(f"{credential} {private_error}")

            monkeypatch.setattr(client, "close", fail_close)
        constructed.append(client)
        return client

    monkeypatch.setattr(adapter, "OpenAI", fake_constructor)
    provider = OpenAIProvider(OpenAIProviderConfig(max_retries=0))
    assert constructed == []
    request = ModelRequest(task, (ModelSourceChunk("source-id", "chunk-id", source),))
    if failure == "success":
        generation = provider.generate_with_usage(request)
        assert generation.result == ResearchResult("Synthetic answer.")
        exposed = repr(generation)
    else:
        with pytest.raises(Exception) as caught:
            provider.generate_with_usage(request)
        assert caught.value.__context__ is caught.value.__cause__ is None
        assert not hasattr(caught.value, "request")
        assert not hasattr(caught.value, "response")
        exposed = (
            str(caught.value)
            + repr(vars(caught.value))
            + "".join(traceback.format_exception(caught.value))
        )
    if failure != "creation":
        assert len(observed) == 1
        assert json.loads(observed[0]["input"]) == {
            "task_text": task,
            "source_chunks": [
                {"source_id": "source-id", "chunk_id": "chunk-id", "text": source}
            ],
        }
    assert all(client.is_closed() for client in constructed)
    captured = capsys.readouterr()
    for sentinel in (credential, private_error, task, source, raw_response):
        assert sentinel not in exposed
        assert sentinel not in caplog.text
        assert sentinel not in captured.out + captured.err


@pytest.mark.parametrize("active_caller", [False, True])
@pytest.mark.parametrize("failure_kind", ["sdk", "malformed"])
def test_sanitized_failure_hides_visible_caller_and_sdk_chains(
    active_caller: bool,
    failure_kind: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caller = "synthetic-caller-" + "context-sentinel"
    credential = "synthetic-credential-" + "chain-sentinel"
    sdk_error = "synthetic-sdk-" + "chain-sentinel"
    task = "synthetic-task-" + "chain-sentinel"
    source = "synthetic-source-" + "chain-sentinel"
    caplog.set_level(logging.DEBUG)
    clients: list[OpenAI] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        raw_failure = " ".join((credential, sdk_error, task, source))
        if failure_kind == "sdk":
            raise httpx2.ReadTimeout(raw_failure, request=request)
        return httpx2.Response(
            200,
            json={
                "id": "synthetic-chain-response",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.6-terra",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "id": "synthetic-chain-message",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": raw_failure,
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    def client(config: OpenAIProviderConfig) -> OpenAI:
        sdk = OpenAI(
            api_key=credential,
            base_url="https://api.openai.com/v1",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
        )
        clients.append(sdk)
        return sdk

    provider = OpenAIProvider(
        OpenAIProviderConfig(max_retries=0), _client_factory=client
    )
    request = ModelRequest(task, (ModelSourceChunk("source-id", "chunk-id", source),))
    expected_error = (
        OpenAIProviderError if failure_kind == "sdk" else MalformedModelOutputError
    )

    def execute() -> str:
        with pytest.raises(expected_error) as caught:
            provider.generate(request)
        assert type(caught.value) is expected_error
        assert caught.value.__cause__ is None
        if not active_caller:
            assert caught.value.__context__ is None
        assert not hasattr(caught.value, "request")
        assert not hasattr(caught.value, "response")
        return (
            str(caught.value)
            + repr(vars(caught.value))
            + "".join(traceback.format_exception(caught.value))
            + "".join(
                traceback.TracebackException.from_exception(caught.value).format()
            )
        )

    if active_caller:
        try:
            raise RuntimeError(caller)
        except RuntimeError:
            exposed = execute()
    else:
        exposed = execute()
    assert len(clients) == 1 and clients[0].is_closed()
    captured = capsys.readouterr()
    for sentinel in (caller, credential, sdk_error, task, source):
        assert sentinel not in exposed
        assert sentinel not in caplog.text
        assert sentinel not in captured.out + captured.err


def test_provider_has_no_authorization_retrieval_or_persistence_dependencies() -> None:
    path = Path(adapter.__file__)
    tree = ast.parse(path.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    application_imports = {name for name in imports if name.startswith("privilab.")}
    assert application_imports == {
        "privilab.application.model_provider",
        "privilab.domain.research",
    }


def test_no_public_endpoint_credentials_or_telemetry_contract_extension() -> None:
    settings = load_settings({})
    assert not hasattr(settings, "api_key")
    assert set(signature(OpenAIProviderConfig).parameters) == {
        "model",
        "timeout_seconds",
        "max_retries",
        "max_retry_delay_seconds",
    }
    assert tuple(signature(ModelProvider.generate).parameters) == ("self", "request")
    assert {field.name for field in fields(ModelRequest)} == {
        "task_text",
        "source_chunks",
    }
    assert {field.name for field in fields(RunOutcome)} == {
        "run_id",
        "status",
        "permission_result",
        "result",
        "failure_stage",
    }
    for contract in (RunConfiguration, RunProvenance, RunOutcome, ResearchResult):
        names = {field.name for field in fields(contract)}
        assert {
            "usage",
            "latency",
            "pricing",
            "cost",
            "api_key",
            "raw_response",
        }.isdisjoint(names)
