# Transaction transfer replacement

W07 replaces one imported withdrawal and, when explicitly identified, its
imported deposit with two new reciprocal native transfer legs. The source and
destination must be active accounts of the same owner. Cash, cheque, savings,
credit-card, loan, investment and forex accounts are supported. The request binds
both accounts and cached balances, both currencies, each old row's GID and
numeric ID, actual amounts and dates, a directional exchange rate, and a stable
source-event ID. Send and Receive dates may differ. Live admission accepts a
supported MoneyWiz bundle at build 449 or newer when its model and canonical
store identity match; disposable test stores require the native fixture marker.

## Plan and apply

~~~sh
moneywiz transaction transfer --request /private/path/request.json \
  --plan /private/path/plan.json
moneywiz write validate --plan /private/path/plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/plan.json --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/plan.json
~~~

Keep requests and plans private: they contain account and transaction details.
The request uses the common version-2 envelope plus `destination_account` with
`account_gid`, `currency_unit`, and `expected_cached_balance`. Live plans also
require `balance_mode: "ledger"`; account caches are preserved. Its single
`operation` has `kind: "replace_import_with_transfer"`, `operation_id`,
`source_old`, optional `destination_old` (`null` when absent), `send_at`,
`receive_at`, `sender_amount`, `recipient_amount`, `exchange_rate`, and
`fee_amount`. Each old row binds its entity, GID, numeric ID, account, amount,
currency, timestamp, native status and flags, reconciliation state, note,
description, payee GID, sorted tag GIDs and category-assignment URIs. The
source row must be a withdrawal; an identified destination row must be a
deposit. Amounts and the directional rate must agree within one cent.

Only zero-fee conversions are admitted. Both old rows must be in the observed
cleared native state, nonvoid and free of investment or prior FX metadata.
Existing business links outside the reviewed pair,
ambiguous destination candidates, stale rows, changed balances and duplicate
GIDs are rejected before mutation. The host deletes the old row or rows and
their category assignments, creates two linked transfer rows, and saves the
graph once. Live balances derive from the ledger. On marked disposable fixtures,
the source cached balance stays the same; a source-only conversion adds the
recipient amount to the destination cached balance.

The receipt reports both new GIDs and numeric IDs, old numeric IDs, reciprocal
link verification and both resulting balances. A fresh Core Data context
checks the persisted pair. Recovery distinguishes unchanged inputs from an
already applied pair and refuses partial or ambiguous states. Notes, tags,
payees and reconciliation values from identified old rows are carried over;
without an old recipient row, recipient metadata starts empty. See
[Writer Recovery](WRITER-RECOVERY.md) for journal handling.

The `write.replace-import-with-transfer` capability is enabled for reviewed
MoneyWiz builds at 449 or newer when the supported bundle, exact model, and
canonical store identity match. Bundle channel does not determine admission.
Marked disposable stores remain supported for tests. Nonzero fees need native
reference evidence for their currency and amount rules. Live use requires
MoneyWiz reopen and sync acceptance.

## Change the recipient account of a linked transfer pair (W10)

W10 updates the existing `TransferWithdrawTransaction.recipientAccount` and
`TransferDepositTransaction.account` relationships in one Core Data save. It
preserves both GIDs and durable IDs, amounts, currencies, dates, fees, notes,
flags, payees, tags, assignments and reciprocal transaction links. The source,
previous destination and new destination must be distinct accounts owned by the
same user. The new destination must use the existing recipient leg's currency.

Build a request with the shared version-2 envelope, `previous_destination_account`,
`destination_account`, and one `operation` with kind
`reassign_transfer_recipient`. Bind both complete transfer leg snapshots under
`expected_pair.sender` and `expected_pair.recipient`, including native entity,
GID, numeric ID, account, peer identities, amounts, currencies, exchange rate,
date/timezone, status, flags, reconciliation state and metadata. Account guards
include GID, currency and expected cached balance. Use `balance_mode: "ledger"`
for live accounts; disposable fixtures use cache-delta checks.

~~~sh
moneywiz transaction reassign-transfer-recipient --request /private/path/request.json \
  --plan /private/path/plan.json
moneywiz write validate --plan /private/path/plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/plan.json --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/plan.json
~~~

The native host checks both snapshots and all three accounts before mutation,
saves both account relationship changes atomically, and independently reads the
persisted pair back. Recovery reports retry-safe before save and a no-op after a
completed reassignment; partial pairs and stale account or transaction state are
refused. W10 capability is `write.reassign-transfer-recipient`. Live admission
requires a supported MoneyWiz bundle at build 449 or newer with exact app/model/
store identity; disposable stores must carry the W01 fixture marker.
