# Transaction assignment

W03 replaces a payee and category splits on exact existing transaction IDs.
It runs only against newly invented, marked model-48 disposable stores using
the TestFlight 2026.37.1 build 449 model. Live capability
`write.assign-payee-categories` remains blocked in the compatibility register.

## Contract

Use the same explicit envelope as the
[W01 creation request](TRANSACTION-CREATION.md#request-example). Give the plan
and source event new IDs, and replace its `operation` with:

```json
{
  "operation_id": "assign-1",
  "kind": "assign_payee_categories",
  "transaction_entity": "WithdrawTransaction",
  "transaction_gid": "EXACT_EXISTING_GID",
  "account_gid": "EXACT_ACCOUNT_GID",
  "amount": "-4",
  "expected_assignments": {
    "payee_gid": "OLD_PAYEE_GID",
    "category_splits": [{"category_gid": "OLD_CATEGORY_GID", "amount": "-4"}]
  },
  "target": {
    "payee_gid": "NEW_PAYEE_GID",
    "category_splits": [{"category_gid": "NEW_CATEGORY_GID", "amount": "-4"}]
  },
  "replacement_mode": "replace"
}
```

`payee_gid` may be null; `category_splits` may be empty. Every nonempty split
list must contain distinct categories, sorted by GID, whose signed amounts sum
to the unchanged transaction amount. The request must change at least one
relationship. The target states the complete final relationship set; omitted
old assignments are deliberately removed. This is transaction-only: it does
not rename or merge payees or change their other transactions.

```bash
moneywiz transaction assign --request /private/path/request.json \
  --plan /private/path/assignment-plan.json
moneywiz write validate --plan /private/path/assignment-plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/assignment-plan.json --owner OWNER_LOCAL_ID \
  --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/assignment-plan.json --owner OWNER_LOCAL_ID
```

The Python builder opens no store. The native host independently checks the
reviewed plan digest, exact account/owner/currency/amount, expected old
relationships and target ownership. Only ordinary unreconciled income,
expense and linked refund transactions in the disposable CashAccount fixture
are supported. Category type must match income or expense; existing budget,
scheduled or history links refuse replacement. Transfers, adjustments,
investment and special records remain blocked.

The native host preflights every operation, saves the coherent unit once and
reads it back through a new context. A payee-only change preserves category
assignment objects. Changed category splits replace obsolete assignment
objects deliberately. Account balance, transaction identity, unrelated fields
and relationships must remain unchanged. Recovery classifies exact old state
as `retry_safe`, exact final state as `noop`, and contradictory or mixed state
as `unknown`; unknown outcomes are never replayed.

## Validation and acceptance

`tests/cli/test_transaction_assign.py` checks the closed plan and receipt
contract. `tests/cli/test_native_transaction_assign.py` exercises the native
host on invented stores, including replacement, add/remove, payee-only,
category-only, stale/foreign references, atomic rollback and interruption
recovery. Installed bundle validation must use `MONEYWIZ_TEST_BUNDLE_PATH`.
MoneyWiz reopen/history and remote synchronization acceptance require a
separate authorized session before live capability promotion.
