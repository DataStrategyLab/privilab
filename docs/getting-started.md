# Getting started

This guide runs the local synthetic fixture preview. It needs no API key, hosted
service, frontend build or client data. Use a source checkout for the complete
six-task trade/regulatory pack.

**Setup qualification is pending.** Wait for maintainer clearance before a new
networked native bootstrap. The commands below describe the existing engineering
path, not a release-cleared public setup. Check
[local setup qualification](release-status.md#local-setup-qualification) first.

## Requirements and installation

Supported bootstrap platforms are macOS/Linux on ARM64 or x86-64. Install Git,
make, curl, tar, a POSIX shell and shasum or sha256sum. Windows is not a supported
native bootstrap platform. Docker setup is on a temporary security-qualification hold.

```sh
git clone https://github.com/DataStrategyLab/privilab.git
cd privilab
./scripts/bootstrap.sh --ci
make ci
```

Until publication, cloning requires repository access. Bootstrap verifies and
installs uv 0.12.23 and Gitleaks 8.30.1, selects managed Python 3.13.15 and installs
the frozen lockfile including development groups. Tools, interpreter and virtual
environment live under ignored local directories. Bootstrap may download from
upstream registries; subsequent CI is offline. No global Python setup is required.

## Preview and expected behavior

```sh
make preview
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), select a scenario, and click
**Run scenario**. Stop your own preview process with Ctrl-C.

| Choice | Expected observation |
| --- | --- |
| Standard synthetic researcher | Generated fixture draft, ALLOW, automated PASS; separate review available |
| Blocked researcher role | BLOCK; retrieval/model not executed; not reviewable |
| Missing workflow context | UNKNOWN; retrieval/model not executed |
| Unresolved permission condition | CONDITIONAL stop while condition is unresolved |
| Critical citation failure | Generated draft; automated BLOCK; Approve disabled |
| Malicious retrieved source | Controlled instruction-attack fixture; citation checks BLOCK; no general injection-immunity claim |
| Trade/regulatory choices | Six synthetic DRAFT tasks, for internal engineering exploration only |

Approve, Reject and Request revision each store one immutable synthetic decision
on a generated eligible run. A generated BLOCK permits negative decisions but
not approval. A stopped run has no review actions. These UI actions do not supply
qualified domain review or release authority.

Open **Recent history**, stop/restart the same preview, and reopen a run. Metadata
persists in the same DB, but generated answers and draft citation bodies are not
retained or regenerated. History lists the newest 25 runs; older saved run URLs
remain usable. Fresh source/configuration identity matters when comparing runs.

## Fresh databases and settings

By default the checkout uses `.local/preview/provenance.sqlite3`. To start a new
practice session without deleting earlier evidence, pick a never-used absolute
path and run these commands sequentially from the repository root:

```sh
test ! -e "$PWD/.local/preview/practice-01.sqlite3"
PRIVILAB_PREVIEW_DB="$PWD/.local/preview/practice-01.sqlite3" make preview
```

If the first command fails, choose another filename before running the second.
There is no automatic migration/repair of incompatible old databases. Preserve
old evidence and use a new database. `scripts/seed_demo.py` and `reset_demo.py`
are placeholders and intentionally fail; they are not setup/reset commands.
The preview loads approved synthetic fixtures through its normal execution path.

| Variable | Meaning |
| --- | --- |
| `PRIVILAB_PREVIEW_DB` | Non-empty absolute SQLite path; default checkout `.local/preview/provenance.sqlite3` |
| `PRIVILAB_PREVIEW_CORPUS_ROOT` | Non-empty absolute corpus path; default checkout `fixtures/corpus` |
| `PRIVILAB_HOST` | Preview bind host; retain `127.0.0.1` for this local demo |
| `PRIVILAB_PORT` | Default 8000; use another free local port if necessary |
| `PRIVILAB_ENVIRONMENT` | Display environment label; default local |

Defaults are anchored to the installed source location, not shell CWD. Browser
requests cannot set paths. Trade/regulatory execution requires the canonical
checkout corpus/task layout; a custom corpus root does not create a new task pack.
`.env.example` documents settings, but the application does not automatically
load a `.env` file. Use shell environment variables. Keep secrets and DBs untracked.

## Optional container

**Temporary security-qualification hold.**
[ADR-008](decisions/ADR-008-preview-deployment.md) permits a local container as an
architectural option; this release-specific hold does not supersede that decision.
The Dockerfile is retained for engineering traceability and reproducibility review.
Do not use it as a public installation or preview path while the hold applies.
Do not build, run or expose it for general external, shared, prospect, client,
hosted or production use.

The existing Makefile container targets remain executable; this documentation
change does not disable them. Their presence does not authorize execution or
establish image qualification. Digest pins and loopback port mapping do not
resolve outstanding security findings or guarantee isolation on every Docker
Engine version. See [Docker's port-publication guidance](https://docs.docker.com/engine/network/port-publishing/).

Docker operation and image redistribution require separate security qualification
and maintainer approval. The intended public preview path is native localhost
with public/synthetic inputs, once the separate
[native setup qualification](release-status.md#local-setup-qualification) is complete.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing/wrong uv or virtualenv | Run the pinned bootstrap; do not change required versions ad hoc |
| Bootstrap cannot reach upstream | Check permitted network access; bootstrap is the download step |
| CI cannot build offline | Confirm bootstrap completed; preserve the failure and rerun bootstrap when permitted |
| Port 8000 in use | Stop only your own preview, or use `PRIVILAB_PORT=8001 make preview` and the matching URL |
| Database schema rejected | Preserve old DB and select a new absolute path |
| Task/corpus unavailable | Use the complete source checkout and canonical corpus; do not fetch arbitrary replacements |
| No draft on reopening | Expected: history is metadata-only |
| Live-eval workflow fails | Expected: hosted live-eval is a deliberate fail-closed placeholder |

For controlled live-model work, use the separate [live-smoke guide](architecture/live-eval.md).
Do not make paid/live execution part of the normal quick start or CI.
