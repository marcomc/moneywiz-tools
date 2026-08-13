# MoneyWiz Tools instructions
These rules do not apply outside of work under `moneywiz-tools/`.

# MoneyWiz API subtree instructions

These rules apply only to work under `moneywiz-api/`.

- Database-backed integration tests must be opt-in through
  `MONEYWIZ_TEST_DB_PATH`. Skip them when the variable is absent, validate an
  explicit path read-only before model creation, and never inherit a user
  database path from production CLI defaults.
- Schema profiles must define aliases per consumer or operation. Do not infer
  one global active alias from physical column presence when holdings and
  transactions can use different columns; cover mixed-layout regressions.
