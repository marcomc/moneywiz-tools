# Adjust Balance: W05 reference contract

W05 creates a `ReconcileTransaction` for an explicit target balance. It is
separate from W04, which changes an existing transaction's `reconciled` flag.

## Verified variant

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

The writer supports only this `investment_total` variant in GBP. Live execution
is admitted for Setapp MoneyWiz 2026.37.1 build 449; the TestFlight build remains
available for marked disposable fixtures. It requires
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
verified for this variant. Ordinary account balance, investment cash and holding
quantity have separate native semantics and no W05 writer capability here.

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
