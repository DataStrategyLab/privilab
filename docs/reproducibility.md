# Reproducibility

PriviLAB's normal verification path is deterministic, fixture-based and secret-free.
It exercises application controls; it does not measure live-model stability or
establish legal correctness. The canonical command is `make ci`.

Fresh networked native setup remains held. The commands below require an existing,
separately approved offline environment; they do not authorize downloading tools
or running the retained bootstrap. Live SDK use is disabled pending qualification.
See [local setup qualification](release-status.md#local-setup-qualification).

## Record the inputs

Keep the source SHA and working-tree state, Python and tool versions, `uv.lock`,
fixture/corpus/task/rubric versions and any explicit preview configuration together.
A Git SHA alone does not identify a materially changed model, permission policy,
corpus or environment. Do not reuse historical approval for a successor runtime.

```sh
git rev-parse HEAD
git status --short
.tools/bin/uv --version
.venv/bin/python --version
.tools/bin/gitleaks version
```

Current native pins: Python 3.13.17, uv/uv_build 0.13.4 and Gitleaks 8.30.1. Native managed-Python sources are frozen in
`configs/python-downloads-3.13.17.json`. The Dockerfile retains its separate
unqualified, historically pinned image versions. Exact artifact
provenance and applicable component records are in `licenses/registry.yaml`.
Equal Python version strings alone do not establish identical distribution bytes.

## Reproduce from source

In an existing approved environment, record the exact checkout before verification.
A fresh checkout may be inspected as source, but this guide does not qualify a
fresh installation. Do not copy executable commands from historical evidence as
current setup guidance. With all locked inputs already provisioned:

```sh
git rev-parse HEAD
make ci
git diff --check
git status --short
```

Retain the actual recorded commit. A successful final
status is clean. No virtualenv, tool directory, old DB or generated result should
be copied into Git. A fresh checkout using caches is cache-backed reproducibility,
not independent fresh upstream acquisition.

The retained bootstrap contains network/download operations and is not approved
for public native setup. Existing CI has its separately scoped engineering
authorization; successful CI does not qualify host certificate trust. Once inputs
are provisioned in an approved offline environment,
`make ci` invokes frozen offline lock checking, repository contracts, fixture/
license validation, formatting/lint/type checks, wheel/sdist build and governed
package smoke, unit/integration/security tests, deterministic smoke/golden
cases, history/worktree secret scans and generated-state checks. It also verifies
that repository-visible state is unchanged. Do not replace it with selected tests.

The five smoke and six golden cases have defined expected outcomes. Test counts
can change as coverage grows; record observed counts rather than treating an old
count as the acceptance criterion. To inspect golden results separately:

```sh
make golden-eval
```

This is supplemental and does not replace CI.

## Repeat preview behavior

Use a new ignored DB as described in [Getting started](getting-started.md).
Record actual run IDs, configuration hashes, permission/gate states and synthetic
decisions. Repeat scenarios on distinct runs. Reopen the same DB after restarting
the preview to inspect persisted metadata. Answer/source bodies are transient;
metadata hashes establish identity, not legal truth or full answer replay.

Permission BLOCK, UNKNOWN and unresolved CONDITIONAL should stop before retrieval/
model execution. Generated critical evaluation failure should disable approval.
A safe new run must not change earlier immutable decisions.

## Existing qualification collectors

The [historical evidence index](product/evidence/README.md) links candidate-bound
collectors and manifests. Those collectors may enforce exact candidate ancestry,
allowed diffs, clean status and never-used output paths. Do not run them on a new
release-doc branch and reinterpret a refusal as product failure, or edit guards to
get a PASS. Their observations retain their original execution identity and time.

## Limits

- Fixture repeatability does not establish live-provider nondeterminism, current
  model availability, substantive legal quality or protected holdout performance.
- A lock export/SBOM is component inventory, not vulnerability clearance or an
  image attestation. Current security/OSS review remains separate.
- Docker setup is on a temporary security-qualification hold; the Dockerfile
  remains an engineering reference during the hold. Digest pins do not clear
  security findings; Docker operation requires separate
  qualification and maintainer approval. Historical container observations retain
  their original scope, including cached layers, OS packages and task-pack limits.
- Pre-existing incompatible evidence schemas fail closed; no automatic migration
  or deletion is performed.
- Public source publication, package/image redistribution, hosted operation,
  prospect eligibility and production deployment have separate review scopes.
