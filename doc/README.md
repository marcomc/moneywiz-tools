# MoneyWiz Database — Developer Docs

This folder documents the MoneyWiz SQLite schema (as observed from the app’s local database) and provides guidance for extending the `moneywiz-api` library and the `moneywiz.sh` CLI to support richer read/write workflows.

Contents

- `DB-SCHEMA.md`: Human-readable schema and key tables (with regeneration instructions).
- `ER-DIAGRAM.md`: Entity relationships for the primary tables used by moneywiz-api.
- `EXTENSIONS.md`: Roadmap for implementing read/write operations across entities with data constraints, pitfalls, and CLI design.
- `SYNCOBJECT.md`: Deep-dive into ZSYNCOBJECT (Core Data SyncObject) and entity typing.
- `CONCEPTS.md`: Core concepts (timestamps, signs, FX fields, relationships) useful for extending the API.
- `REPO-INTEGRATION.md`: How to integrate `moneywiz-api` (submodule/subtree/package) — documented options, not applied by default.

Quick regenerate (from repo root)

- Markdown schema for any DB file:
  - `PYTHONPATH=moneywiz-api/src .venv/bin/python scripts/introspect_db.py --db tests/test_db.sqlite --format md > doc/DB-SCHEMA.md`
- JSON schema dump (machine-readable):
  - `PYTHONPATH=moneywiz-api/src .venv/bin/python scripts/introspect_db.py --db tests/test_db.sqlite --format json > doc/schema.json`

Note on provenance

- MoneyWiz stores most business entities in a single Core Data table `ZSYNCOBJECT`, keyed by entity id (`Z_ENT`) with the human-readable name in `Z_PRIMARYKEY` (`Z_NAME`). Auxiliary tables model many-to-many relationships (e.g., categories, tags) and specialized links (refund mappings).
