# TODO

- [ ] Extend the sanitization pipeline to spot-check new columns (attachments, free-form notes) so `--sanitize-test-db` keeps pace with future MoneyWiz schema updates.

## Propositions

Delivery sequence and phase preparation:
[Transaction write implementation plan](doc/proposals/TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md).
The first delivery scope is P0, the shared writer foundation and P1. Refine
executable tasks progressively when each phase is prepared; the existing
propositions below remain requirements, not an activated P0–P3 task list.

Implementation design and priorities: [Transaction write API proposal](doc/proposals/TRANSACTION-WRITE-API.md).
Its W01-W09 contracts refine the backlog below; none is implemented by the
proposal. Start with P0 read completeness and runtime identity, then the shared
writer contract and P1 operations.

The following writes were needed during the monthly account update workflow.
Each operation must use the existing Core Data writer, default to a dry-run
plan, require explicit `--apply`, and have its own verified schema capability.
Reuse app-closed checks and backup/history/sync safeguards. Validate on
disposable stores before enabling live writes; do not add raw SQL mutations.
Current commands do not enforce backups; consistent snapshots and durable
receipts are requirements proposed for the new write flow.
Every write must accept an explicit current-database path or resolve it through
the active app bundle, return durable record IDs, and read back the persisted
records. A failed partial batch must identify the completed and untouched IDs.

- [ ] **Introduce the versioned transaction writer contract (P1 foundation).**
  Extend the existing Core Data host, preserving verified v1 reassignment.
  See the proposal's source map, contract and phase plan.
  - Extract shared runtime identity and writer invocation from the payee helper;
    bind plans to store UUID, owner, model checksum and exact capabilities.
  - Add typed plans, expected old values, Decimal/timezone semantics, a reviewed
    plan digest and explicit apply; reject unsupported kinds natively.
  - Preflight a coherent unit, save it atomically, and return durable per-record
    results with independent readback and old/new IDs for replacements.
  - Define source-event idempotency and crash-after-save recovery; report unknown
    outcomes before retrying rather than treating lost stdout as rollback.
  - Package shared modules in the bundle manifest and validate the installed
    copy independently of the source checkout and separately checked-out API.

- [ ] **Expose complete reconciliation snapshots and graph audits (P0).**
  Missing parser rows, holdings or flags must not appear as complete zero
  balances or an empty reconciliation queue.
  - Report source-row counts, parsed/skipped IDs, diagnostics and completeness;
    use operation-scoped loading so unrelated models cannot block discovery.
  - Cover per-consumer quantity and price aliases, mixed layouts and absent
    Buy/Sell records using synthetic fixtures; do not coerce missing values to zero.
  - Export account identity, GIDs, reciprocal links, category splits, asset
    quantities, cleared/pending and reconciled flags with explicit cutoff/timezone.
  - Add a read-only graph audit for duplicate source events, orphaned/wrong
    transfer links, mismatched dates/FX and unreconciled affected legs after edits.
  - Distinguish source coverage, ledger correctness and final reconciliation;
    correct midnight-only `--until` semantics/help before relying on date coverage.

- [ ] **Read currency accounts with incomplete optional metadata.**
  The session traceback and a synthetic reproduction establish that nullable
  `Account.info` triggers diagnostic serialization before `statement_day` is
  initialized. The resulting AttributeError masks the original validation error;
  it does not prove the physical statement-day column is missing.
  - Regress `ZINFO=NULL` with valid `ZSTATEMENTENDDAY`, then test absent optional
    statement metadata separately. Never serialize incomplete dataclasses in errors.
  - Compare the separate API checkout's nullable-info/post-construction validation
    against pinned revision `6ea3cdec`; promote a tested dependency and rebuild
    the bundle rather than patching installed site-packages.
  - Make `moneywiz accounts` and account-scoped transaction reads share the
    operation-specific aliases instead of constructing every account subtype
    with fields irrelevant to the requested operation.
  - Verify account IDs, currencies, balances, transaction IDs, transfer links
    and reconciliation flags remain readable after adding a new currency
    account.
  - Return a bounded compatibility error naming the consumer and missing field
    when a required field is absent; do not expose a model-construction
    traceback for optional metadata.

