# Live Write Compatibility

## Current status

MoneyWiz Tools intentionally supports direct work with the live database, but
compatibility is defined per write path.

| Operation | Current status | Required path |
| --- | --- | --- |
| Inspect the live store | Supported | Read-only SQLite access. |
| Generic SQL mutation | Not a product capability | Do not infer iCloud compatibility from SQL success. |
| Reassign a payee to an existing destination | Verified | Bundled Core Data writer. |
| Reassign a payee and create its destination | Verified | Bundled Core Data writer. |
| W01 income, expense and linked refund | Enabled; live trial accepted | Exact reviewed Setapp app, model and store identity. |
| W02 edit, W03 assignment, W04 reconcile/unreconcile | Enabled; live trial accepted | Exact reviewed Setapp app, model and store identity. |
| W05 Adjust Balance investment total | Verified | Setapp or TestFlight MoneyWiz 2026.37.1 build 449, exact model and reviewed store identity. |
| W05 ordinary balance, investment cash and existing-asset quantity | Enabled; live trial accepted for ordinary balances, cash and stock quantity | Setapp MoneyWiz 2026.37.1 build 449; exact model, store and balance unit; Forex quantity tested on disposable stores. |
| W07 reciprocal zero-fee transfer replacement | Enabled; live trial accepted | Exact reviewed Setapp app, model and store identity. |
| W06 delete one investment-total adjustment | Enabled for authorized trials | Setapp MoneyWiz 2026.37.1 build 449, exact model and reviewed store identity. |
| W06 delete supported transactions | Enabled; live trial accepted | Exact reviewed Setapp app/model/store; explicitly selected complete dependency closure. |
| W08 investment cash events and Buy/Sell | Enabled for authorized trials | Setapp MoneyWiz 2026.37.1 build 449, exact model and reviewed store identity. |
| Merge exact-normalized duplicate payees | Enabled for authorized trials | Exact reviewed model, app, store and complete reference inventory. |
| Merge similar-name payees | Enabled for authorized trials | W09 requires one approved review-map row and the complete reference inventory. |

### Account coverage and acceptance, 30 September 2026

The installed model has seven concrete account subtypes: `CashAccount`,
`BankChequeAccount`, `BankSavingAccount`, `CreditCardAccount`, `LoanAccount`,
`InvestmentAccount` and `ForexAccount`. Ordinary creation, editing, assignment,
reconciliation and transfer replacement admit all seven. Native regression
stores exercise each subtype, preserving its metadata and account relationships.
An online-banking connection does not exclude the account from these operations.

Authorized synthetic W01–W09 trials passed on a private copy and the live Setapp
store. Each applied plan passed replay and recovery without duplication.
MoneyWiz displayed the bank rows, reciprocal FX transfer, investment cash and
Buy/Sell events, payee migration and balance adjustment. Temporary investment,
transfer and merge-reference rows were removed; three labelled bank TEST rows
were retained as requested. Original financial fields were unchanged.
CloudKit recorded export without pending upload for the trial rows; after final
cleanup MoneyWiz reported **Up to Date**. The user confirmed that the iPhone
displays the retained TEST rows and matching bank and investment balances.
Individual temporary investment and transfer identities were not checked on the
second device. Private plans, receipts and comparisons remain outside the repository.

The W05 extensions additionally passed six installed-CLI live trials: ordinary
GBP/EUR/USD/CAD balances, investment cash and existing stock quantity. App
read-back and per-record CloudKit export were verified. Exact native cleanup
restored the original financial fields, histories and holding metadata while
preserving the three retained TEST rows. Reopened balances and quantities agreed,
and iCloud reported **Up to Date**. These six temporary rows were not verified
on a second device; Forex quantity has disposable-store acceptance only.

Account coverage does not expand operation-specific semantics: W05 retains
the reviewed no-holdings investment-total contract alongside its explicit
ordinary balance, investment cash and existing-asset quantity variants. W06
additionally deletes the eight supported transaction entities with explicit
refund/transfer closure and owned dependency cleanup. W08
Buy/Sell uses an existing owned holding; the separate first-Buy operation can
create a manual investment holding atomically. New Forex holdings through
Exchange remain outside that contract. Implementation PRs have completed
independent review; runtime entries retain their operation-specific status.

The aggregate investment-total currency extension validates identifiers and
decimal precision against the reviewed app's fiat/crypto catalogs on apply
and recovery. New plans bind an explicit reporting exchange rate; original
GBP plans keep their existing contract. Native EUR and eight-decimal crypto
references were captured. Installed-client live trials verified creation,
replay, recovery and dedicated latest-adjustment deletion in both currencies.
The app displayed the exact totals and deltas, and row-specific CloudKit
metadata recorded export with no pending upload. All fictional rows and
accounts were removed; original financial fields and the three retained TEST
rows were preserved. The app reported iCloud up to date and the trial records
had no remaining CloudKit metadata. No second-device check is claimed.

