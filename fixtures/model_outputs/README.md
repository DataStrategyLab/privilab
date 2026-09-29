# Model-output fixtures

The package-owned manifest under
`src/privilab/adapters/models/resources/governed_fixtures/` registers three
repository-authored synthetic model-output fixtures: a happy path, an
unsupported citation, and one deliberately malformed research result. Each
fixture is hash-verified and covered by the license/source registry. Keeping the
canonical runtime files in the package makes them available to non-editable
installs without maintaining a second fixture copy here.

The malformed fixture is valid JSON but intentionally omits `chunk_id` from its
only citation. The fixture validator accepts only that registered, versioned
failure shape. `FixtureModelProvider` receives fixture text through constructor
injection; it does not load fixture or corpus material itself.

Live model output remains blocked.

DSL-117 additionally registers four versioned outputs in the same canonical package
resource manifest: trade/regulatory grounded, insufficient-source, missing-citation,
and missing-chunk. They retain the existing provider and binding contracts. The
insufficient-source answer is explicitly bounded to the supplied source. Negative
outputs are controlled failures, not substantive assertions or reviewed legal work.
