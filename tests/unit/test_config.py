import pytest

from privilab.config import load_settings


def test_safe_defaults_are_local_and_secret_free() -> None:
    settings = load_settings({})

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.environment == "local"
    assert settings.reference_banner == "Synthetic/reference demo only"


def test_port_must_be_valid() -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        load_settings({"PRIVILAB_PORT": "70000"})
