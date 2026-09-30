# Adjust Balance: W05 reference contract

W05 creates a `ReconcileTransaction` for an explicit target balance. It is
separate from W04, which changes an existing transaction's `reconciled` flag.

## Investment-total variant

MoneyWiz TestFlight 2026.37.1 (build 449), model 48, created one native
adjustment in a GBP investment account without holdings. Private before/after
evidence is retained outside this repository. The account's total equals its
opening balance plus the amounts of its transaction history, rounded
to pence. Its cached `ballance` remained zero and its opening balance did not
change. No `InvestmentAccountTotalValue` row was created.

The new row has `amount = target - prior`, `reconcileAmount = target`,
`reconcileNumberOfShares = 0`, `numberOfShares = 0`, `originalAmount = 0`,
`status = 2`, `flags = 0`, `reconciled = false`, `desc = "New balance"`, an empty
note, and an account relationship. It has no holding, category, payee or tag.

The `investment_total` variant supports GBP. Live execution
is admitted for Setapp and TestFlight MoneyWiz 2026.37.1 build 449, retaining
the previously verified TestFlight path. Other compatible model-48 builds are
admitted only on marked disposable fixtures. It requires
the exact app, model, store, owner, account, prior balance and date in the
reviewed plan; refuses holdings, valuation history and unsupported transaction
history; saves one row; then reads it back in a fresh context. A deterministic
GID prevents a lost response from creating a duplicate. A matching target is a
no-op. Historical adjustment timestamps must be unique for ordered balance
verification. Existing ordinary income, fees and reciprocal funding transfers
are validated and included in the running balance. When cash activity exists,
older adjustment targets are historical annotations: later backdated activity
can change their reconstructed running balances. Adjustment-only histories
retain strict target checks. Current balance, new target and delta are always
checked. New plan dates at or before the latest account transaction are rejected.

## Capability boundary

The native writer was exercised on a private copy of the observed database:
the inserted row matched the app-created row's relevant fields, the balance
equation held, and recovery found the same durable row. This validates the
stored shape and local recovery. An authorized live replacement was reopened in
MoneyWiz with the expected balance and transaction history. The app reported
iCloud up to date after completed uploads, and Core Data CloudKit metadata for
the new row recorded export with no pending upload. The model-48 capability is
verified for this variant. Additional balance units use the separate contracts below.

## Ordinary balance, investment cash and asset quantity

These operations use the reviewed Setapp MoneyWiz 2026.37.1 build 449 runtime,
model 48 and exact store identity. Other runtimes require a marked disposable
fixture. Private native references establish ordinary balance and investment
cash fields; a disposable stock-quantity probe was accepted by the app's
portfolio with unchanged cash. That probe validates app interpretation; it was
not a transaction created through the native UI.

| Kind | Capability | Balance unit | Account |
| --- | --- | --- | --- |
| `adjust_account_balance` | `write.adjust-account-balance` | `account_balance` | Cash, bank cheque, bank saving, credit card or loan |
| `adjust_investment_cash` | `write.adjust-investment-cash` | `investment_cash` | Investment |
| `adjust_asset_quantity` | `write.adjust-asset-quantity` | `asset_quantity` | Investment or Forex, existing holding |

All three require an explicit `description` and `reporting_exchange_rate`,
and bind the current cached balance without changing it. Supported account
currencies are GBP, EUR, USD and CAD, matching the installed inventory.
Cash targets and deltas have at most two decimal places; quantities have at
most eight. Account opening balances and holding attributes are preserved.

Cash and ordinary adjustments write `amount = target - prior` and
`reconcileAmount = target`, with zero share fields. Quantity adjustments write
`numberOfShares = target - prior` and `reconcileNumberOfShares = target`, with
zero cash fields and reporting rate. Quantity plans additionally bind
`holding_gid`, `holding_symbol`, `asset_type` (integer 0 for Investment or 1
for Forex) and `expected_prior_cash`. Targets cannot be negative. Existing
stock Buy/Sell and signed quantity adjustments contribute to units; Forex
deposits, adjustments and the native signed exchange legs contribute to Forex
units. Subsequent Buy/Sell use this same quantity calculation.

The planner uses `moneywiz transaction adjust-balance --request REQUEST
--plan PLAN`. The request keeps the existing version-2 envelope and supplies
one operation of the selected kind. Review the immutable plan, then use
`moneywiz write apply` with its exact reviewed digest and explicit database.
Apply and recovery independently check owner, currency, active account,
app/model/store, prior cash/units, holding identity and deterministic GID.
New rows must follow the latest account transaction. An already matching
target creates no row; a matching persisted GID replays without duplication.
One Core Data save is followed by independent read-back of the row and balance.

These capabilities do not create holdings or expand investment-total valuation
to holdings, non-GBP currencies or `InvestmentAccountTotalValue` histories.
Authorized live trials covered ordinary GBP/EUR/USD/CAD balances, investment
cash and existing stock quantity through the installed CLI, including replay
and journal recovery. MoneyWiz displayed all six rows, their target balances,
cash and quantity. CloudKit recorded each export without pending upload.
Guarded native cleanup removed all six rows; comparison with the coherent
backup confirmed original financial fields, account histories and holding
metadata, preserving the three intentionally retained TEST rows. After reopening,
MoneyWiz showed the original balances and quantity and reported iCloud Up to Date.
No second-device read-back was performed for these six temporary records.
Forex quantity is covered by native and installed disposable-store tests.

## W06 deletion of the observed adjustment

W06 deletes one exactly identified, latest `ReconcileTransaction` from the same
no-holdings GBP investment-total shape. The reviewed request binds its GID,
numeric Core Data ID, account, amount, `reconcileAmount`, timestamp including
fractional seconds, current balance, currency and deletion reason. The preview
computes the balance after removing that amount. The native host checks the
entire ordered adjustment history and rejects stale values, older targets,
dependent relationships, holdings and unsupported transaction types before one save.
It reads the target's absence and the resulting balance in a fresh context.
The client requires the exact target to exist before preparing a new journal;
recovery and replay of a prepared deletion leave an absent target unchanged.

The app-created deletion reference removed only the selected business row and
changed the account version in private before/after snapshots. A writer trial
on a separately marked copy reproduced the balance change and `noop` replay.
The `write.delete-adjust-balance-investment-total` capability is enabled for
Setapp MoneyWiz 2026.37.1 build 449 and the exact reviewed model and store.
Marked disposable TestFlight fixtures remain supported for regression tests.
