"""Offline SDK trust regressions; no real-chain or native-trust qualification."""

import hashlib
import json
import socket
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import certifi
import pytest
from openai import DefaultHttpx2Client

from privilab.adapters.models import openai as adapter

REVIEW_TIME = datetime(2026, 10, 24, tzinfo=UTC)
POLICY = (
    Path(__file__).parents[2]
    / "src/privilab/adapters/models/resources/tls-trust-policy.json"
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("TLS policy regressions must remain offline")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.delenv("SSLKEYLOGFILE", raising=False)


def policy_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes) -> None:
    folder = tmp_path / "resources"
    folder.mkdir()
    (folder / "tls-trust-policy.json").write_bytes(raw)
    monkeypatch.setattr(adapter, "files", lambda _: tmp_path)


def test_context_exclusively_loads_authenticated_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("host/default trust must not be loaded")

    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", forbidden)
    monkeypatch.setattr(ssl.SSLContext, "set_default_verify_paths", forbidden)
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/untrusted.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/synthetic/untrusted-directory")
    context, approved = adapter._sdk_tls_context(now=REVIEW_TIME)
    expected = ssl.create_default_context(cadata=Path(certifi.where()).read_text())
    assert type(context) is ssl.SSLContext
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.verify_flags == expected.verify_flags
    assert context.keylog_filename is None
    assert set(context.get_ca_certs(binary_form=True)) == set(
        expected.get_ca_certs(binary_form=True)
    )
    assert context.cert_store_stats()["x509_ca"] > 0
    assert approved is False


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 22, tzinfo=UTC),
        datetime(2026, 11, 22, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2026, 10, 24),
    ],
)
def test_unreviewed_or_expired_time_fails_closed(now: datetime) -> None:
    with pytest.raises(ValueError, match="review is not current"):
        adapter._sdk_tls_context(now=now)


def test_policy_tampering_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = POLICY.read_bytes().replace(
        b'"network_use_approved": false', b'"network_use_approved": true'
    )
    policy_bytes(monkeypatch, tmp_path, raw)
    with pytest.raises(ValueError, match="policy integrity"):
        adapter._sdk_tls_context(now=REVIEW_TIME)


@pytest.mark.parametrize(
    "raw", [b"not JSON", b"[]", b"{}", b'{"schema_version": true}']
)
def test_invalid_reviewed_policy_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes
) -> None:
    policy_bytes(monkeypatch, tmp_path, raw)
    monkeypatch.setattr(adapter, "_TLS_POLICY_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_missing_policy_does_not_load_host_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(adapter, "files", lambda _: tmp_path)
    with pytest.raises(FileNotFoundError):
        adapter._sdk_tls_context(now=REVIEW_TIME)


@pytest.mark.parametrize("contents", [None, b"", b"malformed PEM", b"tampered data"])
def test_missing_or_invalid_bundle_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, contents: bytes | None
) -> None:
    bundle = tmp_path / "bundle.pem"
    if contents is not None:
        bundle.write_bytes(contents)
    monkeypatch.setattr(certifi, "where", lambda: str(bundle))
    with pytest.raises((FileNotFoundError, ValueError)):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_dependency_version_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "version", lambda _: "0.synthetic")
    with pytest.raises(ValueError, match="source version mismatch"):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_keylogging_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSLKEYLOGFILE", "/synthetic/keylog")
    with pytest.raises(ValueError, match="key logging"):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_reviewed_malformed_bundle_still_fails_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle.pem"
    bundle.write_bytes(b"not a certificate")
    data = json.loads(POLICY.read_bytes())
    data["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    raw = (json.dumps(data) + "\n").encode()
    policy_bytes(monkeypatch, tmp_path, raw)
    monkeypatch.setattr(adapter, "_TLS_POLICY_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(certifi, "where", lambda: str(bundle))
    with pytest.raises(ssl.SSLError):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_nonstandard_context_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssl, "create_default_context", lambda **_: object())
    with pytest.raises(ValueError, match="standard-library SSL context"):
        adapter._sdk_tls_context(now=REVIEW_TIME)


def test_unqualified_policy_blocks_sdk_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unit-key")
    context, approved = adapter._sdk_tls_context(now=REVIEW_TIME)
    monkeypatch.setattr(adapter, "_sdk_tls_context", lambda: (context, approved))

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("an unqualified prototype must not create a client")

    monkeypatch.setattr(adapter, "DefaultHttpx2Client", forbidden)
    with pytest.raises(adapter.OpenAIProviderError, match="qualification is pending"):
        adapter._new_client(adapter.OpenAIProviderConfig())


def test_explicit_context_reaches_sdk_and_lifecycle_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unit-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic.invalid:8888")
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/untrusted.pem")
    context, _ = adapter._sdk_tls_context(now=REVIEW_TIME)
    # Test-only approval exercises transport wiring, never TLS qualification.
    monkeypatch.setattr(adapter, "_sdk_tls_context", lambda: (context, True))
    with adapter._new_client(adapter.OpenAIProviderConfig()) as client:
        transport = client._client
        assert str(client.base_url) == "https://api.openai.com/v1/"
        assert transport.trust_env is False
        assert transport.follow_redirects is False
        assert cast(Any, transport._transport)._pool._ssl_context is context
        assert not transport._mounts
        assert not transport.is_closed
    assert transport.is_closed


def test_failed_sdk_construction_closes_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unit-key")
    context, _ = adapter._sdk_tls_context(now=REVIEW_TIME)
    monkeypatch.setattr(adapter, "_sdk_tls_context", lambda: (context, True))
    clients: list[Any] = []
    factory = DefaultHttpx2Client

    def capture(**kwargs: Any) -> Any:
        client = factory(**kwargs)
        clients.append(client)
        return client

    def fail(**kwargs: Any) -> Any:
        raise RuntimeError("synthetic constructor failure")

    monkeypatch.setattr(adapter, "DefaultHttpx2Client", capture)
    monkeypatch.setattr(adapter, "OpenAI", fail)
    with pytest.raises(RuntimeError, match="synthetic constructor failure"):
        adapter._new_client(adapter.OpenAIProviderConfig())
    assert clients[0].is_closed
