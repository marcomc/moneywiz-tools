# Transaction write API proposal

Status: proposed; analysis only, 9 September 2026. No new write capability is
implemented or enabled by this document.

Delivery tracking, confirmed scope and progressive task preparation are recorded
in the [implementation plan](TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md).

## Recommendation

Extend the existing Python planner and bundled Swift Core Data host with typed,
operation-specific transaction commands. First repair read completeness and app/store
resolution; then add a versioned plan/apply/result contract. Implement simple writes
before transfer conversion and investment object creation.

| Rank | Approach | Use |
| --- | --- | --- |
| 1 | Extend the existing Core Data host | Recommended: builds on verified ownership, checksum, history and app-closed checks |
| 2 | Documented MoneyWiz URL creation | Interim income/expense convenience; asynchronous, name-based, no durable result ID |
| 3 | Native GUI | Necessary fallback and reference behavior for unverified operations |

Raw SQL mutation is excluded: this project's previous relationship-only write caused
later app failures by omitting native object/history behavior. Core Data saving alone
still does not prove that every MoneyWiz business invariant or sync lifecycle is met.

## Evidence and scope

Reviewed the 7–9 September reconciliation session, its preparation/profile notes,
payee review artifact and six original learning notes, including superseded ones.
Personal records, provider policies and detailed chronology remain in private notes.
This proposal uses synthetic examples and source-code evidence only.

| Layer inspected | Revision / finding |
| --- | --- |
| moneywiz-tools checkout | `5c6f346`; pre-existing AGENTS/TODO edits preserved |
| Dependency declared and locked by tools | moneywiz-api `6ea3cdec8b1543356e00f6b529450b5aa1b39264` |
| Installed bundle and local tools environment | Both `direct_url.json` files identify the same `6ea3cdec` dependency |
| Separate `moneywiz-api/` checkout | `0b241c4`; different implementation using `SchemaMappedRow` and post-construction validation |
| Writer register | Model-48 checksum; reassignment verified, exact merge blocked |

A fix made only under `moneywiz-api/` does not update the tools dependency or installed
bundle. Do not patch `site-packages`. Prepare an API revision, update the tools pin
and lock deliberately, then validate a rebuilt relocatable bundle.

No live financial database was opened or changed for this analysis. A synthetic
in-memory model-construction experiment reproduced the account failure on the installed
Python runtime; native business semantics for proposed writes remain unverified.

## Confirmed gaps and corrected diagnoses

### Account discovery failure

The recorded traceback first fails at the installed `Account.__init__` assertion
`self.info is not None`. Its diagnostic calls `self.as_dict()`, which traverses the
`CreditCardAccount` dataclass before `statement_day` is assigned. The resulting
`AttributeError` masks the nullable-info failure and escapes the manager's
`AssertionError`/`KeyError`/`ValueError` handling.

A synthetic row with `ZINFO=None` and **present** `ZSTATEMENTENDDAY=15` reproduces
`AttributeError: ... statement_day`; changing only `ZINFO` to an empty string succeeds.
Therefore a missing statement-day column is not established by the session error.
Adding a currency account exposed the problem; that timing does not prove causation.

The separate checkout already allows nullable `info` and validates after construction.
Review the required changes against that implementation before porting or upgrading.
Test nullable info, missing optional fields and diagnostics on partially constructed
subclasses separately. Required identity errors must remain explicit.

### Incomplete reads can masquerade as complete accounts

The pinned `RecordManager.load` skips some invalid rows and exposes `load_errors`;
`scripts/accounts.py`, `transactions.py` and `holdings.py` do not expose a completeness
contract. The API eagerly loads every manager, so a card error can block a currency
account query. `transactions.py` also catches enrichment failures and silently omits
fields. Read success is not evidence that every relevant row was parsed.

The session saw zero holding quantities and missing Buy/Sell rows despite native
visibility. Treat the cause of each missing row as unproven until a fixture isolates
it. Inspect profile-selected aliases, load errors, account filtering and date cutoffs.
The pinned profile separates holding/transaction quantity aliases but still has one
price alias. Mixed layouts require aliases per consumer, including price and quantity;
physical column presence alone must not choose an operation's source.

