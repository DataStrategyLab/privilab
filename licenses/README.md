# License and attribution guide

## Project source

[LICENSE](../LICENSE) contains Apache License 2.0. [NOTICE](../NOTICE) records DSL
attribution. The project license applies to project-authored code, original
project-authored documentation and original synthetic fixtures, except material
explicitly identified with separate terms. It allows use, modification and
redistribution under its terms, including notice and patent provisions.

Third-party dependencies, external references and brand assets retain their
applicable rights. Apache section 6 does not grant trademark rights. Included DSL
branding identifies this project; do not imply DSL/vendor endorsement of a fork.
Discuss additional branding use with the owner. Brand asset provenance and public redistribution scope still require owner
confirmation before publication; do not infer that a code license expands them.

## Registry and obligations

[registry.yaml](registry.yaml) records reviewed artifacts, versions, source/license
locations, intended use, attribution and open questions. Original synthetic entries
historically say “no external license”; they describe origin, not an exemption from
the now-published project license. Existing history and fixture hashes are preserved.

[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) indexes component license
sources. Installing dependencies from their upstream distributions differs from
redistributing their bytes. A registry table or SBOM does not replace the full
upstream terms, copyright statements or applicable NOTICE files when redistributing
packages, bundled runtimes or container images.

The release-documentation scope prepares the source repository. It does not
publish wheel/sdist/container binaries. Before distributing such artifacts,
inspect the actual built contents and preserve all applicable license/notice
files for dependencies, embedded/vendor code, Python/native components, base OS
packages and tools. Current source/advisory/OSS review and any unresolved material
rights remain separate release gates; see [release status](../docs/release-status.md).

## Adding content

Document original author/source, exact version, rights/permitted use, required
attribution, restrictions, reviewed date and any open question. Register fixture/
corpus hashes and applicable references. Do not treat public availability as
permission to copy restricted legal databases, benchmark tasks or vendor assets.
Follow [data handling](../DATA_HANDLING.md) and contributor review.

The project-authored Code of Conduct in this branch does not incorporate the
Contributor Covenant adaptation from the earlier release draft. No new outside
policy content or license is introduced by that file.
