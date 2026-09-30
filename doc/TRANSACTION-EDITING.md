# Transaction editing

## Capability and supported variants

W02 edits exact existing transaction entity/GID pairs through the version-2
native writer. The model-48 capability is enabled for authorized live execution
on Setapp MoneyWiz 2026.37.1 build 449, with exact app and store identity checks.
TestFlight regression stores require the disposable metadata marker.

Supported entities are `DepositTransaction`, `WithdrawTransaction` and linked
`RefundTransaction` in all seven [supported account types](TRANSACTION-CREATION.md),
including rows created by W01. The entity, GID, object identity, import/source
metadata, owner and account stay unchanged. Reconciled records fail closed;
`correction_mode` must explicitly be `reject_reconciled`. No alternative
correction mode has independent acceptance evidence.

| Logical field | Native fields | Contract |
| --- | --- | --- |
| `amount` | `amount`, `originalAmount` | Signed nonzero canonical Decimal; same-currency pair changes together; no category assignments or budget links |
| `occurred_at` | `date` | Whole-second ISO-8601 instant; offset matches the explicit IANA timezone |
| `note` | `notes` | Trimmed nonblank string or null |
| `description` | `desc` | Trimmed nonblank string or null |
| `checkbook_number` | `checkbookNumber` | Trimmed nonblank string or null |

Model inspection confirms the text attributes are nullable strings. W01
fixtures establish the ordinary amount/original-amount/currency invariant.
These are local schema and persistence semantics; they are not proof of
MoneyWiz application processing or remote synchronization.

Every changed field requires its exact prior value, including explicit null.
Requests cannot contain unchanged fields, arbitrary native attributes, currency
or exchange-rate changes. Live amount edits preserve the account cache and
reporting exchange rate while changing the ledger. Text and date edits preserve existing category, tag,
payee and refund relationships. Amount edits reject category/budget assignments
because their numeric allocations require W03 ownership. They do not rescale
or remove assignments implicitly.

Transfers, adjustments (`ReconcileTransaction`), scheduled transactions,
investment variants, unknown entities/fields, ownership changes and relationship
mutations are refused. W03 assignments/splits use their own
[disposable-only contract](TRANSACTION-ASSIGNMENT.md); W04 reconciliation flags
and all P2/P3 operations remain disabled. Existing v1 payee reassignment is separate.

## Request and apply

Use the same explicit envelope as the
[W01 request example](TRANSACTION-CREATION.md#request-example), replacing its
`operation` with the following and assigning a new plan ID and source event
for this correction:

```json
{
  "operation_id": "edit-fee-1",
  "kind": "edit_transaction",
  "transaction_entity": "WithdrawTransaction",
  "transaction_gid": "EXACT_EXISTING_GID",
  "account_gid": "EXACT_ACCOUNT_GID",
  "changes": {"amount": "-3.5", "note": "Corrected invented fee"},
  "expected_prior": {"amount": "-2.5", "note": null},
  "correction_mode": "reject_reconciled"
}
```

The envelope account/owner/currency and expected cached account balance must
match the current store. The source event identifies the correction for the
journal; it does not overwrite the transaction's original import identity.
The builder canonicalizes amount text, derives the balance delta and native
allowlist, and binds the postcondition and canonical digest. Planning opens
no database and writes an immutable mode-0600 plan when `--plan` is supplied.

```bash
moneywiz transaction edit --request /private/path/edit-request.json \
  --plan /private/path/edit-plan.json
moneywiz write validate --plan /private/path/edit-plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/edit-plan.json --owner OWNER_LOCAL_ID \
  --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/edit-plan.json --owner OWNER_LOCAL_ID
```

The CLI builds one operation per request. The validated v2 envelope can contain
multiple W02 operations with unique transaction GIDs in the same account;
it cannot mix W02 with another capability. Each operation carries its own
expected prior values. The unit's account delta is the sum of amount differences.

## Atomicity, invariants and recovery

Native preflight checks every operation before mutation. It binds exact
store/model/app identity, owner, account, currency and cached balance, and
rejects stale prior values. Linked refunds retain their original withdrawal
links and must remain within the original withdrawal amount cumulatively,
including when a plan edits both the original and refunds. Invalid or
unsupported linked graphs fail closed.

The writer saves the coherent unit once, then independently opens a fresh
context to verify persisted values and preservation of unrelated fields,
relationships and balances. Durable results identify the same transaction URI
and numeric identity. The account balance changes only by the requested delta;
transaction history-related attributes are not rewritten by W02.

The shared journal persists the plan and snapshot before mutation. Reapplying
verified evidence returns a no-op only after checking persisted state.
Interruption recovery distinguishes unchanged prior state (`retry_safe`),
verified post-state (`noop`) and contradictory/mixed state (`unknown`).
Unknown outcomes are not replayed. See [Writer Recovery](WRITER-RECOVERY.md).

## Validation and acceptance

`tests/cli/test_transaction_edit.py` covers the Python plan, CLI and receipt
contract. `tests/cli/test_native_transaction_edit.py` exercises the production
native host on fresh invented model-48 stores, including W01-created records,
refunds, field/relationship preservation, stale state, unsupported variants,
whole-plan rollback, repeated apply and interrupted execution.

Run the native suite against the built bundle using
`MONEYWIZ_TEST_BUNDLE_PATH`; the installed CLI test copies the bundle to a new
location and denies reads from its build-source tree during plan, apply and
recovery. The release pins the read-completeness API revision
`401c919c954d227a04bceb1bef57126c25721313`; its model-48 tag classifier
is covered under [W01 validation](TRANSACTION-CREATION.md#reproducing-validation).

The [W02 task ledger](../TODO.md#p1-w02-transaction-editing) separates implemented
behavior, local validation, independent review and future acceptance. This work
never reads or copies a live financial database. MoneyWiz reopen/history and
remote-client sync acceptance require a separately authorized real session;
the live capability gate remains blocked until direct evidence exists.
