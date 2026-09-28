# Adjust Balance: W05 reference contract

W05 creates a `ReconcileTransaction` for an explicit target balance. It is
separate from W04, which changes an existing transaction's `reconciled` flag.

## Verified variant

MoneyWiz TestFlight 2026.37.1 (build 449), model 48, created one native
adjustment in a GBP investment account without holdings. Private before/after
evidence is retained outside this repository. The account's total equals its
opening balance plus the amounts of its `ReconcileTransaction` history, rounded
to pence. Its cached `ballance` remained zero and its opening balance did not
change. No `InvestmentAccountTotalValue` row was created.

The new row has `amount = target - prior`, `reconcileAmount = target`,
`reconcileNumberOfShares = 0`, `numberOfShares = 0`, `originalAmount = 0`,
`status = 2`, `flags = 0`, `reconciled = false`, `desc = "New balance"`, an empty
note, and an account relationship. It has no holding, category, payee or tag.

The writer supports only this `investment_total` variant in GBP. It requires
the exact app, model, store, owner, account, prior balance and date in the
reviewed plan; refuses holdings, valuation history and unsupported transaction
history; saves one row; then reads it back in a fresh context. A deterministic
GID prevents a lost response from creating a duplicate. A matching target is a
no-op. Dates before the latest account transaction are rejected.

## Capability boundary

The native writer was exercised on a private copy of the observed database:
the inserted row matched the app-created row's relevant fields, the balance
equation held, and recovery found the same durable row. This validates the
stored shape and local recovery. The live capability remains blocked until an
authorized tool-written row is reopened in MoneyWiz and sync acceptance is
observed. Ordinary account balance, investment cash and holding quantity have
separate native semantics and no W05 writer capability here.
