# P0 adversarial and safe-failure coverage

This matrix records deterministic regression evidence for DSL-118. It covers
the approved local, synthetic P0 architecture; it is not a security,
confidentiality, privilege, compliance, production-readiness, or red-team
certification claim.

The applicable invariants are authorization before content reaches model
context; distinct fail-closed `BLOCK`, `UNKNOWN`, and `CONDITIONAL` permission
states; application-owned critical evaluation; metadata-first,
application-authored provenance; and human review separate from automated
evaluation. They are specified by ADRs 004--007, 009, and 010.

## Threat coverage

| Threat class | Governing invariant | Deterministic evidence | Expected safe outcome | Disposition |
| --- | --- | --- | --- | --- |
| Permission bypass and fabricated/broadened scope | Only an application-authorized `ALLOW` can invoke protected retrieval or model execution. | `tests/security/test_retrieval_authorization_boundary.py::test_non_allow_permission_states_cannot_reach_provider` (`BLOCK`, `UNKNOWN`, `CONDITIONAL`); `::test_malformed_fts_and_untrusted_text_cannot_weaken_authorization`; `::test_direct_provider_use_has_no_supported_scope_bypass`; `tests/security/test_run_service_boundary.py::test_missing_material_context_stops_before_retrieval_or_model` | No protected progression and no fabricated allow state. | Existing coverage is sufficient. |
| Cross-context leakage | Every governed user, role, client, matter, and workflow dimension is an exact retrieval isolation boundary. | `tests/security/test_retrieval_authorization_boundary.py::test_each_context_dimension_is_an_exact_isolation_boundary`; `tests/security/test_run_service_boundary.py::test_run_service_preserves_cross_context_retrieval_isolation` | Cross-context chunks cannot enter a request or trusted run record. | Existing coverage is sufficient. |
| Unauthorized source entitlement or source text | Authorization-scoped chunks alone reach model context, provenance metadata, or preview. | `tests/integration/test_preview_app.py::test_unauthorized_sources_never_reach_model_provenance_or_html`; `tests/security/test_retrieval_authorization_boundary.py::test_direct_provider_use_has_no_supported_scope_bypass` | Unauthorized source IDs, chunk IDs, and text are absent from those surfaces. | Existing coverage is sufficient. |
| Malicious source instructions / prompt injection | Retrieved text remains data and cannot become application authority. | `tests/security/test_walking_skeleton_boundary.py::test_exact_attack_text_enters_authorized_context_without_acquiring_authority`; `tests/security/test_trade_regulatory_boundary.py::test_exact_authorized_model_context_and_authority[malicious-source-injection-source_ids1]`; `tests/integration/test_trade_regulatory.py::test_all_golden_cases_without_network` | The DSL-117 malicious-source run blocks; it cannot change permission, scope, evaluation, review, or release state. | Existing coverage is sufficient. |
| Fabricated, malformed, unauthorized, or cross-context citations | Model output cannot mint source authority or alter application-authored provenance; invalid critical grounding blocks. | `tests/integration/test_preview_app.py::test_model_citations_cannot_add_authorized_source_rows`; `tests/unit/test_evaluations.py::test_missing_and_cross_run_provenance_produce_error_blocks`; `::test_gate_rejects_fabricated_critical_pass_for_failed_input`; DSL-117 `citation-grounding-challenge` golden case | No source row is added; critical gate blocks and approval is unavailable. | Existing coverage is sufficient. |
| Unsafe tool-authority or release-authority attempt | The model controls no runtime tool, authorization, or release authority. | `tests/security/test_walking_skeleton_boundary.py::test_exact_attack_text_enters_authorized_context_without_acquiring_authority`; `tests/integration/test_walking_skeleton.py::test_block_rejects_approval_but_allows_negative_decisions` | Injection cannot invoke or authorize a tool, create an approval, or grant release. | No runtime model-controlled tool executor or authenticated external release mechanism exists or is exercised. The existing synthetic review-eligibility and server-side approval-denial controls remain in scope. |
| Synthetic canary / sensitive-payload leakage | Trusted provenance, telemetry, logs, and exception-derived preview output retain only the permitted minimum. | `tests/security/test_openai_provider_boundary.py::test_sensitive_values_do_not_escape_sdk_boundary`; `tests/integration/test_model_telemetry.py::test_complete_call_latency_and_roundtrip`; `tests/security/test_walking_skeleton_boundary.py::test_exact_attack_text_enters_authorized_context_without_acquiring_authority`; strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable` | Synthetic payloads and `PRIVATE SENTINEL` do not appear in persisted state or rendered safe-failure pages. | Existing coverage strengthened for outer evaluation/persistence failure. |
| Provenance tampering, malformed rows, and unsupported mutation | Finalized provenance and evidence are append-only, reconstructable, and application-authored. | `tests/integration/test_run_service_integration.py::test_finalized_child_provenance_rejects_every_mutation_form`; `tests/security/test_walking_skeleton_boundary.py::test_corrupt_snapshot_is_not_repaired_and_cannot_authorize_review`; `tests/integration/test_model_telemetry.py::test_corrupt_evidence_rejected_on_read`; `tests/unit/test_run_review.py::test_snapshots_reject_malformed_or_contradictory_evidence` | Invalid stored state is rejected or classified as not reviewable; it is not normalized into trusted evidence. | Existing coverage is sufficient. |
| Malformed/inconsistent critical results | Critical evidence must satisfy the task/criterion contract and fail closed. | `tests/unit/test_evaluations.py::test_execution_error_and_invalid_or_empty_result_sets_block`; `::test_gate_rejects_result_with_evidence_contradicting_its_status`; `::test_type_correct_inconsistent_evaluator_output_invalidates_result_set`; `tests/unit/test_run_review.py::test_snapshots_reject_malformed_or_contradictory_evidence` | Gate is `BLOCK` with invalid/error evidence; it is never treated as `PASS`. | Existing coverage is sufficient. |
| Evaluator or evaluation-persistence failure | An outer failure preserves the immutable run but invents neither evaluation nor human-review evidence; an in-runner criterion failure produces bounded error evidence and blocks. | Strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable` (`privilab.application.run_review.evaluate` and `SQLiteProvenanceStore.append_evaluation` injections); `tests/unit/test_evaluations.py::test_evaluator_exception_is_sanitized_error_and_blocks` (replacement `evaluators.EVALUATOR_REGISTRY[EvaluatorKind.AUTHORIZED_SOURCE]`) | Outer failure: `NOT REVIEWABLE`, no evaluation/review row, no allowed decisions, and server-side `APPROVE` rejection. Criterion failure: valid `EVALUATOR_EXECUTION_ERROR` evidence and `BLOCK`. | Strengthened existing outer-failure test; no fabricated `BLOCK` snapshot for absent evidence. |

