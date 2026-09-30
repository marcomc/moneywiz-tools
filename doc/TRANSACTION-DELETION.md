# Supported transaction deletion

## Scope and status

W06 deletes explicitly selected `DepositTransaction`, `WithdrawTransaction`,
`RefundTransaction`, `TransferWithdrawTransaction`, `TransferDepositTransaction`,
`ReconcileTransaction`, `InvestmentBuyTransaction` and
`InvestmentSellTransaction` records through Core Data.

The capability `write.delete-supported-transactions` is enabled for the reviewed
Setapp MoneyWiz 2026.37.1 build 449/model-48 runtime and marked disposable stores.
Authorized fictional live trials verified ordinary records, refund-only and
complete withdrawal/refund groups, reciprocal transfers, categorized expenses,
investment cash, stock quantity, Buy/Sell, dividends and fees. Installed Python
client acceptance also verified journaled apply, replay and recovery. App
read-back and operation-specific CloudKit export/deletion evidence confirmed
cleanup and restoration; second-device acceptance was not performed for these
temporary rows. The existing `transaction delete-adjustment` contract is unchanged.

The seven reviewed account types are supported, with GBP, EUR, USD and CAD.
Deletion preserves account caches on native stores and projects the resulting
ordinary balance, investment cash and stock/Forex quantities from native history.

## Plan, inspect and apply

Select exact transaction GIDs. Repeat `--target` for each record in the coherent
deletion unit. Planning reads the selected store through the installed native
model without modifying it or preparing a recovery journal.

~~~sh
moneywiz --db /path/to/MoneyWiz.sqlite transaction delete \
  --app /path/to/MoneyWiz.app \
  --target fictional-expense-gid \
  --target fictional-refund-gid \
  --reason 'Remove the identified test transactions' \
  --evidence-note 'synthetic://approved-deletion-trial' \
  --plan /private/path/deletion-plan.json

moneywiz write validate --plan /private/path/deletion-plan.json
~~~

The immutable plan shows target descriptions, amounts and signed quantity
effects; owned dependencies; retained object fingerprints; and prior/final
account balances, caches and holding quantities. It binds the app, model, store
UUID, owner and every native object URI.

Keep MoneyWiz closed during application and recovery. Apply the reviewed digest
through the existing writer interface:

~~~sh
moneywiz --db /path/to/MoneyWiz.sqlite write apply \
  --app /path/to/MoneyWiz.app \
  --plan /private/path/deletion-plan.json \
  --reviewed-digest REVIEWED_SHA256 --apply

moneywiz --db /path/to/MoneyWiz.sqlite write recover \
  --app /path/to/MoneyWiz.app \
  --plan /private/path/deletion-plan.json
~~~

Use `--owner` and `--model` when an explicit selection is needed. The installed
CLI regression exercises this complete planning, validation, application,
journal, replay and recovery workflow.

## Dependency rules

| Relationship | Required effect |
| --- | --- |
| Reciprocal transfer legs | Both exact peer GIDs must be selected; both account projections are verified |
| Withdrawal with attached refunds | Every attached refund must be explicitly selected; incomplete selections are refused |
| Refund selected alone | Remove its links; preserve the original withdrawals and other refunds |
| Category assignments, transaction budget links, images | Delete the exact owned cascade closure; refuse an unsupported cascade or shared scheduled/history assignment |
| Payees, categories, tags, budgets | Retain the objects; verify only the projected removal of deleted inverse references |
| Investment holding | Retain identity, ownership and metadata; derive the remaining cash and quantity |

Native model-48 rules cascade owned assignments and refund links, while transfer
peers and holdings use nullification. The writer explicitly closes transfer and
withdrawal/refund groups to prevent partial pairs or stranded refunds. It does
not infer authorization from matching amounts or dates.

The native app deletes a withdrawal together with its attached refunds. The
writer requires naming the whole group explicitly. Deleting only a refund keeps
the withdrawal and its other refunds.

## Atomicity, stale state and recovery

Python and Swift independently validate the exact plan shape, scalar types,
normalized identity strings, canonical decimals, URI ownership and postcondition.
The native host rechecks the current complete inventory before deleting anything.
A read-only preflight precedes writable store opening, preventing rejected plans
from initializing persistent-history tables.

The entire deletion closure is resolved before mutation. One Core Data save
removes the reviewed records, and a fresh context independently verifies their
absence, unchanged retained attributes, projected inverse relationships and
financial state. Successful receipts contain the complete deleted URI list and
verified final account/holding state.

Retained holding fingerprints include model-48 manual historical prices with
native date keys and finite numeric values. Their archive bytes remain unchanged;
a later price change invalidates the reviewed inventory.

| Observed state | Recovery result |
| --- | --- |
| Complete original closure and retained preconditions match | `retry_safe` |
| All reviewed deleted objects are absent and exact final state matches | `noop` |
| Mixed presence, replaced GID/URI, changed history or invalid final state | Refusal or `unknown`; no automatic replay |

The Python client requires `retry_safe` before preparing a new deletion journal.
Existing verified executions must recover as `noop`. Crash tests cover both
before-save and after-save boundaries.

## Explicit boundaries

- Arbitrary `SyncObject`, exchange and budget-transfer deletion is unsupported.
- Void, unsupported native status/flags, scheduled links and malformed ownership
  or dependency relationships are refused with a specific reason.
- Deleting a Buy or quantity adjustment must leave a nonnegative derived holding
  quantity; deleting a Sell restores its signed units.
- The operation retains holdings, including those left with zero units.
- TestFlight writes require the persistent disposable-store marker. Live Setapp
  admission independently checks the reviewed edition, build, model and store.
- Native history/sync export and second-device acceptance are separate evidence;
  a local deletion does not alone prove remote synchronization.