`--until YYYY-MM-DD` parses midnight; its help should not imply end-of-day coverage.
Current naive datetimes require explicit timezone/cutoff handling before reliable
source matching. These are dependencies of safe planning, not reasons to invent rows.

### App, model and store drift

`moneywiz.sh` discovers only Setapp current/legacy default stores. Explicit `--db`
works, but a previous configuration can target an obsolete store. In
`reassign_payees_by_id.py`, `_resolve_model` defaults to Setapp and checks only its
bundle identifier: merely setting `MONEYWIZ_APP` to TestFlight still fails that check.
The session succeeded using a discovered explicit `MONEYWIZ_MODEL_PATH`.

A shared resolver should return one verified app/store/model tuple. Explicit choices
win; inspect both supported app editions and manifest leaves. If multiple valid stores
remain ambiguous, require selection rather than taking the first path. Bind owner,
store UUID and model checksum to the plan. Preserve existing safe manifest validation.

### Existing write/result boundary

The Swift `WriterPlan` accepts contract version 1, schema version 1 and reassignment
only. It rejects merges and mixed payloads. `WriterResult` returns aggregate counts;
Python relays stdout without a durable typed receipt or per-record readback.
`merge_duplicate_payees.py` prepares a schema-2 merge payload, but both capability and
host reject it. Changing a register entry to verified would not implement the route.

The native host preflights all references and uses one context save, with rollback on
error. Preserve that property. Native type conversion, new transaction initialization,
category/split writes, deletion rules, balance calculation and reconciliation mutation
have not been established by payee reassignment evidence.

## Source map and proposed changes

Existing symbols below are verified in the inspected files. New filenames are proposals.

| Location | Existing responsibility | Recommended change |
| --- | --- | --- |
| `moneywiz.sh`: defaults, `discover_real_db_path`, `usage`, dispatcher | Database selection and command routing | Add shared identity discovery and new command routing without bypassing current path checks |
| `scripts/accounts.py:main`, `transactions.py:main`, `holdings.py:main` | Read output | Expose completeness/diagnostics and operation-specific loading; add reliable scoped snapshot output |
| `moneywiz-api/src/moneywiz_api/model/account.py`: Account/CreditCardAccount | Account construction/validation in separate checkout | Preserve nullable-info fix; test optional fields and safe diagnostics; compare against pinned implementation |
| API `managers/record_manager.py`, `moneywiz_api.py` | Construction and eager loading | Operation-scoped loading with explicit complete/partial/error outcomes |
| API `model/schema_mapped_row.py`, `model/transaction.py`, `model/investment_holding.py` | Current checkout field mappings | Per-consumer aliases and required/optional semantics; mixed-layout fixtures |
| Pinned API `schema_profile.py` | Read profile detection; absent from separate checkout | Reconcile strategies during dependency update; do not assume this file exists in both revisions |
| API `database_accessor.py`, `managers/transaction_manager.py` | Category splits, refund maps, tags, account queries | Complete graph extraction and explicit timestamp/balance semantics |
| `scripts/reassign_payees_by_id.py`: `_resolve_model`, `_resolve_writer`, `apply_coredata_payload` | Shared native invocation currently housed in payee command | Extract reusable `scripts/writer_client.py` and `scripts/runtime_identity.py`; preserve v1 behavior |
| Proposed `scripts/write_plan.py`, `scripts/write_transactions.py` | None | Typed plan validation and narrow command entry points |
| `scripts/moneywiz_tools_host.swift`: WriterPolicy/Plan/Operation/Result | Strict reassignment-only contract | Add versioned typed operation dispatch and per-operation results; retain v1 compatibility |
| Same host: `preflightOperations`, `mutateResolvedOperations`, `writePlan` | Resolve all references, mutate, save/rollback | Preflight every new handler, then one atomic save per coherent unit; independent-context readback |
| `scripts/compatibility.py:require_write_capability`, matrix JSON | Exact fingerprint and capability enforcement | Add proposed capabilities initially blocked, mirror enforcement in Swift |
| `scripts/merge_duplicate_payees.py`: build/apply/export | Exact plans and fuzzy candidates | Separate reviewed-map parser and verified relationship/deletion handler |
| `Makefile`: `HOST_SOURCE`, runtime manifest, build/validate targets | Explicit bundled payload | Package all new Python/Swift modules; test independent installed copy |
| `pyproject.toml`, `uv.lock` | Pinned API revision | Promote only the tested dependency; no implicit local-checkout coupling |

