# Choose the Pinned Dependency and Bundle Mechanism

**Type:** Research

**Status:** Closed

**Blocks:** Reproducible build migration

## Question

How should the Make build resolve an immutable revision of the compatibility
fork, record it in version control, and package it into a self-contained app
bundle without requiring a local nested checkout at build or runtime?

## Resolution

`pyproject.toml` pins `moneywiz-api` to the immutable commit
`3020435cef7b9ae6b788ac6e779f54ac146e7489`, and `uv.lock` resolves that same
commit. The bundle build uses `uv export --frozen` and `uv pip install` to
install the locked dependency graph into
`Contents/Resources/runtime/python/venv` alongside the bundled Python runtime.
No local checkout is required, consumed, or bundled.
