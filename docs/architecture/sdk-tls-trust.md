# Application-scoped SDK trust prototype

**Status: prototype; acceptance BLOCKED. Live SDK client disabled by policy.**
This does not qualify native setup, repair host trust or approve publication.
The existing [native/Docker provenance decision](../decisions/ADR-011-native-and-frozen-docker-provenance.md)
and [setup holds](../release-status.md#local-setup-qualification) remain in effect.

## Selection and failure behavior

The default application client validates a packaged policy, the installed
certifi version and the SHA-256 of the bundle bytes before constructing its SSL
context. Those same bytes are passed as `cadata`; no checked file is reopened.
Normal certificate/hostname checks and Python's strict defaults remain enabled.
The context reaches the supported `DefaultHttpx2Client` interface with
`trust_env=False` and `follow_redirects=False`. The official API origin,
credentials, timeouts, retries and application permission boundary are unchanged.
The client is closed after execution or a failed SDK constructor.

The policy sets `network_use_approved: false`. Changing that flag requires a
reviewed policy/digest change and explicit owner acceptance; an environment
variable cannot enable it. Missing, malformed, tampered, wrong-version, expired
or not-yet-reviewed material fails closed with sanitized provider errors. An
active `SSLKEYLOGFILE` setting is rejected. There is no system-store fallback,
global SSL monkeypatch or verification bypass. Fixture preview does not need to
construct this live client.

## Exact maintained source

The only added dependency is unmodified **certifi 2026.10.19**, MPL-2.0.
The approved upstream wheel is pinned through the project's uv source mapping
and generated lock, with SHA-256
`42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b`.
The actual packaged CA bundle has SHA-256
`50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
The archive and embedded license were inspected; other dependency pins remain
unchanged. Available PyPI provenance metadata matches the artifact subject and
expected publisher, but its signature has **not** been independently verified
with an approved compatible verifier. Digest checking is not signer verification.
See [PyPI metadata](https://pypi.org/pypi/certifi/2026.10.19/json),
[upstream license](https://github.com/certifi/python-certifi/blob/2026.10.19/LICENSE)
and [project notices](../../THIRD_PARTY_NOTICES.md).

The bundled policy is reviewed from October 23 through November 22, 2026 UTC
(end exclusive). This proposed 30-day maximum review age limits silent staleness;
it is not an upstream certificate validity period or an accepted risk interval.
Owner signoff on the cutoff, loss of ambient proxy support and disabled redirects
is still required before merge. No custom proxy, CA path, client certificate or
additional SDK authentication mode is introduced.

## Native macOS versus static trust

| Property | Existing SDK default: HTTPX2/truststore | Proposed app-only context |
| --- | --- | --- |
| Verifier | macOS Security framework on Darwin; platform-specific elsewhere | Managed Python/OpenSSL and explicit bundle only |
| Root changes and local distrust | Native policies can receive OS/administrator updates | No native policy inheritance; reviewed bundle rotation required |
| Revocation/distrusted intermediates | Native verification can apply platform revocation/distrust mechanisms; actual incident outcome remains untested | No automatic OS distrust, CRL/OCSP fetching or compromised-key denylist is added |
| Missing intermediate retrieval | Native mechanisms may fetch missing intermediates | Complete chain must be available to OpenSSL; no new AIA fetcher |
| Alternate/cross-signed paths | Effective native policy must be tested independently | Removing one root does not establish exclusion of every affected intermediate/key/path |
| Environment CA/proxy settings | Default transport can honor them | Ignored by the explicit client; intentionally incompatible with ambient enterprise proxies |
| Evidence today | Static implementation reviewed; no incident-chain rejection proof | Bundle/source-selection and fail-closed offline tests only; no incident TLS clearance |

**The prototype does not match every native protection.** Its live-use policy
therefore stays disabled. Current recommendation is HOLD, not replacement of the
native verifier as an accepted security fix. The safe alternative is to retain
the network restriction and existing native-verifier evidence while the owner
decides whether a correction can preserve those protections or a separately
assessed publication scope can exclude the unqualified path. Neither alternative
is automatically authorized by this document.

The comparison uses the installed SDK 3.19.2, HTTPX2/HTTPCore2 2.13.1 and truststore
0.10.4 source; [current HTTPX2 SSL guidance](https://pydantic.dev/docs/httpx2/advanced/ssl/)
and [truststore documentation](https://truststore.readthedocs.io/en/latest/)
corroborate the distinction. Newer documentation is not a new runtime version.
The [official SDK interface](https://developers.openai.com/api/reference/python)
supports explicit SSL contexts. No live API call is needed to inspect it.

## Acceptance, rotation and recovery

Offline tests cover authenticated source selection, unsafe/missing policy and
bundle rejection, no host fallback, environment isolation, transport wiring,
client cleanup and packaged policy presence. They use mocks for HTTP requests;
they are **not** affected-chain or positive TLS controls. Authentic incident and
independent positive-chain fixtures are unavailable in the reviewed custody.
Their acquisition and use need separately scoped authorization. Revocation and
alternative-chain limitations remain material acceptance blockers.

After an approved rotation, retain the exact upstream artifact, verify its digest
and available provenance, inspect unmodified bundle/license bytes, update policy
and the code-bound policy digest, regenerate the lock with pinned uv, preserve
notices, and rerun applicable tests and canonical `make ci`. New contexts/clients
replace old ones; do not mutate pooled live connections. Future enabling requires
owner acceptance of per-verifier evidence, policy and residual limitations,
dedicated Codex review and genuine non-author human review on the final commit.

Rollback stops native-network/live use and preserves evidence. Revert only the
unaccepted prototype through normal review while maintaining the explicit HOLD.
Keep patched uv/Python; never restore affected roots, disable TLS verification
or recommend vulnerable tools as recovery. No host certificate store changes or
new host backup/recovery operation are part of this prototype.

uv's patched bundled default is separate. Python defaults, system/custom uv,
bootstrap curl and networked pip remain unqualified at their distinct scopes;
normal package verification uses pip offline. No Docker, held A1/A2, foreign
platform, production, client-data or prospect qualification is supplied here.