The outer evaluation injection is deliberately at the `evaluate` symbol imported
by `privilab.application.run_review`; it represents an exception escaping the
whole evaluation call. The persistence injection is
`SQLiteProvenanceStore.append_evaluation`. Both execute after the immutable run
is finalized. The criterion-level injection instead replaces the registered
authorized-source evaluator in `privilab.evals.evaluators.EVALUATOR_REGISTRY`,
which the runner catches and converts to bounded error evidence.

## Acceptance-criteria traceability

| Acceptance criterion | Evidence / disposition |
| --- | --- |
| 1. Threat coverage matrix and class mapping | This document maps each of the ten required threat classes and records the bounded exclusions below. No in-scope class is deferred without a rationale. |
| 2. Authorization remains fail closed | `tests/security/test_retrieval_authorization_boundary.py::test_non_allow_permission_states_cannot_reach_provider[policy0]` (`BLOCK`), `[policy1]` (`UNKNOWN`), and `[policy2]` (unresolved `CONDITIONAL`); `tests/security/test_run_service_boundary.py::test_missing_material_context_stops_before_retrieval_or_model`. |
| 3. Cross-context isolation and protected content surfaces | All five exact dimension cases of `tests/security/test_retrieval_authorization_boundary.py::test_each_context_dimension_is_an_exact_isolation_boundary` (`user_id-user-b`, `role_id-role-b`, `client_id-client-b`, `matter_id-matter-b`, `workflow_id-workflow-b`); `tests/security/test_run_service_boundary.py::test_run_service_preserves_cross_context_retrieval_isolation`; `tests/integration/test_preview_app.py::test_unauthorized_sources_never_reach_model_provenance_or_html`; and `tests/security/test_retrieval_authorization_boundary.py::test_direct_provider_use_has_no_supported_scope_bypass`. |
| 4. Untrusted source instructions cannot acquire authority | `tests/security/test_walking_skeleton_boundary.py::test_exact_attack_text_enters_authorized_context_without_acquiring_authority`; `tests/security/test_trade_regulatory_boundary.py::test_exact_authorized_model_context_and_authority[malicious-source-injection-source_ids1]`. |
| 5. Model output cannot mint trusted evidence | `tests/integration/test_preview_app.py::test_model_citations_cannot_add_authorized_source_rows`; `tests/unit/test_evaluations.py::test_gate_rejects_fabricated_critical_pass_for_failed_input`. |
| 6. Critical evaluation fails closed | `tests/unit/test_evaluations.py::test_execution_error_and_invalid_or_empty_result_sets_block`; `tests/unit/test_evaluations.py::test_gate_rejects_result_with_evidence_contradicting_its_status`; and strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable[evaluate]` / `[append_evaluation]`. |
| 7. Provenance integrity is enforced | `tests/integration/test_run_service_integration.py::test_finalized_child_provenance_rejects_every_mutation_form`; `tests/security/test_walking_skeleton_boundary.py::test_corrupt_snapshot_is_not_repaired_and_cannot_authorize_review`; and `tests/integration/test_model_telemetry.py::test_corrupt_evidence_rejected_on_read`. |
| 8. Sensitive synthetic canaries do not leak on covered paths | `tests/security/test_openai_provider_boundary.py::test_sensitive_values_do_not_escape_sdk_boundary`; `tests/integration/test_model_telemetry.py::test_complete_call_latency_and_roundtrip[None-10-GENERATED]`, `[exhaust-4000000030-FAILED]`, and `[timeout-1500000030-FAILED]`; and strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable[evaluate]` / `[append_evaluation]`. |
| 9. Safe failures are bounded and visible | All `PERMISSION`, `AUTHORIZATION`, `RETRIEVAL`, and `MODEL` cases of `tests/integration/test_preview_app.py::test_stage_failures_are_safely_rendered_from_real_service_outcomes`; strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable[evaluate]` / `[append_evaluation]`. |
| 10. Failure stages preserve truthful progression evidence | All state/stage cases of `tests/integration/test_run_service_integration.py::test_r06_04_failure_truth_table_application_and_raw_sql_parity`; the four cases of `tests/integration/test_preview_app.py::test_stage_failures_are_safely_rendered_from_real_service_outcomes`; and strengthened `tests/integration/test_walking_skeleton.py::test_partial_completion_remains_visible_and_unreviewable[evaluate]` / `[append_evaluation]`. |
| 11. Material failures are regression assets | The strengthened partial-completion test is deterministic. No material product defect was found on the approved base; the work closes an assertion-coverage gap. |
| 12. DSL-117 remains valid | `tests/integration/test_trade_regulatory.py::test_all_golden_cases_without_network` and `make golden-eval` run `grounded-happy-path`, `insufficient-source`, `permission-block`, `critical-eval-failure`, `citation-grounding-challenge`, and `malicious-source-injection`. |
| 13. No architecture drift | Diff review: documentation and regression assertions only; no provider, evaluator kind, persistence model, permission model, dependency, runtime MCP/tool, or trust-boundary change. |

## Bounded exclusions and verification limits

No runtime model-controlled tool executor or authenticated external release
mechanism is implemented or exercised. The absence is architectural, not a
claim that such a capability would be safe if added. Synthetic human-review
eligibility, approval denial, persistence, anti-forgery, and independent
review controls remain covered.

Repository/issue-instruction attacks against development agents and correlated
implementation/reviewer-agent failure are repository-process controls. They do
not justify runtime-agent infrastructure, so they are outside this deterministic
P0 runtime matrix.

Coverage is deterministic, local, network-free, and synthetic-only. It neither
uses nor changes the protected holdout set, live model evaluation, substantive
DSL-117 task/rubric meaning, or prospect-demo status.

## Material-failure record

No material implementation defect was discovered on the approved base. The
existing outer evaluation/persistence failure contract already preserves the
completed immutable run and omits downstream evidence. DSL-118 strengthens its
regression evidence to prove the initial and reopened responses, history,
server-side approval rejection, absence of evaluation/review writes, canary
non-retention on those applicable surfaces, no execution replay on reads, and
safe independent rerun behavior.
