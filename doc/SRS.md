## Software Requirements Specification (SRS)

### 1. Purpose
Provide a read- and write-capable toolkit to inspect and manage MoneyWiz SQLite databases from the command line, powered by a Python API (the “API”) and a unifying shell script (`moneywiz.sh`). The toolkit should mirror the most important MoneyWiz features for accounts, transactions, categories, payees, tags, and investment holdings — safely and predictably.

### 2. Scope
- Read: list and query users, accounts, categories, payees, tags, holdings, and transactions; inspect single records; generate schema docs and summaries.
- Write: create and update core entities and relationships (category splits, tags, refund links). Start with a dry-run layer and controlled opt-in applies.
- Documentation: developer docs for schema, concepts, SyncObject, field mappings; user docs for all CLI commands/options.

### 3. Stakeholders
- End users managing their MoneyWiz data locally.
- Developers extending the API and CLI.

### 4. Definitions
- API: `moneywiz-api` Python package in this repo.
- SyncObject: row in `ZSYNCOBJECT`, typed via `Z_ENT` → `Z_PRIMARYKEY.Z_NAME`.
- Dry-run: simulate planned SQL changes without applying.

### 5. Functional Requirements
- FR1: List/read commands for users, accounts, categories, payees, tags, holdings, transactions, and records.
- FR2: Introspection: full schema dump (md/json), ER diagram, summary counts.
- FR3: Transaction relationships: category splits, tags, refund → withdraw links (read).
- FR4: Write scaffolding: insert/update/delete SyncObjects, assign categories/tags, link refund (dry-run + apply).
- FR5: CLI: `moneywiz.sh` provides a coherent interface with safe defaults, global `--db`, and per-command options.
- FR6: Documentation: README.md (user), doc/ (developer) updated with any new feature.

### 6. Non-Functional Requirements
- Safety: Default to dry-run; encourage using a DB copy for writes.
- Reliability: Use transactions for multi-table writes; tolerate data quirks on reads.
- Portability: macOS default path; custom DB via `--db`.
- Performance: Operate on local SQLite; acceptable for interactive usage.

### 7. Constraints
- No proprietary MoneyWiz internals; rely on on-disk SQLite schema.
- Network-restricted environments should still allow reading local DBs.

### 8. Assumptions
- DB structure matches MoneyWiz schema as discovered via `Z_PRIMARYKEY`/`ZSYNCOBJECT`.
- Users possess local DB file.

### 9. Acceptance Criteria
- CLI successfully lists and inspects all supported entities from a known test DB.
- SQL preview shows correct statements for representative create/update/link operations.
- Docs are consistent, actionable, and regenerated from actual DB when needed.