- [ ] **Create expense and income transactions from the CLI.**
  Monthly fees currently require repetitive UI entry; interest and dividends
  need the corresponding income operation.
  - Accept account ID, amount, currency, date/time with explicit timezone,
    description, payee ID, category ID, and optional notes and tags.
  - Validate account and transaction currencies, conversion direction, original
    amount, and any required exchange rate; never silently use today's rate
    for historical transactions.
  - Return the created transaction ID and persisted fields; support an
    idempotency key or duplicate check so retries do not double-book a fee.

- [ ] **Create investment cash events and portfolio transactions.**
  The session required sale proceeds, investment fees, dividends, purchases and
  sales while preserving the account's chosen aggregate or units-based model.
  - Support investment income, dividend, interest, fee, Buy and Sell operations
    with account ID, security/asset type, symbol when applicable, quantity,
    unit price, commission, cash currency, date/time and payee/category.
  - Represent a confirmed aggregate sale policy as ordinary income categorized
    as investment sale proceeds, plus separate fees. Do not infer support for
    assetless native Sell; units-based Buy/Sell requires verified holding data.
  - Preserve gross proceeds, commission and resulting cash as separate native
    facts; do not infer shares, ticker, price, fee or FX rate.
  - Return the transaction and holding/cash changes, and verify quantities,
    cash and portfolio totals without converting a market-price difference into
    a fabricated transaction.

- [ ] **Edit an existing transaction by ID.**
  Correcting an incorrectly recorded fee must preserve its identity and
  unrelated metadata instead of deleting and recreating the transaction.
  - Support targeted amount, currency/rate, date/time, description, payee,
    category, and notes changes with a before/after plan.
  - Require expected prior values to reject stale edits; explicitly handle
    reconciled transactions and reject unsupported transaction types.
  - Verify persisted values and resulting account balance; cover a fee amount
    correction and historical date correction without creating duplicates.

- [ ] **Set payees and categories on selected transactions.**
  The review required correcting generic imported payees and assigning a
  transaction-level category based on verified merchant evidence.
  - Accept explicit transaction IDs plus an existing payee ID or a guarded
    canonical payee-creation request, and a category ID for one or many rows.
  - Keep payee reassignment separate from description parsing: show the source
    description, original notes, current payee and proposed target in the plan.
  - Support an expected current payee/category guard. Do not update all
    historical transactions for a merchant unless an explicit bulk scope is
    supplied.
  - Read back payee, description and category because the native app can alter
    category or description when a payee is selected.

- [ ] **Convert and link imported transactions as transfers.**
  Owned-account movements must become one native paired transfer instead of a
  duplicate expense or income, including distinct source and destination
  currencies.
  - Accept the source transaction ID, destination account ID and optional
    existing destination transaction ID; support converting an imported expense
    or income into a transfer and linking an already imported reciprocal row.
  - Require expected source/destination amounts, currencies, original amounts,
    exchange rate, account IDs and Send/Receive dates. Reject ambiguous amount
    and date matches without reciprocal/provider evidence.
  - When policy requires matching dates, set and verify both native dates
    atomically. The GUI Up/Down Send-date nudge was verified with one save;
    neither it nor the earlier two-save workaround belongs in the writer protocol.
  - Return both transaction IDs and reciprocal links. Preserve cleared status,
    notes, tags and reconciliation state unless explicitly changed.

- [ ] **Create an Adjust Balance transaction.**
  Portfolio valuation updates need a dated adjustment after itemizing fees,
  not a change to account opening-balance data.
  - Accept account ID, target balance in account currency, description, and
    supported date/time; show the current balance and calculated delta.
  - Create the native adjustment transaction and return its ID; reject stale
    balance preconditions and treat an already-matching balance as a no-op.
  - Verify the resulting Accounts total and unchanged earlier transactions;
    cover recalculation after replacing a same-session adjustment when missing
    fees are added. Expose any historical-date restrictions.

