# TODO

## Authorized live validation checkpoint — 30 September 2026

W01–W09 synthetic trials passed on a private copy and the reviewed live Setapp
store, including replay, recovery, application display and observed iCloud export.
Cleanup restored the investment balances and removed temporary transfers and
merge-reference rows; three labelled bank TEST transactions remain as requested.
Ordinary operations now cover all seven concrete account subtypes.
See [Live Write Compatibility](doc/LIVE-WRITE-COMPATIBILITY.md) for exact scope.
Historical phase rows below retain their original implementation checkpoints;
their pending live authorization statements are superseded by this trial.
The user confirmed retained TEST rows and matching balances on the iPhone;
individual temporary investment and transfer identities were not checked there.
Independent review of the current changes remains a separate release gate.

- [ ] Extend the sanitization pipeline to spot-check new columns (attachments, free-form notes) so `--sanitize-test-db` keeps pace with future MoneyWiz schema updates.

## Active release 0.3.0 tasks

The user confirmed on 2026-09-28 that the full P0/P1F/P1/P2/P3 roadmap,
including W01–W09, belongs to `release/0.3.0`. Keep one PR per operation. W01–W04
are already integrated as recorded below; leave each new PR open for user
inspection and do not merge. Refine later task details as prerequisites become
concrete; preserve the propositions below as requirements.

| ID | Deliverable / owner | Depends on | Acceptance | State |
| --- | --- | --- | --- | --- |
| P0-01 | Complete scoped API reads / API worker | Pinned compatibility baseline | Nullable metadata, safe diagnostics, per-consumer aliases, explicit completeness and opt-in DB tests | API read-completeness integrated and pinned; CI green (run 34761938543) |
| P0-02 | Runtime identity / identity worker | Existing v1 model resolver | TestFlight/Setapp discovery, explicit overrides, ambiguity and mismatch rejection; v1 regression checks | Integrated in Tools P0 PR #3 at `374ebd4` |
| P0-03 | CLI snapshots and graph audit / controller | P0-01 interface | Structured completeness, identities/relationships/flags, explicit cutoff/timezone and diagnostic exit status | Integrated in Tools P0 PR #3 at `374ebd4` |
| P0-04 | API pin, packaging and P0 integration / controller | P0-01–P0-03 | Pre-PR readiness, current-head Codex clean per PR, tested packaged runtime and updated docs | Integrated in Tools P0 PR #3 at `374ebd4`; tested API pin included |

PR links and evidence are recorded here once created. Runtime and remote
acceptance remain distinct from implementation and local test completion.

### P1F shared writer foundation

