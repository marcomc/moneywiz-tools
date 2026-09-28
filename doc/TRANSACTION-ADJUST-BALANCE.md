# Adjust Balance: W05 reference contract

W05 creates a native `ReconcileTransaction` for an explicit target balance.
It is separate from W04, which changes an existing transaction's `reconciled`
flag. This page records phase preparation; no W05 write capability is enabled.

## Evidence available

- The installed MoneyWiz app is TestFlight 2026.37.1 (build 449), using compiled
  model 48. `ReconcileTransaction` inherits `Transaction` and has optional
  `reconcileAmount` and `reconcileNumberOfShares` numeric attributes, plus the
  usual `amount`, `date`, account and holding relationships. Model defaults do
  not establish which values MoneyWiz writes for each adjustment variant.
- The upstream API at `19c1a1c` calls both reconciliation fields a *new
  balance* and requires at least one of them. This describes the read model,
  not native creation rules or the pinned Tools dependency.
- [MoneyWiz 2026 release notes](https://apps.apple.com/us/app/moneywiz-2026-personal-finance/id1511185140)
  report that Adjust Balance can use a past date. The older MoneyWiz 3 guide's
  today-only restriction must not be carried into this build without testing.

## Reference evidence required before a writer

Capture an app-created adjustment in an isolated, invented store and compare
before/after native objects for each supported unit: ordinary account currency,
investment cash, investment total value and holding quantity. Record the
requested target, prior balance, resulting delta, date/time, account/holding
relationships, all `ReconcileTransaction` numeric fields, account cache and
history changes. Exercise a higher target, lower target and an already matching
target. Test a supported historical date and its effect on later balances.

| Unit to verify | Decisive native comparison |
| --- | --- |
| Ordinary account currency | `amount`, `reconcileAmount`, account cache and history |
| Investment cash | Cash balance, account cache and any valuation history |
| Investment total value | Total value history versus cash and holding values |
| Holding quantity | `reconcileNumberOfShares`, holding link and share quantity |

Only a verified variant gets a typed plan and native implementation. The plan
must bind app/model/store/owner identity, account and unit, target and expected
prior balance, source event, date/timezone and exact calculated delta. The
writer must preflight the old state, preserve opening balance and unrelated
history, save once, read back the new object and recover a lost response without
creating a duplicate. Keep live capability blocked until app reopen and sync
acceptance are separately observed.