- [ ] **Delete a specifically identified balance adjustment.**
  Replace a premature same-session valuation after recording missing fees,
  rather than adding a compensating adjustment.
  - Require its transaction ID and expected account, type, date, and amount.
  - Preview deletion and the resulting balance; preserve historical adjustments
    and unrelated transactions, and require explicit application.
  - Verify removal before creating a new Adjust Balance at the target total;
    report partial completion safely if recreation fails.

- [ ] **Delete a specifically identified transaction.**
  A generic guarded deletion is needed for a mistaken current-session write,
  including a pre-existing New Balance that must be recreated after fee entry.
  - Require transaction ID, account ID, type, amount, currency, date and an
    explicit deletion reason in the dry-run plan.
  - Refuse deletion of a linked transfer unless both legs are named and the
    caller explicitly requests the paired deletion. Refuse scheduled and
    investment records until their relationship semantics are verified.
  - Return the resulting balance and verify the intended record is gone while
    unrelated records, holdings and historical adjustments remain unchanged.

- [ ] **Mark selected transactions as reconciled.**
  After matching the account total to the external source, the workflow needs
  to reconcile only the verified transactions, independently of cleared status.
  - Accept explicit transaction IDs and expected account ID, currency, and
    verified account total; refuse the write if the total has changed.
  - Support a batch of IDs with a reviewed plan and explicit per-ID outcomes;
    leave unrelated transactions and cleared/pending status unchanged.
  - Re-read flags after all later category/transfer edits, including both legs;
    earlier bulk-action success did not guarantee final reconciliation.
  - Verify persisted reconciliation flags through CLI reads and the app;
    make retries idempotent and test failure handling for partial batches.

- [ ] **Unreconcile selected transactions under a verified correction flow.**
  A correction may need to change an already reconciled record before it can be
  verified again against the source balance.
  - Accept only explicit IDs with expected reconciliation state and account
    balance guard; default to refusal when a transaction has a linked transfer.
  - Require a correction reason, produce a before/after plan and leave cleared
    state unchanged.
  - Support a companion re-reconcile batch only after the edited records and
    account balance have been read back successfully.

- [ ] **Apply approved fuzzy payee merges through the Core Data writer.**
  The CLI currently exports fuzzy candidates but the approved five groups still
  required the native Payees > Edit > Merge UI.
  - Consume only reviewed CSV rows marked approved with an explicit canonical
    payee ID; treat pending and rejected rows as no-ops and never auto-approve
    based on similarity.
  - Require an evidence note, show every source payee and its transaction,
    scheduled-item and history references, then migrate relationships and
    delete only the approved aliases.
  - Support multi-alias groups and preserve the chosen canonical display name.
    Verify source payees are absent and all former references resolve to the
    canonical payee after sync.

- [ ] **Maintain operation-specific live-write compatibility profiles.**
  This session proved one writer can be verified while another remains blocked,
  and the active TestFlight model required explicit runtime discovery.
  - Discover the current active MoneyWiz app bundle and compiled model instead
    of defaulting to a retired Setapp installation or a hardcoded model number.
  - Fix both the default path and Setapp-only identifier validation; setting
    `MONEYWIZ_APP` alone is insufficient for TestFlight today. Bind the chosen
    app, explicit store and model, rejecting ambiguous parallel installations.
  - Resolve the active TestFlight bundle for `reassign-payees-by-id --apply`.
    The validated Vodafone plan was refused because the writer attempted to
    read `/Applications/Setapp/MoneyWiz 2026.app/Contents/Info.plist` after
    that retired installation had been removed.
  - Gate each write independently, including create, edit, transfer conversion,
    adjustment, deletion, reconciliation and payee merge.
  - Capture application-closed, Core Data history, backup, CloudKit sync and
    post-reopen acceptance evidence per operation before marking it verified.
