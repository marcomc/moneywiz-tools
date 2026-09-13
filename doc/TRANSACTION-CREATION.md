# Transaction creation

## Capability boundary

W01 adds typed income, expense and refund creation to the version-2 writer.
Experiments are restricted to invented disposable stores using the exact
`moneywiz-2026-model-48` profile. The live capability register keeps
`write.create-income`, `write.create-expense` and `write.create-refund` blocked.
The initial disposable account variant is `CashAccount`. Other account classes
require their own evidence before admission. Linked same-account withdrawal
refunds are the W01 refund variant; unlinked refunds, card-specific reversals
and cross-account/FX refunds remain excluded.

W02 editing, W03 post-create assignment/split mutation, W04 reconciliation and
P2/P3 variants remain disabled.

The Python client and production native host independently require Core Data
store metadata `MoneyWizToolsDisposableFixture` equal to `W01-v1`. The fixture
builder sets it only when constructing a new invented store. A plan cannot
self-declare a store disposable, and there is no product command to mark an
existing database. This marker is an experiment boundary, not evidence that
MoneyWiz accepted the resulting objects.

## Plan and apply

```bash
moneywiz transaction create --request /private/path/request.json \
  --plan /private/path/plan.json
moneywiz write validate --plan /private/path/plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/plan.json --owner OWNER_LOCAL_ID \
  --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/plan.json --owner OWNER_LOCAL_ID
```

Planning consumes explicit JSON and opens no store. The builder normalizes
Decimal request amounts; saved plans require canonical text. Both `created_at`
and `occurred_at` require whole seconds, with no fractional timestamp. Applying requires the exact
reviewed digest and selected store/app/model identity. Keep MoneyWiz closed
through apply and persisted verification. The writer lock serializes cooperating
writers; it cannot stop an external launch of MoneyWiz.

One W01 plan represents one source event and creates one transaction. Its
category assignments, tag relationships, supported refund link and account
balance change are part of the same atomic save. Existing payee plans may still
contain multiple operations.

## Typed fields

| Input | Contract |
| --- | --- |
| Account and owner | Explicit account GID and store-local owner URI bound to the envelope |
| Currency | Explicit uppercase three-letter account currency; no FX conversion |
| Amount | Canonical Decimal text; income/refund positive, expense negative; zero refused |
| Date and timezone | ISO-8601 whole-second instant with offset and matching IANA timezone |
| Source event | Explicit stable event identity; evidence references and source interval |
| Payee | Existing payee GID or null; owner must match |
| Categories | Ordered category GID/amount entries or an empty list; signed amounts sum exactly to the transaction |
| Tags | Sorted unique existing tag GIDs; owner must match |
| Note | Trimmed nonblank text or null |
| Refund | Explicit original withdrawal entity/GID; other kinds require null |
| Expected balance | Native cached `Account.ballance` before mutation; delta equals the signed amount |

Unknown fields, unsupported kinds and mismatched per-operation capabilities are
errors. The schemas do not expose arbitrary Core Data attributes, flag edits or
entity conversion. Decimal values must round-trip through native Double without
changing their decimal value.

Native initialization sets `amount` and `originalAmount` to the same signed
value, `originalCurrency` to the account currency, and `originalExchangeRate`
to `1`. `date` comes from `occurred_at`; `objectCreationDate` comes from
`created_at`. Other transaction attributes retain compiled-model defaults,
including status `1`, flags `0`, unreconciled and non-void state. Category
assignment order is zero-based. Persisted verification checks these fields,
all requested relationships, and unchanged fields on existing objects.

## Request example

Replace the fixture identities with those emitted by the disposable fixture
builder. Optional relationships are explicit nulls or empty lists; they cannot
be omitted. This example plans an uncategorized income:

