# Historical evidence publication proposals

**Proposal dated October 21, 2026; owner decision pending.** This inventory covers
the 25 files under `docs/product/evidence/` at baseline
`ede324d4f620afce0d0a579734e104894f99d456`. All existing evidence files remain
unchanged. Classification is a proposed disclosure treatment, not publication
approval, a new technical assessment, or an update to historical review outcomes.

Public developers should use [Getting started](getting-started.md),
[Reproducibility](reproducibility.md), the [tests](../tests/) and
[ADRs](decisions/README.md). Historical collectors have candidate-specific guards;
their records are not onboarding prerequisites or current qualification.

## Proposed treatments

- **PUBLIC_REPRODUCIBLE:** Useful public methodology or synthetic observations,
  interpretable with the recorded revision and limitations. This does not claim
  that a historical capture can be rerun on current main unchanged.
- **PUBLIC_SUMMARY_ONLY:** A separately authored, approved summary is more useful
  publicly than the full historical record. No replacement summary or removal
  is performed here.
- **RESTRICTED_INTERNAL:** Recommend retaining the detailed workpaper in approved
  private custody; publish only an approved summary if needed. The existing bytes
  remain committed pending a separate owner disposition.
- **NEEDS_OWNER_DECISION:** A record includes historical context or capture
  metadata requiring explicit disclosure and integrity decisions.

All paths below are relative to `docs/product/evidence/`. The table contains no
raw workpaper excerpts, personal workstation paths or private-system URLs.

| File | Proposed treatment | Reason / useful public scope |
| --- | --- | --- |
| `README.md` | PUBLIC_REPRODUCIBLE | Historical package navigation and interpretation limits |
| `demo-ui-claims-checklist.md` | PUBLIC_REPRODUCIBLE | UI/test procedure and bounded claims; asset rights remain separate |
| `gate5/README.md` | PUBLIC_SUMMARY_ONLY | Dated qualification narrative; retain original review attribution |
| `gate5/claims-and-limitations.md` | PUBLIC_SUMMARY_ONLY | Historical claims context; current limitations live in release status |
| `gate5/demo-materials.md` | PUBLIC_SUMMARY_ONLY | Historical presentation plan, not current external-use permission |
| `gate5/manifest.json` | NEEDS_OWNER_DECISION | Candidate, review and promotion metadata require scoped clearance |
| `gate5/scenarios.json` | PUBLIC_REPRODUCIBLE | Synthetic control observations tied to their execution identity |
| `dsl154/README.md` | NEEDS_OWNER_DECISION | Package reconstruction and historical decision references |
| `dsl154/acceptance-matrix.json` | NEEDS_OWNER_DECISION | Internal acceptance mapping and historical decision references |
| `dsl154/claims-and-limitations.md` | PUBLIC_SUMMARY_ONLY | Historical claims mapping; do not promote it to current approval |
| `dsl154/current-source-queue.json` | RESTRICTED_INTERNAL | Internal research/verification work queue |
| `dsl154/demo-materials.md` | PUBLIC_SUMMARY_ONLY | Historical script and qualification context |
| `dsl154/findings.json` | RESTRICTED_INTERNAL | Detailed historical review/remediation workpaper |
| `dsl154/handoffs.md` | RESTRICTED_INTERNAL | Internal operator, reviewer and evidence-promotion handoffs |
| `dsl154/independent-review.md` | RESTRICTED_INTERNAL | Candidate-specific historical review handoff |
| `dsl154/manifest.json` | NEEDS_OWNER_DECISION | Hash-bound capture identity and environment metadata |
| `dsl154/preflight.json` | PUBLIC_SUMMARY_ONLY | Historical tooling/environment checks, not a current setup contract |
| `dsl154/preview.json` | NEEDS_OWNER_DECISION | Original preview capture and environment metadata |
| `dsl154/repeatability.json` | PUBLIC_REPRODUCIBLE | Synthetic repeatability observations and stated comparison limits |
| `dsl154/sbom.cdx.json` | PUBLIC_REPRODUCIBLE | Historical lock-derived component inventory, not image/security clearance |
| `dsl154/scenarios.json` | PUBLIC_REPRODUCIBLE | Synthetic observations and capture-hash relationships |
| `dsl154/security-evidence.json` | PUBLIC_REPRODUCIBLE | Bounded public test/control mapping, not vulnerability clearance |
| `dsl154/substantive-review.json` | RESTRICTED_INTERNAL | Human-review worksheets; no completed domain signoff implied |
| `dsl154/supply-chain.json` | PUBLIC_SUMMARY_ONLY | Historical inventory/provenance limits; not redistribution permission |
| `dsl154/verification.json` | NEEDS_OWNER_DECISION | Captured command/environment metadata with integrity dependencies |

## Integrity and owner decisions

The proposal totals seven PUBLIC_REPRODUCIBLE, seven PUBLIC_SUMMARY_ONLY, five
RESTRICTED_INTERNAL and six NEEDS_OWNER_DECISION files. None is moved, edited,
deleted, rehashed as a replacement, or newly approved for public exposure.
Detailed baseline hashes, metadata exceptions and dependency references belong
in the private engineering record, not public PR comments.

The Gate 5 and DSL-154 manifests, scenario captures, preflight and supply-chain
records contain cross-file hash/reference relationships. The collectors
`scripts/collect_gate5_evidence.py` and `scripts/collect_dsl154_evidence.py` enforce
candidate/diff guards; their existing integration tests exercise identity,
preservation and failure behavior. This PR changes neither collectors nor those
historical contracts. Reproduction commands and links in the original packages
retain their original context.

Andrew must decide disclosure treatment, private custody and any approved public
summary before captured records are altered. A later authorized change must
inventory affected hashes, collector guards, tests and links, preserving the
original record and its review attribution. Removing bytes from HEAD would not
remove them from reachable Git/PR history. If a record cannot be exposed through
the existing repository, stop for a separate publication-route/history decision;
this PR performs no rewrite or deletion.

Publication approval, contributor/branding rights and effective repository
settings remain separate owner decisions. All existing successor-image holds,
prospect/production restrictions and source-only distribution boundaries in
[release status](release-status.md) remain in force.
