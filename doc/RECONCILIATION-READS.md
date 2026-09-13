# Reconciliation reads

Use structured reads before constructing a transaction-write plan. Parsing
completeness, ledger consistency and external-source verification are separate.

## Runtime identity

~~~sh
moneywiz identity --app /Applications/MoneyWiz.app
moneywiz --db /path/to/store.sqlite identity --owner 1
~~~

`identity` discovers a supported MoneyWiz app and canonical store location,
reads the store UUID and owner identity, and checks the compiled model checksum
through the native host without opening a Core Data store. Explicit `--db`,
`--app` and `--model` choices take precedence; `MONEYWIZ_APP` and
`MONEYWIZ_MODEL_PATH` remain supported. Multiple valid apps/stores or owners
require explicit selection. This command does not launch MoneyWiz or change data.

Model 48's User has no GID. The binding contains `store_uuid` and
`owner_local_id`, with optional sync login, plus app version/build and the
model checksum. An identity match does not enable an unverified write operation.

The installed bundle supplies its native checksum helper. Source development can
select a built host with `MONEYWIZ_TOOLS_HOST`; the helper supports
`MoneyWizTools --model-checksum /path/to/model.mom` without a database argument.

## Complete snapshot and graph audit

~~~sh
moneywiz --db /path/to/store.sqlite snapshot --account 10 \
  --until 2026-09-12 --timezone Europe/Rome
~~~

The JSON snapshot includes:

- Selected accounts, transactions and holdings with IDs/GIDs and model fields.
- Payee/category/tag records, transaction category splits, tags and refund links.
- Per-manager source and parsed counts/IDs, skipped identities and typed errors.
- Native status/flag values, reconciliation flags, account archival status and
  native cached balance, explicitly labelled as not source-verified.
- Structural transfer checks for mismatched reciprocal native FX fields, plus
  candidate findings for differing dates, unreconciled paired legs and
  coincident transactions.

Account/cutoff selection controls displayed transactions. Graph checks use the
whole loaded graph, including counterparts outside the selected account/interval.
Completeness conservatively covers all loaded managers, not just displayed rows.
Payee/category/tag records are included across the loaded store for relationship
inspection. Treat exported JSON as private financial data.

Pair-level owner, date and reconciliation observations require reciprocal
withdrawal/deposit transaction and account links. They are emitted once with
withdrawal/deposit ID ordering, even when selection displays only one leg.
If a referenced leg exists in transaction source IDs but was skipped during
parsing, the audit reports `unreadable_transfer_leg`; `missing_transfer_leg` is
reserved for a reference absent from the observed transaction source.
Account relationships use the same distinction: `unreadable_account` means the
account was source-observed but skipped, while `missing_account` means its ID was
not present in account source evidence.
Reciprocal transfer FX checks compare the sender/recipient amounts and currencies
recorded by both legs, account for the deposit-side fee in its validated native
amount equation only when that fee uses the recipient-side currency, and require
both native exchange rates to use the same direction. A fee in another currency
is reported as a mismatched transfer rather than combined with unlike amounts.
Duplicated cross-leg values are compared exactly; the model tolerance for each
leg's internal equation does not hide a disagreement between legs. A mismatch
emits only transaction IDs, not financial field values.

Amount/date coincidence is a review candidate, never authority to merge or delete.
Different transfer dates can be legitimate. The cached account balance is not an
independent balance calculation, and raw native status/flags are not an established
cleared/pending interpretation. External activity, accounting scope and native
business semantics still need verification before write planning.

Financial amounts and quantities must be finite before public output. A selected
cached balance must also retain its native numeric type; malformed or non-finite
values fail the operation with status `2` rather than being stringified.
Core transaction descriptions preserve the native text-or-null shape; binary or
other non-text values are rejected during API admission, leaving the record
unreadable with structured partial diagnostics and status `3`. The root
description guard retains a bounded status `2` fallback for unsupported values
that reach it. Snapshot status and flag fields must be present as native
integers; their numeric meanings remain uninterpreted, and malformed values fail
the direct export guard with status `2`. The selected account's native archived
flag follows the same integer-only export rule.

## Existing list commands

~~~sh
moneywiz accounts --format json --diagnostics
moneywiz holdings --account 10 --format json --diagnostics
moneywiz transactions --account 10 --format json --diagnostics \
  --until 2026-09-12 --timezone Europe/Rome
~~~

Without `--diagnostics`, list JSON remains an array. With it, output is an object
containing `rows` and `completeness`. Table output remains available without the
diagnostic envelope. Partial reads also emit structured diagnostics on stderr.
When row enrichment and manager parsing are both partial, stderr contains one
combined `read_completeness` document rather than separate diagnostics.
Accounts and holdings load their relevant managers; transactions additionally
load account and payee information for enrichment. The snapshot loads all managers.

`--until YYYY-MM-DD` is an inclusive cutoff at that date's midnight in
`--timezone` (UTC by default); it does not include the rest of that day. A
timestamp cutoff requires an explicit offset, for example
`2026-09-12T18:30:00+02:00`, and is also inclusive. Transaction times are decoded
from the absolute Core Data epoch; daylight-saving changes do not shift that
epoch. Output includes the UTC offset.

## Exit statuses and planning boundary

| Status | Meaning | Next action |
| --- | --- | --- |
| `0` | Requested managers parsed completely | Inspect graph findings and verify external source scope |
| `3` | Some requested records or enrichment could not be read | Keep usable rows for diagnosis; block dependent write planning |
| `2` | Invalid arguments, missing identity or failed read | Correct the reported input/schema/runtime issue |

An empty transaction list with status `3` is not an empty account. An explicitly
selected account that is source-observed but unreadable returns status `3` with
its manager diagnostics; an ID absent from source evidence is an invalid
selection and returns status `2`. Likewise, status `0` and no graph findings do
not prove bank reconciliation or live-write compatibility. Use the per-operation
capability gate and source evidence.
