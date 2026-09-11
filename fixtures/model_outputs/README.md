# Model-output fixtures

`manifest.json` registers three repository-authored synthetic model-output
fixtures: a happy path, an unsupported citation, and one deliberately malformed
research result. Each fixture is hash-verified and covered by the license/source
registry.

The malformed fixture is valid JSON but intentionally omits `chunk_id` from its
only citation. The fixture validator accepts only that registered, versioned
failure shape. `FixtureModelProvider` receives fixture text through constructor
injection; it does not load this directory or any corpus material itself.

Live model output remains blocked.
