# Decision log

## 2026-08-27 — Linear MCP engineering exception

2026-08-27: Approved Linear MCP for Codex engineering/project-management access only. This supersedes the Gate 3 bootstrap assumption of no MCP for engineering sessions. Linear MCP is not part of the PriviLAB runtime, may not access client/DMS data or deployment credentials, and does not authorize architecture changes or autonomous merge/release actions. Approved by Andrew.

This exception does not add repository MCP configuration, a runtime dependency,
or product functionality.

## 2026-09-12 — Task-specific Codex implementation model routing

Normal Codex implementation model selection is task-specific. The human task
owner selects the supported model and reasoning effort appropriate to each task:
routine work may use a balanced model, while complex, security-sensitive, or
high-judgment work may use a higher-capability model. Dedicated Codex code
review remains pinned to Sol through `review_model`. This changes development
tooling policy, not PriviLAB runtime model architecture.

## 2026-09-28 — GPT-6 Astra for dedicated Codex review

Dedicated Codex `/review` now uses `gpt-6-astra` through
`.codex/config.toml`.

This supersedes only the review-model portion of the 2026-09-12
task-specific Codex implementation model-routing decision. Normal Codex
implementation model and reasoning-effort selection remain task-specific
and are not repository-pinned.

The change affects development tooling only. It does not change PriviLAB
runtime model/provider architecture, application behavior, agent autonomy,
sandboxing, network access, web-search policy, multi-agent policy, human
review requirements, or merge/release authority.
