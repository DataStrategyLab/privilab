# Trust boundaries

## Untrusted inputs

User-supplied text, retrieved source material, fixture content, and model output
are untrusted. Source content must never grant permissions, select tools, change
system instructions, or bypass evaluation/review gates.

## Authorization boundary

Permission evaluation precedes retrieval. Retrieval must receive an explicit
authorization scope and filter sources before any source text enters future
model context. Missing or unresolved material context fails closed.

## Model boundary

Models are providers behind an application-controlled interface. They do not
control runtime tools, authorization, retrieval scope, evaluation release logic,
or human-review state. DSL-105 contains no provider implementation.

## Data boundary

Only public, synthetic, anonymized, redacted, or properly licensed material may
enter the repository. Client/DMS content and credentials remain outside the
system and outside Linear MCP engineering sessions.

## Engineering boundary

Codex may use approved user-level engineering integrations. Repository Codex
configuration disables workspace network access, web search, and multi-agent
delegation. Linear MCP is not a runtime dependency and grants no architecture,
merge, release, client-data, or credential authority.

## Release boundary

Automated evaluation, independent Codex review, non-author human review, and
Andrew's merge/release decision are distinct controls. Critical evaluation and
Critical/High review findings fail closed. Merge alone does not mark work Done.
