from pathlib import Path

import pytest

from privilab import config
from privilab.config import Settings, load_settings
from privilab.main import create_app


def test_safe_defaults_are_local_and_secret_free() -> None:
    settings = load_settings({})

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.environment == "local"
    assert settings.reference_banner == "Synthetic/reference demo only"


def test_port_must_be_valid() -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        load_settings({"PRIVILAB_PORT": "70000"})


def test_checkout_corpus_default_does_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings({})
    assert (
        settings.preview_corpus_root
        == Path(config.__file__).resolve().parents[2] / "fixtures/corpus"
    )
    assert (
        settings.preview_database
        == Path(config.__file__).resolve().parents[2]
        / ".local/preview/provenance.sqlite3"
    )
    assert list(tmp_path.iterdir()) == []


def test_explicit_paths_are_lazy_and_injectable(tmp_path: Path) -> None:
    corpus = tmp_path / "absent-corpus"
    database = tmp_path / "absent-directory/preview.sqlite3"
    injected = Settings(preview_corpus_root=corpus, preview_database=database)
    configured = load_settings(
        {
            "PRIVILAB_PREVIEW_CORPUS_ROOT": str(corpus),
            "PRIVILAB_PREVIEW_DB": str(database),
        }
    )
    assert configured == injected
    create_app(injected)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("key", ["PRIVILAB_PREVIEW_CORPUS_ROOT", "PRIVILAB_PREVIEW_DB"])
@pytest.mark.parametrize(
    "value", ["", " ", ".", "fixtures/corpus", "../corpus", "~/corpus"]
)
def test_paths_reject_empty_or_relative_overrides(key: str, value: str) -> None:
    with pytest.raises(ValueError, match="non-empty absolute"):
        load_settings({key: value})


def test_injected_corpus_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        Settings(preview_corpus_root=Path("relative"))
