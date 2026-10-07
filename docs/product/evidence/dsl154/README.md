# DSL-154 prospect-demo candidate qualification — 1.0.0

This engineering package supports a later decision; it grants no prospect use.
The product candidate is `f19f5542105661614c225691c3df780264de8262`.
The manifest identifies the execution/tooling commit separately. The final committed
package/review HEAD is bound in the author-session handoff, not self-embedded in a
commit containing its own hash. No independent review runs in the author session.

## Sources of truth

- `manifest.json`: candidate/configuration identity, artifact references, pending gates.
- `acceptance-matrix.json`: every Linear A–H criterion, evidence class, owner, outcome.
- `verification.json`: commands, exact execution HEAD, times, counts, hashes, limits.
- `scenarios.json` and `repeatability.json`: actual observations and comparisons.
- `security-evidence.json`: bounded test-node/control mappings.
- `supply-chain.json` and `sbom.cdx.json`: locked components, notices, provenance scope.
- `substantive-review.json`: six local source checks and unsigned review worksheets.
- `current-source-queue.json`: mutable facts requiring approved external verification.
- `claims-and-limitations.md`, `demo-materials.md`, `handoffs.md`: presentation controls.
- `independent-review.md`: separate reviewer setup, command, scope and pending status.

Historical `../gate5/` is read-only. Its old manifest, claims, pending fields, and
candidate identity are preserved byte-for-byte. Andrew's October 5, 2026
INTERNAL DEMO READY decision is a separate Linear record for candidate
`8d4bad1833431452bd6e99d2c238f5aa51cebbf5`; comment
`735781ca-370c-4e70-88e1-fc5044f9603f` on
[DSL-120](https://linear.app/rohic/issue/DSL-120).
It is not a post-DSL-153 prospect approval.

## Corrected qualification after independent review

Prior tooling `06d4fe827d3c8f3aa16a0df4de7a3b1938598ba7` and final package
`c1001ffa0477771848f47f5fffd37893983843c3` are superseded for final qualification.
The prior independent review reported a P2 history-failure masking defect. Its
reproduction, regression proof, and author remediation are recorded in findings.json.
New T2 observations replace affected qualification evidence. Review of the new
final H2 remains pending in a separate context; prior review is not H2 approval.

Unaffected preview.json is retained byte-for-byte with its original prior-T SHA.
Original container/preview command records are separately labeled in verification.json.
They are supporting observations, not new T2 execution or human acceptance.

## Reconstruction

1. For qualification, use exact T2 from the manifest. For final verification/review,
   use exact H2 from the author handoff. Make a fresh local clone with
   `git clone --local --no-hardlinks --no-checkout SOURCE DEST`, then
   `git -C DEST checkout --detach EXACT_HEAD`. No network fetch is needed.
2. Confirm `git rev-parse HEAD`, clean status, candidate ancestry, and an
   evidence-only diff from the product candidate. `../gate5/`, product source,
   tasks, fixtures, evaluator, permission, dependencies, and schema must be unchanged.
3. Provision approved pinned uv/Gitleaks and managed Python/package caches only;
   use the recorded hashes and source provenance. Do not copy a virtualenv,
   previous DB, or execution output. Run bootstrap inside the fresh checkout.
4. Set `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never`, and `UV_NO_PROGRESS=1`.
   Run `./scripts/bootstrap.sh --ci`, `make ci`, `git diff --check`, and
   `make golden-eval`. Save exact times, exits, identities, counts, and bounded
   results in fresh ignored local paths. Never substitute another sequence for CI.
5. For three captures, select three never-used DB/JSON pairs under the checkout's
   ignored `.local/dsl154/`. For each pair run:

```sh
.venv/bin/python scripts/collect_dsl154_evidence.py \
  --database "$PWD/.local/dsl154/capture-01.sqlite3" \
  --output "$PWD/.local/dsl154/capture-01.json"
```

The collector refuses existing paths and dirty/materially changed checkouts. It
uses the historical collector's scenario composition/helpers, not its old
candidate guard or package identity. The current execution is observed afresh.
`compare_captures` compares three exported records; never reuse one capture three
times. Qualification is deterministic fixture repeatability, not live-model stability.

For the corrected history/repeatability verification, after three fresh captures:

```sh
.venv/bin/python - <<'PYTHON'
import importlib.util, json
from pathlib import Path
spec = importlib.util.spec_from_file_location("dsl154", "scripts/collect_dsl154_evidence.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
captures = [json.loads(Path(f".local/dsl154/capture-{n:02}.json").read_text()) for n in range(1, 4)]
assert collector.compare_captures(captures)["passed"]
for capture in captures:
    history = next(c for c in capture["checks"] if c["scenario_id"] == "history-reopen")
    assert history["passed"]
    assert [o["phase"] for o in history["observations"]] == ["baseline", "final"]
    assert all(collector.history_observation_passed(o) for o in history["observations"])
    assert [len(o["run_ids"]) for o in history["observations"]] == [10, 12]
PYTHON
```

6. Start `PRIVILAB_PREVIEW_DB="$PWD/.local/dsl154/preview-01.sqlite3" make preview`
   only after confirming the DB does not exist. Use loopback and stop only the
   process started for this check. Record actual HTTP/browser outcomes separately.
7. Retain a separate offline wheel/sdist build because CI deletes its temporary
   build. Use `.tools/bin/uv build --offline --no-sources --cache-dir .local/dsl154/build-cache --out-dir OUTPUT`, then
   `.venv/bin/python scripts/verify_built_package.py ABSOLUTE_WHEEL_PATH ABSOLUTE_FRESH_SMOKE_DIRECTORY`.
   Hash retained outputs. Export the existing lock with pinned uv's
   `export --offline --frozen --all-groups --format cyclonedx1.5 --cache-dir .local/uv-cache`.
8. Run container commands only with existing Docker permission. Missing access
   is an operator handoff, not permission to escalate or reuse old execution.

The environment label is **FRESH_CHECKOUT_CACHE_BACKED**. Fresh source checkout and
virtualenv do not make cached inputs independently retrieved or currently verified
upstream. The separate cache record, lock, tool hashes, and checkout SHA disclose
that limitation. Python version alone is not its complete distribution identity.

## Evidence interpretation

Each of three captures covers 14 checks and 12 run attempts. Six DSL-117 cases are
supplemented by UNKNOWN, unresolved CONDITIONAL, three separate synthetic review
actions, denied approval after critical failure, history/reopen, and safe rerun.
Actual observations are compared with existing golden expectations. Expected BLOCK
is successful negative-test evidence, not a passing draft. Missing-source output
must qualify the supplied evidence; it does not assert that no legal obligation exists.

Collector exports contain minimum synthetic metadata, transient-output hashes and
citation identifiers, never answer/task/query/source bodies. Output hashes do not
allow answer replay. Review rows are identified by run ID and actual decision/time;
there is no invented standalone review ID. All local review actions are classified
AUTOMATED_SYNTHETIC_DEMO_DECISION. Real human gates remain unsigned.

The single composite history-reopen check retains ordered baseline and final
observations: 10 runs at baseline, 12 after the additional permission cases. Each
observation independently records all nine persistence-table snapshots, run IDs,
HTTP statuses, metadata-only view checks, and retrieval/model/run/evaluation guards.
Both complete observations must pass. Any failure, missing/duplicate phase,
incomplete metadata, or interrupted observation fails qualification. A later PASS
cannot replace an earlier FAIL. Interrupted attempts retain bounded metadata and
completed earlier observations without exporting exceptions or content.
Timestamps/IDs/run duration are excluded only
from repeatability comparison, not from execution evidence. Fixture model cost,
usage, and provider latency are unavailable, not measured zero.

A material product finding stops product implementation in DSL-154. Preserve failure,
severity, governing requirement/ADR, minimal regression and proposed corrective
issue. A correction creates a new candidate and requires affected requalification.

## Completion boundary

Author completion is a committed, verified, clean engineering package and either
READY FOR INDEPENDENT CODEX REVIEW or NOT READY FOR INDEPENDENT CODEX REVIEW.
The separate reviewer must inspect the final committed package HEAD against the
frozen product base, including unchanged candidate behavior and all new evidence
logic. Do not recommend In Review before that review. Human approvals, external
facts, holdout disposition and Andrew's Gate 5 decision remain separate.