If the Swift host is split into policy/preflight/handler files, update `HOST_SOURCE`,
build invocation and Swift test harness together. Do not introduce another writer app
or a second persistence engine just to add command verbs.

## Proposed plan and result contract

Names in this section are **proposed interfaces**, not currently runnable commands.
Prefer `moneywiz transaction create|edit|delete`, `moneywiz transfer link`,
`moneywiz balance adjust`, `moneywiz reconcile`, and `moneywiz write apply --plan FILE`.
Existing direct commands can remain compatibility entry points.

Planning is the default. Apply requires explicit `--apply` within the user's approved
operation scope. A saved plan is immutable: changed fields require a new plan/digest.
Do not overload the existing meaning of schema version 2 (unused merge payload).
Define a new contract version and an independently versioned operation schema.

| Contract field | Purpose |
| --- | --- |
| `contract_version`, operation schema versions | Reject unknown shapes and preserve v1 reassignment |
| `plan_id`, canonical digest, creation time | Bind the reviewed proposal to exact operations |
| Store UUID, owner GID, profile, model checksum, app identity | Prevent cross-container, cross-user and stale-model writes |
| Source interval, timezone, source evidence references | Make accounting scope reviewable without embedding credentials |
| `operations[]`: operation ID, kind, capability, dependencies | Typed command union; no arbitrary entity/key-value mutation |
| Exact entity/GID and temporary creation reference | Address existing objects; connect newly created paired objects |
| Expected fields/relationships and affected-account balances | Reject stale plans inside native preflight |
| Decimal strings, currency/asset unit, fee currency, effective date | Avoid float/FX/time ambiguity; validate signs by operation |
| Idempotency key, source-event identity, expected resulting GIDs | Recognize retries independently from coincidental amount/date matches |
| Expected postconditions and allowed changed fields | Detect altered categories, flags, metadata and related objects |

The digest is an integrity check, not user authentication. A source hash proves bytes,
not financial truth. Authorization comes from the user's task and reviewed scope.
The host validates every field it relies on, including owner and old values, rather
than trusting Python to have validated them.

For results return operation status (`applied`, `noop`, `rejected`, `unknown`), entity
and GID, numeric ID resolved after save, before/after fields, paired IDs, affected
balances and structured errors. Keep durable receipts in private storage, not temporary
stdout alone. Treat local readback, app acceptance and remote sync as separate stages.

### Atomicity, recovery and idempotency

Use one native context/save for one coherent graph repair, including both transfer
legs and planned duplicate cleanup. Reject the complete unit before mutation if any
reference is invalid. Avoid partially committing individual rows of a paired transfer.
For larger multi-unit runs report committed, rejected, untouched and unknown units.

A lost response after save is not evidence of rollback. On restart inspect deterministic
new GIDs/source-event identities and postconditions before replay. A sidecar receipt
alone cannot guarantee idempotency across a crash between save and receipt; verify the
store. Deterministic GID creation must follow the observed MoneyWiz convention and
collision/owner rules before enabling it.

Capture a consistent preimage/snapshot and private journal before a new destructive
write flow. Current commands do **not** enforce backup creation; this is a proposed
recovery requirement for the new flow. A main-file `cp` is insufficient with active WAL.
Process checks plus an application-specific writer lock serialize cooperating writers
but cannot stop MoneyWiz relaunching. Recheck immediately before opening/saving and
require the app to stay closed; do not claim an atomic exclusion mechanism.

