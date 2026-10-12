# Viewing architecture diagrams

The Mermaid source is embedded directly in the Markdown documents:

- [README control flow and component overview](../../README.md).
- [System components and request sequence](../architecture/system.md).
- [Authorization boundary](../architecture/trust-boundaries.md).

GitHub renders fenced `mermaid` blocks automatically. Local editor previews may
show source text unless Mermaid support is enabled. In Visual Studio Code, an
optional Mermaid-capable Markdown preview extension can provide this support;
install it through the editor's trusted marketplace if you want local rendering.
The source repository needs no new runtime library or frontend build for these
diagrams. Plain-language explanations and tables accompany the diagrams.

Edit the Mermaid blocks in their Markdown files so there is one source to maintain.