Entry: P0 merged into `release/0.3.0` at `374ebd4`. Implementation owner:
`feat/p1f-writer-foundation`; PR target: `release/0.3.0`. Scope follows
[P1F](doc/proposals/TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md#p1f-shared-writer-foundation)
and the [shared contract](doc/proposals/TRANSACTION-WRITE-API.md#proposed-plan-and-result-contract).
W01–W04 operation implementations and live financial writes are excluded from
P1F. P1F integrated into the release branch at `1020c40`.

| ID | Deliverable / owner | Depends on | Acceptance | State |
| --- | --- | --- | --- | --- |
| P1F-01 | Typed plans and shared writer client / Python worker | P0 merge | Strict versions, reviewed digest, identity, source event, old values, Decimal/timezone contracts; v1 transport preserved | Implemented; synthetic validation passed |
| P1F-02 | Native preflight, atomic save and read-back / native worker | P1F-01 contract | Reject invalid references/stale state before mutation; one save; durable IDs and independent persisted results | Implemented; synthetic validation passed |
| P1F-03 | Journal, snapshots, retry and recovery / Python and native workers | P1F-01–02 | Private flushed preimage/receipt; before/after-save interruption tests; no replay of unknown outcomes | Implemented; synthetic validation passed |
| P1F-04 | Discovery and bounded retention cleanup / Python worker | P1F-03 | Effective paths/provenance; explicit cleanup apply; 90-day verified retention and indefinite unresolved evidence | Implemented; synthetic validation passed |
| P1F-05 | CLI, packaging, documentation and integration / controller | P1F-01–04 | Relocated bundle tests, unchanged v1/P0 tests, local READY and current-head independent GitHub clean evidence | Integrated at `1020c40`; W01 builds on this baseline |

### P1 W01 transaction creation

Entry: P1F integrated at `1020c400d4740f45f29f1e2c87a11aa0a74f8603`.
Former branch: `feat/p1-w01-transaction-create`; PR #5 merged into
`release/0.3.0`, and the worktree has been retired.
Scope: [W01](doc/proposals/TRANSACTION-WRITE-API.md#operation-contracts-and-acceptance)
through the version-2 typed plan and shared native writer. Only invented
fixtures and disposable stores are authorized for validation. W02 editing,
W03 post-create assignment/split mutation, W04 flags and all P2/P3 variants
remain excluded. At W01 integration, the API revision was pinned at
`7cfa1ea9f09263f87e4099c4315bd2cc83c25d5c`.

| ID | Deliverable / owner | Depends on | Acceptance | State |
| --- | --- | --- | --- | --- |
| P1-W01-01 | Exact model semantics and disposable fixtures / native worker | P1F merge | Compiled TestFlight model fields, inverse relationships and supported variants recorded without live data | Model 48 / build 449 inspected; CashAccount income, expense and linked refund fixtures |
| P1-W01-02 | Typed creation plans and CLI / Python worker | P1-W01-01 schema | Explicit owner/account/currency/Decimal/date/timezone/source identity; strict per-kind schema; negative input coverage | Implemented; Python/native schema and CLI validation passed |
| P1-W01-03 | Atomic creation and persisted verification / controller | P1-W01-01–02 | Income, expense and supported refunds; preflight ownership/split totals/stale balance; one save; durable IDs and independent read-back | Implemented; production host persisted-field and relationship checks passed |
| P1-W01-04 | Source-event retry and interruption recovery / Python and native workers | P1-W01-03 | No duplicate on repeated event; before/after-save crash evidence; conflicting/mixed outcomes refuse replay | Before/after-save recovery and journal no-op tests passed; mutation-sensitive boundary tests |
| P1-W01-05 | Product bundle and regression integration / controller | P1-W01-02–04 | Required lint/tests; production host on disposable stores; relocated installed copy after build source removal; P0/P1F/v1 preserved | Production bundle built; installed validation evidence accompanies PR handoff |
| P1-W01-06 | Independent review and release handoff / controller | P1-W01-05 | One cumulative ledger, local READY, current-head GitHub review, PR targeting release branch; no merge | Independent local review complete; current-head GitHub evidence accompanies PR handoff |
| P1-W01-07 | Application and sync acceptance / future authorized acceptance owner | P1-W01-06 | Direct MoneyWiz reopen/history and remote-client evidence for each promoted variant | Not authorized in this synthetic-only task; live capabilities blocked |

### P1 W02 transaction editing

Entry: W01 integrated at `e80b08006aab268f8cc192f8fe0bb98c259fd06f`.
Branch: `feat/p1-w02-transaction-edit`; PR target: `release/0.3.0`.
Scope: [W02](doc/proposals/TRANSACTION-WRITE-API.md#operation-contracts-and-acceptance)
through P1F version-2 plans. Owners below have exclusive implementation areas;
the controller owns integration and the cumulative review ledger.
Only invented disposable model-48 stores are authorized. W04 flags,
reconciled correction, special transactions, FX and P2/P3
are excluded. Preserve the exact pinned API revision and existing W01/v1 behavior.

| ID | Deliverable / owner | Depends on | Acceptance | State |
| --- | --- | --- | --- | --- |
| P1-W02-01 | Scalar allowlist and model semantics / native worker | W01 merge | Installed TestFlight 2026.37.1 build 449 model-48 evidence; supported income/expense/refund variants and exclusions explicit | Implemented on synthetic model-48 fixtures; live scope blocked |
| P1-W02-02 | Strict edit plans and CLI / controller | P1-W02-01 | Exact entity/GID, expected prior for every change, owner/account/currency guards; Python/native contract parity | Python/native contract and negative paths passed |
| P1-W02-03 | Native atomic edit and verification / native worker | P1-W02-01–02 | Whole-plan preflight, one save, unchanged identities/relationships/history, expected balance and refund invariants | Native persistence and rollback tests passed on disposable stores |
| P1-W02-04 | Disposable regressions and recovery / fixture worker and controller | P1-W02-02–03 | Every scalar positive/negative; stale/special/reconciled rejection; atomic rollback, repeat no-op, before/after-save crash and durable journal evidence | Native crash/recovery and full CLI suite passed on disposable stores |
| P1-W02-05 | Installed bundle and documentation / controller | P1-W02-04 | Full required validation; production bundled host; relocated install after disposable build source unavailable; unchanged API pin | Relocated bundle CLI passed with source reads denied; API pin remains `401c919` |
| P1-W02-06 | Independent review and PR handoff / controller | P1-W02-05 | One coordinator/ledger; local READY; PR to release/0.3.0; merge after current-head clean evidence | PR #7 clean on `084eab3`, squash-merged into release at `e0bb1d5` |
| P1-W02-07 | Application and sync acceptance / future authorized owner | P1-W02-06 | Direct authorized MoneyWiz reopen/history and remote-client evidence for each variant | Not authorized; live edit capability blocked |

### P1 W03 transaction assignment

Entry: W02 integrated at `e0bb1d5`. Branch:
`feat/p1-w03-assign-payee-categories`; PR target: `release/0.3.0`.
Scope: exact-ID replacement of payee and category splits on existing ordinary
transactions. Only invented disposable model-48 stores are authorized. Live
capability stays blocked pending application and sync acceptance. See
[Transaction Assignment](doc/TRANSACTION-ASSIGNMENT.md).

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P1-W03-01 | Strict plan and CLI | Prior/target relationships, exact transaction identity, signed split total and replacement intent | Implemented; Python validation passed |
| P1-W03-02 | Native preflight and atomic replacement | Owner/category type and stale-state guards; deliberate obsolete-link deletion; unchanged balance and unrelated fields | Implemented on invented disposable stores |
| P1-W03-03 | Read-back and recovery | Durable IDs, exact final relationships, repeat no-op and before/after-save classification | Native fixture tests passed |
| P1-W03-04 | Bundle and regression validation | Relocated installed bundle plus unchanged W01/W02/P1F behavior | 606 CLI tests passed; relocated W01/W02/W03 bundle checks passed |
| P1-W03-05 | Independent review and release handoff | Local readiness, current-head independent GitHub review, PR into release branch | PR #8 merged into release at `ab719ea` |
| P1-W03-06 | Application and sync acceptance | Authorized MoneyWiz reopen/history and remote-client evidence | Not authorized; live capability blocked |

### P1 W04 reconciliation flags

Entry: W03 integrated at `ab719ea`. Branch: `feat/p1-w04-reconciliation`;
PR target: `release/0.3.0`. Reconcile and unreconcile use separate capabilities.
Only invented disposable model-48 stores are authorized. Transfer pairs,
adjustments, scheduled/investment variants and live writes remain blocked until
their native and external-source acceptance is established.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P1-W04-01 | Exact scope and typed plans | Complete full-account read inventory, explicit target IDs, expected flags and verified account balance; separate correction reason for unreconcile | Implemented; strict Python tests passed |
| P1-W04-02 | Native flag update | Whole-batch preflight, account/owner/variant guards, one save, unchanged native status/flags and unrelated fields | Implemented; disposable model-48 read-back passed |
| P1-W04-03 | Recovery and negative paths | Final per-ID flags, repeat no-op, stale/partial/mixed refusal, before/after-save recovery | Native interruption and mixed-batch tests passed |
| P1-W04-04 | Bundle and documentation | Relocated installed CLI, W01–W03 regressions, help, changelog and contract | Relocated W04 bundle passed; 629 CLI tests passed, 2 skipped before final mixed-batch test |
| P1-W04-05 | Independent review and PR handoff | Local READY and current-head GitHub review; leave PR open for user inspection | Current-head review clean; PR #9 merged at `1f91151` |
| P1-W04-06 | Application and sync acceptance | Authorized MoneyWiz reopen/history and remote-client evidence | Not authorized; live capabilities blocked |

## P2 preparation: W05 Adjust Balance

Entry: W04 code merged into `release/0.3.0` by PR #9 at `1f91151`.
`feat/p2-w05-adjust-balance` starts from that commit. W05 is part of P2 within
`release/0.3.0`; the phase label does not create a separate release branch.
Its PR must target `release/0.3.0` after its base is verified. See
[W05 reference contract](doc/TRANSACTION-ADJUST-BALANCE.md). P1 application
and sync acceptance remains a separate promotion gate.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P2-W05-01 | Native reference | Compare the app-created adjustment with before/after data from the observed account | Complete for GBP investment total without holdings; other units lack native evidence |
| P2-W05-02 | Typed plan and no-op contract | Bind unit, account, target, prior, delta, date/timezone and source identity; reject stale state | Implemented for the observed variant |
| P2-W05-03 | Native creation and recovery | One save, app-matching fields, unchanged opening balance, durable ID and replay recovery | Verified on a private copy and an authorized live replacement |
| P2-W05-04 | Store-copy and bundle validation | Positive, stale, duplicate and backdated checks; rebuilt and relocated bundle | Local evidence complete; focused regression gate passed |
| P2-W05-05 | Independent PR review | Local READY and current-head clean review against `release/0.3.0`; leave PR open for user inspection | [PR #10](https://github.com/marcomc/moneywiz-tools/pull/10) merged at `29864f1` |
| P2-W05-06 | Application and sync acceptance | Reopen a tool-written row in MoneyWiz and verify sync for the supported variant | Live app read-back and iCloud export observed; investment-total capability verified |

W05 extensions on `feat/w05-balance-units`: ordinary balance, investment cash
and existing stock/Forex quantity are implemented. Focused native tests cover
apply, replay, recovery, matching-target no-op and subsequent Buy/Sell. Independent
local review is complete. Installed-CLI live trials covered four ordinary
currencies, investment cash and stock quantity; app read-back, iCloud export and
cleanup restored original financial data while preserving the three retained
TEST rows. Forex quantity has disposable-store coverage. Fresh installed-bundle
validation passed: 917 tests on TestFlight and 55 on Setapp, including the
Setapp-specific reference-store case. PR #16 passed current-head GitHub review
and merged at `d037afb`.

## P2 preparation: W06 guarded deletion

Entry: W05 merged into `release/0.3.0` at `29864f1`. The first W06 variant is
deletion of one specifically identified `ReconcileTransaction` from the observed
no-holdings GBP investment-total account shape. Private before/after snapshots
of an authorized MoneyWiz deletion show the target row removed and the account
version changed. Other shared `ZSYNCOBJECT` rows did not change; CloudKit history
and metadata changed, and an unrelated report row appeared during the interval.
These snapshots do not establish deletion semantics for other transaction types.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P2-W06-01 | Native reference and dependencies | Inventory the target, account, linked records and CloudKit effects from the existing private snapshots | Private before/after reference inspected; observed target has no dependent business links |
| P2-W06-02 | Typed deletion preview | Bind exact target GID/entity/account, amount, date, currency, expected balance and reason; show the resulting balance | Implemented for the latest GBP investment-total adjustment |
| P2-W06-03 | Guarded native deletion | Recheck app/model/store identity and all target/dependency preconditions before one save; preserve unrelated rows | Applied on marked private copy; only target row removed and account version changed |
| P2-W06-04 | Recovery and refusal | Classify a present target as retry-safe and a verified prior deletion as no-op; refuse ambiguous absence, stale state and unsupported links | Private-copy recovery and replay passed; synthetic crash and refusal checks passed |
| P2-W06-05 | Local and bundle validation | Check before/after store copies, interruption recovery, relocated bundle, lint and independent review | Copy comparison, recovery, lint and local independent review passed; rebuilt relocated bundle suite: 662 passed, 2 skipped; GitHub review pending |
| P2-W06-06 | Application and sync acceptance | Verify a tool-written deletion in MoneyWiz and its operation-specific sync evidence | Pending separate live-write authorization |

Linked transfers, scheduled records, holdings and ordinary transaction types
remain outside this first variant until their native deletion behavior is known.

### W06 supported-record extension

Entry: W05 extensions merged through PR #16 at `d037afb`.
Implementation branch: `feat/w06-supported-deletion`. The finite contract is
[Supported Transaction Deletion](doc/TRANSACTION-DELETION.md).

| Deliverable | Current evidence / remaining gate |
| --- | --- |
| Eight supported transaction entities and exact owned closure | Native model inventory inspected; 68 source native tests passed, including historical-price preservation and refusal |
| Python/native input parity and exact receipt proof | Invalid-plan tests passed; eight altered native receipt proofs refused |
| Installed planning, journaled apply, replay and recovery | Disposable CLI tests and live Python-client apply/replay/recovery passed; four journal entries verified |
| Current actual-store identity and retained TEST protection | Verified current Setapp identity and read-only inventory on a coherent copy |
| Native counterpart policy, live app/sync acceptance and cleanup | Native withdrawal deletion includes its refunds; 15 native and three client targets exported then deleted; financial state and three retained TEST rows restored |
| Full fresh installed suite, privacy, lint and independent review closure | Pending integrated final gate |
| PR, current-head Codex clean, squash merge and scoped cleanup | Pending; authorized by the active user goal |

## P2 preparation: W07 transfer replacement

Entry: W06 merged into `release/0.3.0` at `54606bb`. W07 covers a marked
disposable model-48 store: one imported withdrawal and an optional explicitly
identified deposit become two reciprocal, zero-fee transfer legs. The observed
private reference pairs establish the link and FX fields and separate dates;
they do not establish nonzero-fee or live conversion acceptance.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P2-W07-01 | Native reference and scope | Bind the two account/leg relationships, observed FX direction and zero-fee fields | Model-48 and private reference evidence inspected; unsupported variants remain blocked |
| P2-W07-02 | Typed replacement plan | Bind old GIDs/numeric IDs, both accounts/balances, amounts, currencies, dates, rate and source event | Implemented; Python/native contract tests passed |
| P2-W07-03 | Atomic native replacement | Recheck identity and old rows; create reciprocal legs in one save; read back IDs, links and balances | Disposable production-host and relocated-bundle tests passed |
| P2-W07-04 | Recovery and refusal | No-op verified replay; refuse stale, ambiguous, partial and unsupported state | Before/after-save and negative fixture checks passed |
| P2-W07-05 | Local validation and review | Integrated suite, bundle privacy, lint and independent review | 691 passed; fresh bundle file/link scan clean; independent local review clean |
| P2-W07-06 | Application and sync acceptance | MoneyWiz reopen/history and operation-specific sync evidence | Pending separate live-write authorization; capability blocked |

## P3 preparation: W08 investment transactions

Entry: W07 merged into `release/0.3.0` at `d5911bb`. W08 uses the installed
model-48 InvestmentAccount and holding relationships. Read-only native records
show ordinary investment cash events and linked Buy/Sell rows. Aggregate
accounts must not acquire invented holdings or assetless Sell transactions.
Model-48 holdings have no mutable current-units attribute; units and investment
cash are derived from transaction history and must be checked independently.
Only marked disposable stores are authorized for implementation validation.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P3-W08-01 | Native reference and account modes | Record real Buy/Sell/cash field shapes, holding ownership, cash and quantity equations; identify unsupported variants | Read-only native records and disposable before/after evidence complete for the supported shapes |
| P3-W08-02 | Investment cash-event plans | Explicit InvestmentAccount, income/expense kind, amount, currency, date, category and expected cash state; preserve aggregate versus units-based policy | Implemented; disposable validation passed |
| P3-W08-03 | Buy/Sell plans | Bind existing holding, asset identity/type, positive quantity and price, commission/currency, account cash and holding units | Implemented for existing holdings; disposable validation passed |
| P3-W08-04 | Native atomic persistence | One guarded save; exact derived cash and unit deltas, unchanged unrelated objects, fresh-context read-back | Implemented; disposable persistence and read-back passed |
| P3-W08-05 | Recovery and refusal | Verified no-op replay, before/after-save recovery; reject stale, ambiguous, FX and unsupported zero-value shapes | Implemented; replay, crash and refusal checks passed |
| P3-W08-06 | Bundle validation and independent review | Installed bundle, privacy scan, regressions, local READY and current-head GitHub review | Fresh bundle and direct admission passed; 709 integrated and 29 installed tests passed; independent local review clean; GitHub review pending |
| P3-W08-07 | Application and sync acceptance | MoneyWiz reopen/history and operation-specific sync evidence before live promotion | Pending separate live-write authorization |

## P3 preparation: W09 payee merges

Entry: W07 is integrated; W08 has an independent PR. W09 changes payee
relationships and does not depend on investment transaction code. The model-48
reference inventory covers transactions, string history, scheduled handlers,
payment plans and info cards. Only marked disposable stores are admitted.

| ID | Deliverable | Acceptance | State |
| --- | --- | --- | --- |
| P3-W09-01 | Complete native inventory | Explicit source, survivor, owner and five relationship families | Implemented; disposable inventory verified |
| P3-W09-02 | Exact and fuzzy review plans | Separate capabilities; exact name normalization; one approved map row; pending/rejected no-op | Implemented; focused validation passed |
| P3-W09-03 | Atomic native migration | Guard current inventory, migrate each reference, delete source, save once and read back | Implemented; disposable validation passed |
| P3-W09-04 | Recovery and refusal | Replay, crash boundaries, stale identity, unmarked store and unsupported model refusal | Focused and installed bundle validation passed |
| P3-W09-05 | Bundle and independent review | Integrated suite, installed bundle, privacy scan, local READY and current-head GitHub review | 695 passed, 14 skipped; fresh bundle privacy scan and independent local review clean; GitHub review pending |
| P3-W09-06 | Application and sync acceptance | MoneyWiz reopen/history and operation-specific sync evidence | Pending separate live-write authorization |

## Propositions

- [ ] **Audit redundant read compatibility after integrating the new API pin.**
  With Tools pinned to `moneywiz-api` commit `401c919`, compare any Tools read
  adapters with the API completeness and schema-profile contracts. Remove only
  proven duplication; retaining every adapter is valid if each serves a distinct
  consumer or safety check. This backlog entry does not authorize a Tools
  simplification or an API change.
  - Map `scripts/read_support.py`, `scripts/holdings.py` and
    `scripts/snapshot.py` to the pinned API's `schema_profile.py`,
    `model/schema_mapped_row.py`, `database_accessor.py` and `read_result.py`.
    Produce a keep/remove table with exact symbols, callers and tests;
    distinguish column parsing from operation scope and enrichment diagnostics.
  - Preserve Tools operation-specific completeness checks, runtime identity,
    `scripts/compatibility.py`, the compatibility matrix and native write
    capability gates. Complete reads alone never authorize a write.
  - For a justified removal, test incomplete/nullable reads, mixed schema
    aliases, model-48 tags, CLI failure behavior, unsupported-write rejection
    and the rebuilt installed bundle. Use a separate reviewed branch.

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
The v2 writer foundation now enforces consistent snapshots and durable receipts.
Existing v1 commands retain their prior backup behavior.
Every write must accept an explicit current-database path or resolve it through
the active app bundle, return durable record IDs, and read back the persisted
records. A failed partial batch must identify the completed and untouched IDs.

- [ ] **Introduce the versioned transaction writer contract (P1 foundation).**
  Implemented in `feat/p1f-writer-foundation` and integrated at `1020c40`.
  Preserves v1 reassignment.
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
    against reviewed revision `7cfa1ea9f09263f87e4099c4315bd2cc83c25d5c`;
    validate the pinned dependency and rebuilt bundle rather than patching
    installed site-packages. API PR #4 head
    `3f74a22f327297c708e0ed852e7ed6b5b8268be6` passed CI run `34761938543`
    and merged as `7cfa1ea9f09263f87e4099c4315bd2cc83c25d5c` into `release/0.3.0`.
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
  W01 is implemented for marked disposable CashAccount stores; live clearance
  and other account variants remain pending. See `P1-W01-01`–`P1-W01-07`.
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
  - [x] W07 fixture scope: replace one imported withdrawal and, optionally, its
    independently identified imported deposit with two new native transfer legs.
    Bind both original GIDs and numeric IDs, both account GIDs and balances, both
    currencies, amounts, dates and the directional exchange rate in one plan.
  - [x] Verify the new sender/recipient GIDs and numeric IDs, reciprocal links,
    account references and both resulting balances after one atomic save. Recover
    from either side of the save boundary without repeating the replacement.
  - [x] Cover GBP-to-EUR and EUR-to-GBP fixture conversions, separate Send/Receive
    dates, source-only and paired-import replacement, stale rows, ambiguous
    counterparts, existing transfers and duplicate source events.
  - [x] Keep nonzero-fee conversion blocked until a native before/after example
    establishes the fee currency and amount rules; observed reference pairs have
    zero fee. Keep live capability blocked until application and sync acceptance.

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