After remote sync, restoring an old SQLite file can conflict with newer cloud state.
Prefer supported corrective operations; define a tested recovery protocol instead of
promising automatic backup restoration. Never edit persistent-history/CloudKit tables
or prune history as part of these commands.

## Operation contracts and acceptance

| ID | Operation / priority | Required semantics and decisive acceptance |
| --- | --- | --- |
| W01 | Create income/expense/refund, P1 | Explicit account/currency/date/timezone, Decimal amount, payee/categories/tags/notes; repeat source key creates nothing twice; one persisted row and expected balance delta |
| W02 | Edit transaction, P1 | ID/entity and expected prior values; field allowlist; preserve identity/unrelated fields; reconciled changes need explicit correction flow; refuse unsupported adjustment/investment types |
| W03 | Assign payee/category splits, P1 | Explicit IDs; owner checks; replace/add/remove split intent and sum validation; remove obsolete links deliberately; distinguish transaction-only from merchant-wide updates |
| W04 | Reconcile/unreconcile, P1 | Explicit IDs and expected old flags; verified balance/cutoff and complete source scope; preserve cleared/pending; pair checks; idempotent repeat and final per-ID flags |
| W05 | Create Adjust Balance, P2 | Target denomination is cash/total/asset units explicitly; native reconcile object and calculated delta; opening balance/history unchanged; matching target no-op; unsupported backdate refused |
| W06 | Guarded deletion, P2 | Exact account/entity/GID/amount/currency/date/reason; preview dependent objects; reject unnamed linked legs, scheduled/investment relationships until verified; verify no unrelated loss |
| W07 | Convert/link transfer and FX, P2 | Source ID, destination account and optional existing counterpart; both actual amounts/dates, fees and rate; one atomic native pair, reciprocal links, no duplicate import or orphan |
| W08 | Investment Buy/Sell and cash events, P3 | Asset identity/type, quantity, quote unit, price, commission/currency; verify cash and holdings independently; no invented units; aggregate income-sale method stays W01 |
| W09 | Exact and approved fuzzy payee merge, P3 | Consume approved rows only, explicit survivor, owner/evidence and relationship inventory; pending/rejected no-op; migrate current/scheduled/refund/history-relevant relationships using native rules |

Each row gets its own capability and evidence. Separate reconcile and unreconcile,
exact and fuzzy merge, deletion of ordinary and special entities when semantics differ.
Do not authorize all variants from one successful happy path.

For W07, an entity cannot be changed by assigning a type name to an existing
`NSManagedObject`. Establish whether native conversion replaces objects and how it
preserves import identity, relationships and history. If replacement is necessary,
return an explicit old/new GID mapping. Do not promise identity preservation for
conversion before verifying the native reference behavior.

GUI date nudges are **not** a writer protocol. When policy requires aligned dates,
set and verify both native fields in the atomic operation. Keep original source dates
in evidence if distinct. Do not implement the earlier two-save workaround in the CLI.
For nonzero fees verify the exact native fee currency and sign rules with fixtures;
never apply a single generic FX equation to every entity.

W05 maps to native `ReconcileTransaction` semantics, not W04's reconciliation flag.
Inspect target versus delta and cash versus share fields. Do not categorize or edit
adjustment rows like normal transactions. An aggregate investment sale is a policy-
selected income category, not proof that an assetless native Sell is supported.

## Delivery order and tests

| Phase | Deliverables | Exit evidence |
| --- | --- | --- |
| P0 | Reliable account/holding/transaction reads, explicit completeness, app/store resolver, fixture baseline | Nullable-info reproducer fixed; mixed aliases and skipped rows reported; active/retired app ambiguity tested |
| P1 | Versioned shared contract, receipts/retry handling, W01–W04 | Complete native preflight, atomic save/rollback, per-record readback; v1 reassignment unchanged |
| P2 | W05–W07 and refund/instalment repair recipes | Native reference comparison for create/delete/convert, paired dates/FX/fees, uniqueness and historical invariants |
| P3 | W08–W09, separate per-variant promotion | Holding/cash/fee totals, split relationships, approved-map and sync acceptance |

