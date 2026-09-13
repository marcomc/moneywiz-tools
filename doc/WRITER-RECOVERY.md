# Writer recovery

## Scope

P1F provides the version-2 shared writer infrastructure. Its narrow
`reassign_payee` bridge uses the existing payee relationship operation to exercise
preflight, atomic persistence and recovery. W01–W04 transaction creation, editing,
category assignment and reconciliation remain disabled. Existing version-1
commands retain their interface and capability checks.

This phase is validated with synthetic/disposable stores. Local persisted
read-back, MoneyWiz application acceptance and remote sync are separate evidence.
No P1 operation is cleared by these tests.

## Review and apply

```bash
moneywiz write validate --plan /private/path/plan.json
moneywiz write apply --plan /private/path/plan.json
moneywiz --db /private/path/store.sqlite write apply \
  --plan /private/path/plan.json --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/store.sqlite write recover \
  --plan /private/path/plan.json
```

Validation and apply without `--apply` only inspect the plan. Mutation requires
both explicit apply and the digest of the reviewed content. Editing any plan
field changes its digest. The digest proves integrity, not user authorization.
Keep plans and output private; they contain source references and financial state.

The version-2 envelope binds contract and operation schema versions, plan and
source-event identity, store UUID, store-local owner URI, exact app/model identity,
source interval/timezone, evidence references, account guards and typed operations.
Amounts use Decimal strings. Unknown kinds and capabilities fail closed; the
envelope is not a generic entity/key-value write API. The
`expected_cached_account_balance` guard binds native `Account.ballance`;
`currency_unit` matches `Account.currencyName`. The cached value is not an
independently verified bank balance. Decimal strings must round-trip through
native Double without changing their decimal value.

Preflight resolves every target and guard before mutation. One coherent unit uses
one Core Data save. Read-back uses a new context and returns durable transaction
identities. Keep MoneyWiz closed through preparation, execution and verification.
Cooperating writer serialization does not prevent an external MoneyWiz relaunch.

## Interrupted execution

A flushed prepared journal and consistent SQLite backup precede mutation. A
missing response or receipt does not imply rollback. Recovery inspects persisted
identities and postconditions before classifying the outcome:

| Persisted state | Recovery action |
| --- | --- |
| Every operation matches its postcondition | Return a verified no-op; do not repeat the save |
| Every operation still matches the expected preimage | Report safe-to-retry evidence; explicit apply remains required |
| Mixed, stale, missing or contradictory state | Preserve unresolved evidence and refuse replay |

Do not use a GUI write to bypass an unknown outcome. Recovery never automatically
restores a SQLite backup or edits persistent-history/CloudKit records. After sync,
an old backup can conflict with newer state; corrective work needs its own scope.

## Discovery and retention

```bash
moneywiz write locations
moneywiz write journal
moneywiz write cleanup
moneywiz write cleanup --apply
```

Discovery reports effective journal, snapshot and private report locations with
configuration provenance. The machine journal is local and independent of cloud
availability. Configure private report locations to the canonical Obsidian vault;
generic repository files contain no personal vault or account paths.

On macOS the default journal root is
`~/Library/Application Support/MoneyWiz Tools`; `MONEYWIZ_JOURNAL_DIR` overrides
it. `MONEYWIZ_REPORT_DIR`, or `obsidian_report_dir` in the journal root's private
`config.json`, selects the report directory. Without configuration, the report
location is explicitly unconfigured. Discovery does not create directories or
write reports. Journals and snapshots use `0700` directories and `0600` files.

Store locks always reside in the default data root's `locks` directory and are
keyed by store device/inode, even with a custom journal location. Native direct
calls and the Python client share that lock. The client holds it from snapshot
preparation through durable result persistence; cleanup uses the same lock order.

Verified entries become eligible 90 days after successful final verification.
Prepared, active, unknown and failed/unresolved entries remain until resolved.
Evidence referenced by unresolved entries is retained. Obsidian reports remain
indefinitely and are excluded from automatic pruning.

P1F retains recovery snapshots indefinitely. Journal expiry alone never deletes
a snapshot. Compact source-event reservations remain to reject conflicting event
reuse after journal expiry. A later snapshot-pruning policy requires a separate
implementation; cleanup currently reclaims journal payloads only.

Cleanup first lists eligible entries, reasons and estimated bytes. Explicit apply
rechecks eligibility and writer activity while holding the cleanup lock and
writes a minimal cleanup receipt without deleted financial payloads. Missing or
malformed recovery state is retained. A
retention boundary does not prove financial correctness or application acceptance.

## Disposable validation

Native regression tests use synthetic Core Data models and temporary SQLite
stores, including process termination immediately before and after save. The
opt-in installed-bundle test builds a new empty store from the explicitly supplied
MoneyWiz model, then verifies apply, persisted IDs, recovery and repeated no-op.
It never copies or discovers a live financial store.

```bash
MONEYWIZ_TEST_BUNDLE_PATH="/path/to/MoneyWiz Tools.app" \
MONEYWIZ_TEST_MODEL_PATH="/path/to/compiled-model.mom" \
MONEYWIZ_TEST_APP_PATH="/path/to/MoneyWiz.app" \
  uv run --frozen pytest -q tests/cli/test_installed_bundle_smoke.py
```

The writer test requires MoneyWiz closed; model-checksum/read tests need no live
application session. Run against a relocated bundle after removing a disposable
build checkout to establish independence from development paths.