```json
{
  "plan_id": "synthetic-income-1",
  "profile_id": "moneywiz-2026-model-48",
  "model_checksum": "+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=",
  "store_identity": {"store_uuid": "FIXTURE_STORE_UUID"},
  "owner_uri": "x-coredata://FIXTURE_STORE_UUID/User/p1",
  "app_identity": {
    "bundle_id": "com.moneywiz.personalfinance",
    "version": "2026.37.1",
    "path": "/Applications/MoneyWiz.app",
    "model_path": "/Applications/MoneyWiz.app/Contents/Resources/MoneyWizDataModel.momd/MoneyWizDataModel 48.mom"
  },
  "created_at": "2026-09-13T10:00:00Z",
  "timezone": "UTC",
  "source_interval": {
    "start": "2026-09-13T00:00:00Z",
    "end": "2026-09-14T00:00:00Z"
  },
  "source_evidence_refs": ["synthetic://income-1"],
  "source_event_id": "synthetic-income-1",
  "expected_account_gid": "w01-account",
  "expected_cached_account_balance": "0",
  "currency_unit": "EUR",
  "operation": {
    "operation_id": "create-1",
    "kind": "create_income",
    "account_gid": "w01-account",
    "amount": "12.5",
    "occurred_at": "2026-09-13T09:00:00Z",
    "payee_gid": null,
    "category_splits": [],
    "tag_gids": [],
    "note": "Invented fixture income",
    "refund_reference": null
  }
}
```

Expense uses `create_expense` with a negative amount. Refund uses `create_refund`
with a positive amount and `refund_reference` containing
`original_transaction_entity: "WithdrawTransaction"` and the exact
`original_transaction_gid`. Income categories must have native type `2`;
expense/refund categories must have type `1`. Refund totals cannot exceed the
referenced withdrawal. FX, investment, linked multi-withdrawal refunds and
unexpected existing refund graphs are rejected.

## Source identity and recovery

The transaction GID is the uppercase UUID-shaped encoding of the first 16 bytes
of SHA-256 over canonical JSON containing only `store_uuid`, `owner_uri` and
`source_event_id`. Both Python and Swift recompute it. Changing the plan ID,
operation ID or transaction kind cannot select a different creation identity for
that source event.

The shared journal flushes the prepared plan and consistent snapshot before
mutation. Recovery inspects persisted identities and postconditions before
classifying an interruption; it never treats lost stdout as rollback or restores
an old database automatically. See [Writer Recovery](WRITER-RECOVERY.md) for
private paths, source reservations and retention.

## Acceptance evidence

The target installed bundle inspected during implementation is MoneyWiz
TestFlight `2026.37.1` build `449`, model 48. The production host enforces this
exact build for disposable W01 execution. Compiled-model inspection and
invented Core Data stores establish only local schema and persistence evidence.
Application initialization semantics, reopening/history consumption and remote
sync require direct acceptance in a separately authorized session. No live
financial database is used by this implementation workflow.

The [W01 task ledger](../TODO.md#p1-w01-transaction-creation) separates
implementation, required validation, independent review and future application
acceptance. No capability is promoted by this document.

## Reproducing validation

The legacy CLI tests expect an ignored fixture file. On a clean checkout,
generate it entirely from checked-in DDL and invented rows:

```bash
python tests/build_synthetic_legacy_fixture.py
uv run --frozen --with pytest pytest -q tests/cli
```

The builder refuses to overwrite an existing file. It does not discover, read,
copy or sanitize a financial database. Its deliberately invalid transfer tests
partial-read diagnostics. W01 native tests create separate fresh Core Data
stores from the installed current model, with `MONEYWIZ_TEST_MODEL_PATH` as an
explicit override; the legacy fixture is never sent to the native writer.

The unchanged API pin parses W01 transaction rows but reports P0 snapshots as
partial on fresh model-48 stores: its tag-table classifier does not recognize
the model's unrelated `Z_24TAGS` and `Z_32TAGS` shapes. The native writer verifies
tags through Core Data relationships. Do not interpret that native result as a
complete P0 snapshot; dependent reconciliation planning remains blocked by the
partial-read diagnostic. Resolving the API classifier needs a separate reviewed
pin update.