The W06 extension passed native live deletion of 15 exported fictional rows
and installed Python-client deletion of three further exported rows. Coverage
includes refund-only retention, complete withdrawal/refund groups, reciprocal
transfers, categories, cash and stock quantity adjustments, Buy/Sell, dividends
and fees. Replay and recovery passed. Original ledgers, balances, quantities and
manual-price archives were restored, and the three retained TEST rows stayed
unchanged. After cleanup the app reported **Up to Date** and the exact exported
record metadata was absent. No second-device check is claimed for these rows.

No backup requirement is imposed by the command. The operator remains
responsible for deciding their own recovery posture before modifying
financial data.

## Operating rule

Use the reassignment planner first:

~~~sh
moneywiz reassign-payees-by-id --from-payee-id 1234 --show-plan
~~~

Review the result. If the plan is correct:

1. Let MoneyWiz complete any active sync.
2. Quit MoneyWiz so it releases the persistent store.
3. Run the same command with `--apply`.
4. Reopen MoneyWiz.
5. Confirm iCloud Sync reports **Up to Date**.

Keep MoneyWiz closed for the full write. Python checks the process name and the
native host checks both known MoneyWiz bundle identifiers. Either check fails
closed when inspection is unavailable or abnormal. This is a defensive
preflight, not an atomic process or store lock.

Every selected row must become either a writer operation or an explicit
already-target no-op. The planner rejects the complete selection if any row has
a missing or dangling account or owner, a missing GID, or an empty description
without a fallback payee. Its summary reconciles selected rows as
`processed = updated + noops`.
The account lookup is restricted to the verified `Account` entity family, so a
different `ZSYNCOBJECT` row cannot satisfy the ownership check accidentally.

The tool refuses ambiguous normalized payee names. Resolve or consolidate those
duplicates through the MoneyWiz GUI while
`write.merge-duplicate-payees` remains blocked. Export similar pairs with
`--fuzzy-map PATH`; W09 requires an explicitly approved row.

## Compatibility profile

The verified writer was observed with MoneyWiz 2026.32.1, builds 431 and 433, using
managed-object model `MoneyWizDataModel 48`. The runtime register calls this
`moneywiz-2026-model-48`. The current live store places payees and
transaction subclasses in Core Data storage with shared `ZSYNCOBJECT`
identity and version fields.

The exact `NSStoreModelVersionChecksumKey` for this verified model is
`+6BY8eaTke2jfAd5Bzt5D49JRMZld5o8ZoUW+4G2ElQ=`. Structural table, column,
and entity requirements remain useful diagnostics, but they do not authorize
a write without that exact checksum.

The relevant payee relationships are documented in
[Live Payee Structure](LIVE-PAYEE-STRUCTURE.md). The writer itself is
documented in [Core Data Writer](CORE-DATA-WRITER.md).

## Evidence for the version-1 reassignment path

The current host was tested against the live profile by:

- Reassigning to an existing payee.
- Reassigning while creating a new destination payee.
- Reopening MoneyWiz after each operation.
- Confirming the app consumed persistent history and iCloud export advanced.
- Confirming the app reported a successful sync.

This proves reassignment for the observed profile. It does not prove that an
arbitrary column-level SQL update, other app versions, or a duplicate merge has
the same compatibility. Exact duplicate consolidation needs its own acceptance
evidence despite using the same host.

## Historical finding

The earlier raw reassignment updated only visible relationship data. It did
not reproduce the object lifecycle expected by Core Data, persistent history,
and CloudKit. MoneyWiz later crashed when creating a transaction, which is
why the live reassignment implementation now saves through Core Data.

Treat this as an implementation lesson, not as a prohibition on all direct
database work: read access and verified writer paths remain useful. The
boundary is between a reconstructed live object contract and an untracked raw
mutation.

## Revalidation triggers

Re-run a minimal existing-payee and new-payee reassignment test when any of
these change:

- MoneyWiz application version or managed-object model.
- Database location, account, or sync provider.
- Core Data host bundle identity or transaction author.
- The fields or relationships touched by the writer.

Keep the scope minimal, wait for sync completion, and restore any test
transactions created solely for the test.

## Runtime enforcement

Run `moneywiz compatibility` to inspect the detected profile and
`moneywiz compatibility --capability NAME` before applying a write. Python
parses the store's Core Data metadata, selects a profile by both its
structure and exact model checksum, and passes the verified capability,
profile ID, checksum, and writer-contract version to the Swift host. Before
opening the persistent store, the host independently requires the exact
supported profile, checksum, `write.reassign-payees-by-id` capability, schema
version 1, ten-entity transaction allowlist, and reassignment-only payload
shape. These version-1 restrictions do not describe the version-2 handlers.
It rejects blank or duplicate transaction GIDs, partial or mixed target
fields, and inconsistent new-payee keys. It then compares the expected checksum
with both the store metadata and the selected MoneyWiz managed-object model.
The selected model path comes from one safe manifest leaf: an extensionless
current-version name receives `.mom` once, while a manifest value already
ending in `.mom` is used unchanged.

After the store opens, a read-only Core Data preflight resolves the complete
plan using exact-entity fetches with subentities excluded. It verifies account
users, existing-payee ownership, and shared new-payee ownership before any
payee insert or relationship change. Unknown, blocked, merge, mixed, schema 2,
entity-mismatched, or ownership-invalid version-1 plans fail closed without mutation.