P0 and native-reference research for later phases can progress independently during
future implementation, but no write promotion precedes its readback capability.
The durable outcome is reduced repetitive GUI work; no unsupported numerical token
savings or unattended success rate is claimed.

Extend existing tests rather than replacing them:

- `tests/cli/test_reassign_payees_by_id.py`: app/model discovery, wrapper order,
  ownership, no-ops and v1 transport regression.
- `tests/cli/test_compatibility.py`: blocked/unknown capabilities, checksum/model
  mismatches, store identity and malformed contract versions.
- `tests/swift/moneywiz_tools_host_ownership_tests.swift` and its Python harness:
  late-invalid object, mixed-owner payload, entity mismatch, unknown kind, rollback
  and zero mutation before complete preflight; add native handler fixtures.
- New graph/operation tests: direct-current refund versus card reversal, already
  imported reciprocal row, separate real transfer with same amount, double retry,
  crash-after-save, stale balance, both FX directions, tiny conversion versus fee,
  distinct dates/timezones/DST, category splits and final flags after later edits.
- API unit tests: nullable info with valid statement column, missing optional versus
  required metadata, invalid raw diagnostic, per-consumer quantity/price aliases,
  unreadable Buy/Sell, no synthetic-zero holdings, complete versus partial reads.
- `tests/cli/test_bundle_publication.py`, dispatcher and installed-copy tests:
  include new modules in explicit payload; run outside/moved source checkout.

Use synthetic stores and temporary Core Data models for tests. Database-backed API
integration tests remain opt-in through `MONEYWIZ_TEST_DB_PATH`, validated read-only
before model creation. Never inherit a production CLI default for integration tests.
Do not use the current main-file `create-test-db` copy as consistent live evidence.

Native reference research should compare authorized app-created operations on disposable
stores before/after, including GIDs, relationships, history, balances and reopen behavior.
Then perform an explicitly authorized minimal live acceptance per capability: save,
readback, app reopen, history consumption and sync to another authorized client if
available. Without remote observation report sync evidence as incomplete, not verified.

Update command help, FUNCTIONS, writer/compatibility docs, bundle documentation and
release notes only when implemented behavior changes. Existing Wayfinder tickets for
[writer contract](../wayfinder/tickets/python-coredata-writer-contract.md),
[profile support](../wayfinder/tickets/schema-profile-support-policy.md) and
[write evidence](../wayfinder/tickets/verified-write-profile-evidence.md) remain the
related decision records; this proposal supplies concrete scope and acceptance.

## Open evidence questions

1. Which app-initialized transaction attributes, inverse links and defaults are
   required beyond the compiled model, especially for creation and type conversion?
2. What is the correct account/asset balance calculation across opening values,
   reconcile rows, pending activity and investment exchange events?
3. Which native deletion rules create history/tombstones and cascade to paired,
   scheduled, split and investment objects? How is safe recovery observed after sync?
4. Can durable deterministic GIDs and receipts provide retry safety across every
   crash point without adding unsupported data to the MoneyWiz schema?

These questions block their respective handlers, not the whole design or existing
verified reassignment. Resolve with recorded native fixtures, not assumed SQL layouts.

## External contract checks

The official [MoneyWiz URL documentation](https://help.wiz.money/en/articles/4525440-automate-transaction-management-with-url-schemas)
was checked on 9 September 2026: creation uses name-based parameters and asynchronous
app dispatch; it does not provide the proposed ID-based editing/FX-linking contract.
The [Adjust Balance guide](https://help.wiz.money/en/articles/4440697-how-to-adjust-account-balance)
describes a created adjustment that cannot be edited/moved and is dated at creation.
Verify restrictions against the actual supported app version before enabling W05.
