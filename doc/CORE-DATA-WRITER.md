# Compatible Core Data Writer

## Status and compatibility

This document records the verified contract for direct payee reassignment on a
live MoneyWiz database. It was observed on 2026-08-08 with MoneyWiz 2026
version 2026.32.1, build 431, using `MoneyWizDataModel 48`.

The writer resolves the current model version from MoneyWiz's
`MoneyWizDataModel.momd/VersionInfo.plist`. A future MoneyWiz model version is
not automatically assumed compatible; the contract must be rechecked after an
app or model upgrade.

## Why raw SQLite was insufficient

Changing `ZSYNCOBJECT.ZPAYEE2` directly updates the local relationship but does
not create MoneyWiz's persistent-history provenance or its private CloudKit
metadata and serialized asset. That can leave a locally visible change which
does not have the same synchronization contract as a native edit.

MoneyWiz owns the `ANSCKRECORDMETADATA` and
`ANSCKRECORDMETADATAENCODEDRECORDASSET` payloads. The compatibility writer does
not synthesize or patch those private payloads.

## Verified write protocol

`reassign-payees-by-id --apply` writes through Core Data, not SQL:

1. The Python planner reads the database and resolves a target payee per user.
2. The installed `MoneyWizWriter.app` loads the current MoneyWiz model.
3. It saves a single Core Data transaction with persistent history enabled,
   `transactionAuthor = MWLocalAuthor`, bundle identifier
   `com.moneywiz.personalfinance-setapp`, and executable name `MoneyWiz`.
4. On the next launch, MoneyWiz consumes that history and materializes its own
   CloudKit metadata, encoded record asset, and export.

The protocol was exercised for both an existing payee reassignment and a newly
created payee. In both cases MoneyWiz displayed the result, incremented the
record metadata export transaction, and recorded successful CloudKit events.

## Operating rule

Quit MoneyWiz before using `--apply`; the writer requires exclusive store
access. Reopen MoneyWiz afterward and wait for iCloud Sync to report `Up to
Date`. This is a concurrency requirement, not a prohibition on using the live
database path.

Payee matching uses Unicode NFKC normalization, whitespace collapsing, and
case-folding within the transaction's user. The existing stored payee name is
retained when it matches. If no matching payee exists, the writer creates one
using the transaction description and that transaction's account user. Duplicate
matching payees are rejected as ambiguous rather than choosing one silently.
