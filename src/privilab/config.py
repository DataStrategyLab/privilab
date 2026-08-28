"""Secret-free local configuration for the DSL-105 placeholder."""

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Safe settings required by the local placeholder preview."""

    title: str = "PriviLAB"
    host: str = "127.0.0.1"
    port: int = 8000
    environment: str = "local"
    reference_banner: str = "Synthetic/reference demo only"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load only non-secret, local preview settings."""
    values = os.environ if environ is None else environ
    port = int(values.get("PRIVILAB_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PRIVILAB_PORT must be between 1 and 65535")
    return Settings(
        host=values.get("PRIVILAB_HOST", "127.0.0.1"),
        port=port,
        environment=values.get("PRIVILAB_ENVIRONMENT", "local"),
    )
