# DSL-119 demo UI verification aid

This checklist couples the Reference Demo presentation to executable checks. It
does not replace canonical DSL product, brand, Legal Practice, accessibility, or
claims controls. The current Linear issue is authoritative for acceptance.

## Presentation and disclosure rules

- Normal pages say **PriviLAB Reference Demo** and **Synthetic/reference demo only**.
  The landing page uses the README's reference-architecture positioning.
- Generated content is a **Draft result**, with exactly **Presented for reviewer
  consideration.** The automated gate and local human decision are separate.
- A displayed citation pair must occur in the run's trusted source/chunk metadata.
  Other pairs become **Reference unavailable** with neither identifier in HTML or
  attributes. This disclosure check never changes evaluator input or provenance.
- Reopened runs and history retain metadata only. They cannot replay execution,
  reconstruct a draft/citation list, or assume the default scenario.
- Stopped runs can have an actual recorded stop evaluation. Show it as such under
  traceability; never imply that retrieval, generation, or human review occurred.
  Missing evaluation evidence remains unavailable, not a manufactured BLOCK.
- Approval eligibility comes from `RunReviewView.allowed_decisions`. Display copy
  explains existing state and cannot override it. Review remains a local synthetic
  exercise with one immutable decision, not external release authority.
- Fixture configuration, synthetic data, localhost execution, provider abstraction,
  and automated PASS must not be promoted into legal, privilege, privacy,
  confidentiality, security, compliance, endorsement, benchmark, or readiness claims.

## Approved asset evidence

Andrew supplied and approved the Data Strategy Lab logo for this demo on
2026-10-02, recorded in DSL-119. This is the sole approved asset:

`src/privilab/web/static/branding/DSL_primary_full-color_light-bg_1024w_v1.png`

- PNG, 1024 × 444; served locally with its original aspect ratio.
- SHA-256: `351a2769ed240d03f178294b74b67df5a3bc95568bc26e722aba9e8d40034007`.
- Do not regenerate, recolor, crop, or substitute it. Approval for this demo does
  not grant broader branding or redistribution rights. CSS accents are local
  implementation choices, not official brand standards.
- Carry this source/approval/hash evidence into any later PR description.

## Current Linear acceptance mapping

| Criteria | Implementation / verification |
| --- | --- |
| 1–5: identity, logo, coherent workbench | Shared base, local stylesheet, approved PNG; `test_landing_shell_and_bounded_scenario_guide`, `test_local_assets_integrity_and_static_confinement`; visual inspection. |
| 6–7: hierarchy and progressive detail | Run summary; context, permission, evidence, draft, evaluation, human review, traceability; native disclosures for technical evidence. Manual scan/disclosure checks. |
| 8–10: synthetic context and control sequence | `test_all_scenarios_share_shell_claims_and_truthful_sections`; persistent banner and synthetic labels at point of use. |
| 11–13: distinct permission stops and unreached stages | Existing permission-stop and stage-failure tests, strengthened `assert_no_later_sections`; no draft/evaluation/review work area on a stopped run, recorded stop evidence remains inspectable. |
| 14: authorized metadata only | Existing unauthorized-source isolation test; exact-pair disclosure regression and missing-chunk/cross-source cases. |
| 15–17: draft and original citations without new authority | `test_citations_are_disclosed_only_from_original_result_without_authority_changes`, `test_authorized_citation_markup_is_escaped`; exact reviewer phrase and unchanged citation counts/gate/provenance. |
| 18–22: separate evaluation and bounded human decisions | All-scenario review-button parity; `test_review_labels_final_explanation_and_history`; existing review conflict/race and partial-completion regressions. |
| 23–25: traceability and metadata-only history | Existing newest-25, restart, older URL, no-replay tests; all-scenario reopen and history shell checks. |
| 26–27: bounded failure and suppressed internals | Existing stage/composition/template/storage/evaluation failure tests and DSL-118 canary regressions; recovery links and hardcoded template-independent fallback. |
| 28–29: claims and endorsement | Expanded `FORBIDDEN_CLAIMS` / `assert_safe_page` across all scenarios, review decisions, history, reopen, invalid requests, and failures. Human review must also inspect implied claims; vocabulary checks alone are insufficient. |
| 30–33: keyboard, textual status, semantics, responsive layout | Deterministic landmark/heading/label/reference/table assertions; manual keyboard, focus, zoom, target-size, contrast, table-scroll, and viewport checks below. |
| 34–35: architecture, local assets, deterministic execution | Static confinement/external-reference checks; `test_presentation_keeps_the_approved_runtime_and_no_frontend_build`, `make preview`, full `make ci`, installed-wheel assets, and applicable local-container checks. |
| 36: task/golden meaning | Existing DSL-117 tests and all six golden cases through `make ci`; task pack, fixtures, rubrics, and expectations remain unchanged. |
| 37–38: adversarial protections and authority boundaries | Existing DSL-118/security tests, full `make ci`, and dedicated Codex review. No domain, adapter, evaluator, review, or persistence contract change. |

## Preview acceptance procedure

Run `make preview` and inspect the localhost Reference Demo. Use the compact
selector and its expandable guide; option values, ordering, and default are
unchanged. Run each scenario independently, including the six trade/regulatory
cases. Demonstrate Approve, Reject, and Request revision on separate eligible
runs; inspect disabled approval on a generated BLOCK and final decisions.

Inspect keyboard-only navigation and visible focus, the skip link, select,
disclosures, source/evaluation table scrolling, review controls, and history links.
Check laptop dimensions, a narrow viewport, and actual 200% browser zoom. Confirm
that tables scroll within their panels, page content stacks logically, targets are
at least 24 × 24 CSS px or sufficiently spaced, and status meaning survives without
color. Reopen history and confirm draft/citation absence without execution replay.

Run the local container workflow when Docker is available. The existing container
contains the basic fixture scenarios and canonical corpus; the six trade/regulatory
tasks still require the source checkout. This issue does not change that boundary.

## Deliberate limits and completion gates

- No JavaScript dependency, external presentation asset, new framework, live-model
  execution, telemetry invention, retention change, or hosted deployment.
- No dark mode, source-text viewer, formal accessibility certification, browser
  test dependency, screenshot/video package, or DSL-120 release evidence package.
- Long technical tables use bounded horizontal scrolling at narrow widths.
- The fixed emergency fallback deliberately remains unbranded and minimal so a
  template or stylesheet failure cannot prevent recovery.
- Record actual automated/manual results in the implementation handoff; this
  checklist is not itself evidence that a check passed.
- Dedicated Codex review, required non-author/CODEOWNER review, Andrew's preview
  acceptance, and Andrew's final merge decision remain separate gates. Do not mark
  DSL-119 Done from automated test results alone.
