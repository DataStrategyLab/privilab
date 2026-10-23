# ADR-011: Independently governed native and frozen-container provenance

- Status: Accepted for implementation; release qualification pending
- Decision owner: Andrew Tsintsiruk
- Decision date: 2026-10-22
- Implementation tracking: DSL-185; Docker setup restriction: DSL-184
- Supersedes: only the *cross-artifact version-equality assumption* in repository contract tests; ADR-008 remains accepted

## Context

PriviLAB v0.1.0 is an experimental, source-only Developer Preview. Its native
bootstrap and CI are an intended localhost/synthetic development path. A separate
historical Dockerfile is retained as a reproducibility reference under an explicit
temporary security-qualification hold. The two paths have different qualification
states and may therefore require different pinned toolchain versions.

The previous repository contract required the Dockerfile's uv and Python tags to
match the active native bootstrap versions. That equality would force changes to
the frozen, unqualified Docker references whenever a native security update was
necessary. It would not establish that an updated image had been qualified.

## Decision

1. Independently maintain **native bootstrap/CI provenance** and **frozen Docker
   reference provenance**. Do not infer deployment permission or risk acceptance
   from architecture, source availability, immutable tags, or passing tests.
2. The active native bootstrap must use one exact pinned, checksum-verified uv
   release, the same exact `uv_build` version and `[tool.uv].required-version`,
   a specifically selected managed CPython patch/build, and a matching
   `actions/setup-python` patch. The initial accepted implementation targets
   uv/uv_build **0.13.4** and CPython **3.13.17**, subject to the DSL-185
   verification gate. No untested version is declared qualified by this ADR.
3. Where the pinned uv release predates the managed Python patch, the bootstrap
   may use a **checked-in local** `UV_PYTHON_DOWNLOADS_JSON_URL` manifest
   restricted to the four supported macOS/Linux ARM64/x86-64 targets. The
   manifest must pin vendor release URLs, exact build identifiers and SHA-256
   digests. Verify the manifest parser/schema and downloaded artifact bytes
   during implementation. Do not retrieve an unpinned network-hosted manifest.
4. Preserve **the existing frozen Dockerfile bytes and image digests**, including
   its separate uv/Python versions. Container image versions must remain exact
   SHA-256-digest-pinned and agree with their independently reviewed registry
   entries. Contract tests must reject mutable, malformed, mismatched or stale
   references. The intentionally frozen container versions need not equal the
   current native bootstrap versions.
5. Preserve the Docker execution hold in public quickstart, release-status and
   security documentation. Existing executable Makefile targets are retained
   only for historical/internal reference; their presence does not authorize a
   build/run. Do not pull, build, scan, select, redistribute, deploy or endorse
   the frozen image under this decision.
6. Version/artifact changes require exact upstream source, license/NOTICE,
   checksum/provenance review, frozen lock verification, canonical `make ci`,
   dedicated Codex review, a genuine non-author human review and Andrew's final
   merge/release decision. Source publication is a separate gate.

## Required contract invariants

### Proposed amendment: application-scoped SDK trust

An isolated prototype may use exactly pinned certifi 2026.10.19, authenticated
bundle bytes and a packaged, code-bound review policy for the existing SDK
transport. This is application trust provenance, separate from uv bundled trust,
Python defaults and frozen Docker provenance. It introduces no global CA change.

**Amendment acceptance pending.** The prototype's `network_use_approved` flag
remains false. A proposed 30-day review cutoff, `trust_env=False` (including loss
of ambient proxy support), disabled redirects and loss of native platform trust
features require explicit owner decision and applicable human review. Static
trust does not establish equivalent revocation or alternate-chain protection.
See [SDK trust scope and comparison](../architecture/sdk-tls-trust.md).

- Native `uv`, `uv_build` and project uv version requirement match exactly.
- Native managed CPython version and CI setup-python version match exactly; its
  selected upstream build date, source and hashes are recorded and checked.
- Frozen Docker `FROM` image tags and digests remain immutable and independently
  match `container:uv` and `container:python` registry references.
- An attempted Docker/image version or digest edit, stale registry record,
  removed Docker hold, unpinned Python download source or unsupported platform
  must fail an applicable test or an owner-controlled review gate.
- No existing permission, evaluation, provenance, data-isolation, licensing,
  secret-scan or clean-working-tree control is weakened.

## Consequences and rollback

This adds an explicit provenance and testing distinction, not a second supported
deployment path. The local Python download manifest and updated bootstrap create
new change-controlled inputs that must remain public, synthetic-data-safe and
auditable. A patched version can be technically present without passing the
release qualification gate.

If bootstrap, artifact authentication, build backend, lockfile or CI validation
fails, keep the native quickstart on hold, preserve the private release status
and revert the unaccepted implementation branch. Do not recommend the former
affected uv version as a safe public alternative. Docker qualification and the
separate held successor-image review remain outside this ADR.
