# Transaction reconciliation flags

W04 changes only the native `reconciled` attribute of selected existing
transactions. `reconcile` and `unreconcile` have separate capabilities. Both
are enabled for supported MoneyWiz bundles at build 449 or newer, with exact
model and canonical store identity checks. Synthetic stores require the
disposable metadata marker regardless of bundle channel.

## Build and review a plan

~~~sh
moneywiz transaction reconcile --request /private/path/request.json \
  --plan /private/path/plan.json
moneywiz write validate --plan /private/path/plan.json
moneywiz write apply --plan /private/path/plan.json
~~~

Use `transaction unreconcile` for a correction, with a nonempty
`correction_reason`. The request contains the usual version-2 envelope,
`source_scope` and a nonempty `operations` array. Each operation names an
ordinary deposit, withdrawal or refund by exact entity and GID, its account
GID, expected prior `reconciled` value, and exact native `status` and `flags`.
Native status `1` or the app-observed cleared status `2` is required. The native status and flags are raw guards;
their business meanings are not inferred or changed. Reconcile expects `false`
and sets `true`; unreconcile expects `true` and sets `false`.

`source_scope` requires `scope: "entire_account"`, `read_status: "complete"`,
`external_source_verified: true`, the account GID/currency, an independently
verified balance, matching source/parsed counts, and the sorted unique GIDs of
**every** transaction in the account. It is the reviewer's attestation of source
evidence; a caller-supplied `true` does not itself verify a bank statement.
The native host compares the complete GID inventory and reviewed balance with
the store before saving and during independent read-back. Live balances use
the ledger; invented fixture balances use their cache. A snapshot's cached balance is
not external-source evidence. Keep the request and plan private.

## Apply and recover

~~~sh
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/plan.json --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/plan.json
~~~

All targets are checked before mutation. One Core Data save changes only their
`reconciled` attributes; account balance, payee, categories, native status and
flags remain unchanged. A repeated completed plan returns `noop`. A stale,
partial or mixed result refuses replay. Recovery classifies persisted state
without writing. See [Writer Recovery](WRITER-RECOVERY.md) for the journal.

W04 excludes transfers, investment/fee/FX/void/scheduled variants, foreign
accounts and unsupported native status. A passing disposable test does not
authorize a live financial write.
