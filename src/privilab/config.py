"""Non-secret local fixture-preview configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    """Local preview paths and server settings, resolved without side effects."""

    title: str = "PriviLAB"
    host: str = "127.0.0.1"
    port: int = 8000
    environment: str = "local"
    reference_banner: str = "Synthetic/reference demo only"
    preview_database: Path = _CHECKOUT_ROOT / ".local/preview/provenance.sqlite3"
    preview_corpus_root: Path = _CHECKOUT_ROOT / "fixtures/corpus"

    def __post_init__(self) -> None:
        for path in (self.preview_database, self.preview_corpus_root):
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError("preview paths must be absolute Path values")


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load only non-secret, local preview settings."""
    values = os.environ if environ is None else environ
    port = int(values.get("PRIVILAB_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PRIVILAB_PORT must be between 1 and 65535")
    defaults = Settings()
    paths: dict[str, Path] = {}
    for name, key, default in (
        ("preview_database", "PRIVILAB_PREVIEW_DB", defaults.preview_database),
        (
            "preview_corpus_root",
            "PRIVILAB_PREVIEW_CORPUS_ROOT",
            defaults.preview_corpus_root,
        ),
    ):
        raw = values.get(key)
        if raw is not None and (not raw.strip() or not Path(raw).is_absolute()):
            raise ValueError(f"{key} must be a non-empty absolute path")
        paths[name] = default if raw is None else Path(raw)
    return Settings(
        host=values.get("PRIVILAB_HOST", "127.0.0.1"),
        port=port,
        environment=values.get("PRIVILAB_ENVIRONMENT", "local"),
        preview_database=paths["preview_database"],
        preview_corpus_root=paths["preview_corpus_root"],
    )
