# PriviLAB

PriviLAB is a controlled legal-AI reference demo. This repository is currently
at the P0 bootstrap stage: it contains the approved repository boundaries, a
placeholder FastAPI/Jinja preview, and a reproducible verification contract.

The placeholder is not a legal research product, does not call a model, and
does not contain client or matter data.

## Prerequisites

- macOS or Linux
- POSIX shell, Git, curl, tar, make, and a SHA-256 utility
- Docker only if you want to exercise the optional local container preview

## Bootstrap and verification

```sh
./scripts/bootstrap.sh
make ci
```

Bootstrap is the only step permitted to download the pinned toolchain and
locked Python dependencies. After bootstrap, `make ci` is secret-free and
network-free.

## Local preview

```sh
make preview
```

Open <http://127.0.0.1:8000>. The page is intentionally limited to a clearly
marked synthetic/reference-demo placeholder.

An optional local container can be built with `make container-build` and run
with `make container-preview`. No hosted deployment is approved for P0.

## Current boundaries

- Python 3.13, FastAPI, Jinja, SQLite/FTS5 when persistence is implemented.
- Modular monolith; no runtime autonomous-agent framework.
- No model-controlled runtime tools, DMS integration, or runtime MCP.
- FixtureModelProvider must precede any live OpenAIProvider work.
- OpenAIProvider/live GPT work remains blocked until P0-10 is accepted.

See [AGENTS.md](AGENTS.md), [DATA_HANDLING.md](DATA_HANDLING.md), and
[docs/architecture/system.md](docs/architecture/system.md) before making
changes.
