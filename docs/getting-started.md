# Getting started

This guide describes the local synthetic fixture preview for an existing,
separately approved offline environment. It needs no API key, hosted service,
frontend build or client data. The complete source checkout includes the six-task
trade/regulatory pack; source visibility does not qualify its substantive use.

**Fresh networked setup is on hold.** This release supplies no approved public
bootstrap or Docker installation procedure. The default live SDK client is
disabled even when credentials and opt-in flags are supplied. Check
[local setup qualification](release-status.md#local-setup-qualification) first.
If you lack a separately approved environment, use source inspection and
documentation contribution; do not bypass the hold to run the preview.

## Requirements and installation

The retained bootstrap targets macOS/Linux on ARM64 or x86-64; these are declared
targets, not four verified public platforms. Native pins are uv 0.13.4, managed
Python 3.13.17 and Gitleaks 8.30.1. Windows is not a native bootstrap target.
Retained source and CI configuration document engineering provenance, not an
installation clearance. Do not run the networked bootstrap or prescribe global
CA changes as a workaround. Existing CI authorization is separate from public
native setup qualification.

In an existing, approved environment with all locked dependencies and tools
already provisioned, verification runs offline:

```sh
make ci
```

No tools, virtual environment, runtime or dependency bundle is distributed with
the source-only release. Generated state stays ignored and untracked.

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
| Missing/wrong uv or virtualenv | Stop; fresh networked setup is held. Read release status and ask a maintainer about qualification. |
| Bootstrap cannot reach upstream | Do not retry or change TLS verification; bootstrap is not an approved public setup path. |
| CI cannot build offline | Preserve the failure; an approved environment must have inputs provisioned. Do not fetch replacements under this guide. |
| Port 8000 in use | Stop only your own preview, or use `PRIVILAB_PORT=8001 make preview` and the matching URL |
| Database schema rejected | Preserve old DB and select a new absolute path |
| Task/corpus unavailable | Use the complete source checkout and canonical corpus; do not fetch arbitrary replacements |
| No draft on reopening | Expected: history is metadata-only |
| Live execution fails | Expected: the default live SDK client and hosted live-eval are blocked; credentials do not enable them. |

The [live-smoke reference](architecture/live-eval.md) records retained design and
telemetry behavior, not an approved execution procedure. Native trust correction
and explicit qualification are required before live execution can be re-enabled.
