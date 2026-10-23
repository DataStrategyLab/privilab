# Changelog

## v0.1.0 — Developer Preview

This entry describes the 0.1.0 source tree.
[GitHub Releases](https://github.com/DataStrategyLab/privilab/releases) is the
authoritative record of publication status, actual dates, tags and downloadable
source archives. The package version alone does not establish publication.
Distribution is source-only and designated as a GitHub pre-release; no wheel,
binary, container image or hosted demo is included.

### Existing implementation represented in this preview

- Synthetic context and permission contracts; fail-closed policy/scope boundaries.
- SQLite/FTS5 authorization-filtered retrieval and versioned fixture outputs.
- RunService, deterministic critical gates, immutable synthetic review actions
  and metadata-only provenance/history.
- OpenAI adapter with offline tests; default live client disabled pending native
  trust qualification. Historical local telemetry contracts remain documented.
- Six synthetic trade/regulatory golden cases and adversarial coverage.
- Offline CI, package-resource smoke and local server-rendered preview.

### Source-only execution restrictions

- Fresh networked native bootstrap and Docker execution remain held.
- Default live SDK construction fails closed before credential/HTTP access;
  existing opt-in flags do not enable it. Fixture preview and offline tests remain.
- No CA-store remediation, T01 closure or platform qualification is claimed.
- [Release notes](docs/release-notes-v0.1.0.md) identify included source,
  excluded artifacts and the authoritative publication record.

### Release documentation

- Apache-2.0 LICENSE/NOTICE and source/third-party rights guide.
- Public contributor, conduct/security contact and issue/PR entry points.
- Current architecture diagrams, setup/reproducibility and capability/evaluation
  guides; roadmap and dated unfinished-work notice.

Public-source publication and runtime qualification have separate review scopes.
Qualified domain and prospect rehearsal/release gates are
separate; all six domain scenarios remain INTERNAL_ONLY for substantive/prospect
use. Held successor bases remain HOLD BOTH and Gate 2 remains closed. See
[release status](docs/release-status.md) for the dated readiness assessment and
security restrictions. Publication does not lift those restrictions.
