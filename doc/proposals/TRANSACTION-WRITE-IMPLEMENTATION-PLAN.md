# Transaction write implementation plan

Status: roadmap recorded on 12 September 2026; implementation has not started.
The first delivery scope is confirmed. Later phases describe intended scope and
require phase preparation before executable tasks are added.

## Purpose and related documents

Make routine MoneyWiz reconciliation use verified CLI writes, with targeted
computer-use fallback and actionable evidence when the CLI cannot complete an
operation. Track development and application acceptance separately.

| Document | Responsibility |
| --- | --- |
| This plan | Delivery order, decisions, coordination, acceptance and progress |
| [Transaction write API proposal](TRANSACTION-WRITE-API.md) | Technical source map, W01–W09 operation contracts and evidence questions |
| [Project TODO](../../TODO.md) | Existing propositions and progressively refined executable work |
| Private MoneyWiz notes in Obsidian | User policies, source evidence, session reports and financial details |

The technical proposal remains the detailed design reference. Where decisions
evolve, update both documents where relevant and record the reason here.
No proposed command or roadmap entry constitutes an enabled write capability.

## Decisions and boundaries

| Decision | State |
| --- | --- |
| First delivery: P0, shared writer foundation and P1/W01–W04 | Confirmed by user |
| New release version and first release branch: `0.3.0`, `release/0.3.0` | Confirmed by user |
| Initial application acceptance target: MoneyWiz TestFlight | Confirmed; rediscover exact app, store and model during execution |
| Use Obsidian for private recovery/session information | Confirmed in principle |
| Create detailed TODO tasks progressively as each phase is prepared | Requested by user |
| Separate release branch for each phase; child implementation branches with independent GitHub review | Required by user |
| Read models and database discovery belong in `moneywiz-api` | Existing architecture, retained |
| Python plans and native Core Data persistence belong in MoneyWiz Tools | Existing architecture, retained |
| Machine journal stored locally, readable reports in Obsidian | Confirmed by user |
| Retain verified journal entries for 90 days and unresolved entries until resolved | Confirmed by user; Obsidian reports remain indefinitely |
| Skill can discover journal/report locations and perform bounded cleanup | Required by user; implement with the journal interface |

The separately checked-out API, pinned dependency and installed app bundle are
distinct artifacts. Changes to the API checkout must reach the tested dependency
pin, lockfile and rebuilt bundle before they affect the installed CLI.

Extend the existing Swift Core Data host. Preserve verified v1 payee reassignment
and its guards. Each new operation and meaningful variant needs an independently
verified capability; direct SQLite mutation is outside this design.

This roadmap authorizes no implementation or live acceptance by itself. Current
work is documentation on `release/0.3.0`. A future instruction to implement a phase establishes its
execution scope; source inspection and ordinary implementation decisions should
then proceed without repeatedly seeking the same approval.

## Progressive phase preparation

Keep the whole roadmap visible while detailing only the phase about to start.
Existing TODO propositions are retained as requirements; they are not evidence
that all phases have been scheduled or authorized.

1. Refresh the current code, dependency, installed runtime and completed evidence.
2. Resolve technical facts from code, fixtures and existing source evidence first.
3. Use `$grilling` for unresolved user decisions, one question at a time with a
   recommendation. Reuse decisions already recorded; do not repeat an interview
   when no material decision remains. Record any scope change and its impact.
4. Define the phase's entry conditions, deliverables, exclusions and exit evidence.
5. Use `$add-todo` to refine the matching propositions into executable tasks.
   Give each task a stable phase-prefixed ID, dependency, owner, bounded scope
   and acceptance check. Link to this plan and the relevant W contract.
6. Implement and validate the phase within its authorized scope. Keep deferred
   requirements visible without generating detailed P2/P3 task lists early.
7. Record implementation, local validation, app acceptance and remote sync
   separately. Update the TODO and roadmap from actual evidence before advancing.

Suggested task IDs are `P0-01`, `P1F-01`, `P1-01`, `P2-01` and `P3-01`.
These are naming conventions, not tasks created by this document.

## Delivery sequence

P0 precedes the shared foundation (P1F), which precedes P1 operations and their
supervised acceptance. P2 builds on that foundation; P3 follows with additional
investment and relationship evidence. Native-reference research may overlap when
it has an isolated, authorized test environment and no shared-writer contention.

### Release branches and GitHub review

The first phase branch is `release/0.3.0`, created from `main` at
`5c6f346`. It carries the planning baseline: AGENTS, TODO, documentation index,
technical proposal and this implementation plan. The user selected `0.3.0` for
the new release. Product metadata will be aligned during release implementation;
this planning update does not change the installed product version.

| Work | Branch / PR target | Integration condition |
| --- | --- | --- |
| P0 documentation baseline | `release/0.3.0` | Documentation validation; separate from executable changes |
| Individual implementation | `feat/<task-id>-<topic>` from the owning phase branch | PR targets that phase branch; independent GitHub code review and required checks |
| P1F, P1, P2 and P3 | New `release/<phase>-<topic>` branch when that phase starts | Previous phase accepted and integrated; scope/tasks refined first |
| Completed phase | Release branch PR to `main` | Independent review, phase exit evidence and version/release decision |

Use the actual phase release branch as the review base, not `main`, for each
implementation PR. Each reviewer must be independent of the implementation agent
and inspect the current PR changes. Record review evidence on GitHub; address
actionable findings and rerun affected checks after changes before merging.
Local tests or self-review alone do not satisfy this requirement.

Track the phase branch, implementation branch, PR and review evidence against
each activated TODO task. Dependent task branches start from the release branch
after their prerequisites merge. An API dependency change follows the same phase
and independent-review discipline in its own repository, with cross-referenced
PRs and a deliberate tested pin/lock update in MoneyWiz Tools.

Create later phase branches from the accepted integration baseline. Avoid starting
future implementation on unreviewed predecessor changes. Implementation branching
and GitHub review are required workflow steps; commit, push, PR creation, merge,
tagging and publication still follow the user's execution authorization.

### P0: complete reads and runtime identity

Deliver reliable account, transaction and holding snapshots with source/parsed
counts, skipped-record diagnostics and explicit complete/partial/error status.
Scope loading so unrelated invalid models do not block an otherwise valid query.
Partial reads must prevent dependent write planning.

Cover nullable account metadata and safe post-construction diagnostics,
per-consumer price/quantity aliases, mixed schemas and missing investment rows.
Make cutoff, timezone and date-boundary semantics explicit. Export the relationships,
category splits, balances, quantities and flags required to verify planned writes.
Add graph audits for orphaned transfers, duplicate-event candidates and final flags;
candidate matching alone must not authorize a change.

Resolve an unambiguous app/store/model tuple, supporting the TestFlight target and
preserving existing supported paths. Bind store UUID, owner and exact model checksum
to subsequent plans. Explicit choices take precedence; ambiguity is an error.

Exit evidence: nullable-info and mixed-layout regressions, complete versus partial
snapshot tests, date-boundary tests, app/store ambiguity tests and the tested API
dependency available through the packaged runtime. No live write promotion occurs.

### P1F: shared writer foundation

Extract shared runtime identity and writer invocation from the payee helper.
Introduce versioned typed plans, expected old values, Decimal amounts, explicit
timezones, reviewed-plan digests, source-event identity and explicit apply.
Swift independently validates the contract, ownership and capability before mutation.

Preflight an entire coherent operation unit, save atomically, and return durable
IDs with per-operation status and independent read-back. Preserve v1 behavior.
Define consistent snapshots, journal persistence, app-closed checks, cooperating
writer serialization and recovery from an interrupted response. Process checks do
not provide atomic exclusion against MoneyWiz being relaunched externally.

Exit evidence: native rejection before mutation for invalid references and stale
plans; atomic rollback; crash-before-save and crash-after-save recovery; retry/no-op
behavior; private durable receipts; unchanged v1 reassignment tests; all modules
present in a relocatable bundle tested independently of the development checkout.

### P1: routine transaction writes

| Contract | Deliverable | Decisive evidence |
| --- | --- | --- |
| W01 | Create income, expense and supported refund transactions | Exact fields and balance delta; repeated source event creates no duplicate |
| W02 | Edit a supported transaction by ID | Expected-old-value guard; identity and unrelated fields preserved |
| W03 | Assign payee and category splits to explicit transaction IDs | Owner and split-total validation; deliberate relationship replacement; final read-back |
| W04 | Reconcile and unreconcile selected transactions | Complete verified source scope and balance guard; cleared/pending preserved; final flags correct |

Suggested order is W01, W02, W03, then W04; phase preparation may adjust it based
on fixture evidence. Reconcile and unreconcile require separate capability evidence.
Reconciled edits use the explicit correction flow. Unsupported transfer, adjustment,
scheduled and investment variants remain blocked.

Exit evidence: fixtures and negative paths for each variant, installed CLI checks,
minimal authorized TestFlight acceptance and a supervised reconciliation cycle.
Verify IDs and flags again after final edits. Report CLI coverage and GUI fallbacks
from observed outcomes; do not assume most operations have been automated.

The first delivery ends here. P2/P3 operations retain their existing supported
fallbacks until independently verified.

### P2: adjustments, deletion and transfers

| Contract | Deliverable | Evidence needed before implementation/promotion |
| --- | --- | --- |
| W05 | Create native Adjust Balance transactions | Target versus delta; cash/total/asset units; native date restrictions; matching-target no-op |
| W06 | Guarded deletion of supported records | Exact target and dependency inventory; native history/deletion behavior; no unrelated loss |
| W07 | Convert/link transfer and FX records | Native conversion or replacement rules; reciprocal links; actual amounts, fees, dates and duplicate prevention |

Require complete evidence for both accounts and both legs of a transfer. Preserve
source-event identity and report old/new IDs if conversion replaces objects. An
atomic graph repair must not leave one leg or duplicate cleanup partially committed.
Adjustment rows are distinct from reconciliation flags and opening-balance edits.

Resolve the native balance, backdating, fee, deletion and conversion questions
during phase preparation and bounded reference research. Include refund/instalment
repair recipes using verified primitives and the private user policy.

Exit evidence: native before/after comparisons, stale-state and interruption tests,
both FX directions, separate source dates, fee currencies, duplicate/orphan checks,
history preservation, app reopen and operation-specific sync acceptance.

### P3: investments and payee merges

| Contract | Deliverable | Decisive evidence |
| --- | --- | --- |
| W08 | Investment Buy/Sell and cash events | Explicit asset/quantity/price/commission; independent cash and holding changes; no fabricated units |
| W09 | Exact and approved fuzzy payee merges | Explicit survivor/owner; reviewed inputs only; complete reference migration and native deletion |

Aggregate investment proceeds represented as ordinary income may use verified W01
when the private accounting policy permits; this does not imply native Sell support.
Exact and fuzzy merges require separate capabilities. Pending/rejected candidates
remain unchanged; similarity does not authorize merging.

Exit evidence: holding/cash/fee reconciliation, relevant split/scheduled/history
relationships, review-map validation, repeated-operation safety and app/sync checks.

## Recovery journal and Obsidian reports

Recovery is a runtime feature used on every new write flow, as well as something
tested during development. It must work when an operation saves but confirmation
is lost. A receipt alone cannot resolve a crash between database save and receipt
creation: inspect persisted identities and postconditions before replaying.

Confirmed storage and retention design; command syntax remains to be designed:

- The CLI owns a private machine-readable journal under the platform's local
  application-data directory, independent of Obsidian or cloud availability.
- A journal entry records plan/digest, store/model identity, source references,
  intended operations, expected values, resulting IDs, outcomes and verification.
  Flush the prepared record before mutation; define persistence failure behavior.
- Readable private session reports in Obsidian reference journal entries and
  distinguish completed, pending, unknown and fallback actions.
- Retention is 90 days after successful final verification; unresolved entries
  remain until resolved. Obsidian reports remain indefinitely and are excluded
  from automatic journal pruning.

Expose effective journal, report and snapshot locations through a machine-readable
CLI discovery interface, including retention settings and configuration provenance.
Resolve the canonical vault from private configuration/project context. The generic
skill must consume discovered paths and report links without embedding a user's
absolute home path or relying on old session notes to locate artifacts.

Provide CLI-owned cleanup with a dry-run listing eligible entries, reasons and
estimated space, followed by an explicit apply operation. The skill should use
this interface under the confirmed retention policy instead of deleting files
with shell commands. Recheck eligibility and active-writer state at apply time;
preserve active, prepared, pending, unknown and failed/unresolved entries and
any evidence still referenced by them. Missing or malformed state means retain.
Snapshot retention needs its own policy during phase preparation; journal expiry
alone must not authorize removing recovery snapshots.

Include discovery, cleanup preview/apply, expired verified entries, unresolved
entries, active-writer races and custom storage paths in foundation tests. Keep a
minimal cleanup receipt without deleted financial payloads. Obsidian reports should
remain readable after journal expiry, with expired references clearly identified.

Keep financial payloads, account IDs, database snapshots and credentials out of
the repository and reusable skill. Never include credentials/OTPs in the journal.
Backups require a consistent snapshot including WAL state, not a main-file copy.
Do not promise automatic restoration after cloud sync; prefer verified corrective
operations under a tested recovery protocol.

## Reconciliation skill and fallback feedback

Update canonical `$moneywiz-reconcile` and its Codex discovery copy only as command
contracts and verified capabilities become available. Preserve the existing workflow
and private profile. CLI preference is decided per operation at runtime.

At session start, discover journal/report locations and effective retention through
the CLI. Record links in the private session checkpoint. At session close, preview
and apply eligible journal cleanup under the confirmed policy, report removals and
preserved unresolved entries, and retain Obsidian reports. If discovery or cleanup
is unsupported or fails, record the finding and preserve files. Do not teach the
skill proposed syntax before the corresponding CLI implementation is available.

1. Discover current capability and read completeness; build and review a plan.
2. Apply the supported operation within the authorized reconciliation scope.
3. Read back the result and verify affected balances, relationships and final flags.
4. For unsupported or confirmed-unapplied operations, use a supported targeted
   action or computer use when the identity and source evidence are sufficient.
5. For an unknown outcome, inspect persistence before any retry or GUI mutation.
   Missing identity, contradictory evidence or failed balance guards require
   resolution; GUI fallback must not bypass these conditions.
6. Save a private fallback finding with operation, capability, CLI/app/model
   versions, sanitized error, outcome classification, fallback and final read-back.
   Put a synthetic/redacted reproducer in the project backlog when appropriate.

Keep bookkeeping separate from tooling development: record CLI defects for a later
implementation task. Preserve iPhone Mirroring's real-interaction interval of at
most 45 seconds during every live import/reconciliation, including CLI work.

## Agent coordination

Use this task as the control point. At implementation time, create user-visible
implementation/control tasks when requested; use bounded subagents for delegated
work within a task. Creating this roadmap does not dispatch either kind of work.

| Role | Recommended model / reasoning | Ownership |
| --- | --- | --- |
| Main control | `gpt-6-astra` / `xhigh` | Phase scope, decisions, dependencies, integration and acceptance ledger |
| API/read worker | `gpt-6-astra` / `high` | P0 models, scoped loading, completeness and read regressions |
| Runtime identity worker | `gpt-6-astra` / `high` | App/store/model discovery and identity tests |
| Fixture/evidence worker | `gpt-5.6-sol` / `high` | Synthetic fixtures, native-reference comparisons and test scenarios |
| Foundation/native writer owner | `gpt-6-astra` / `xhigh` | Shared contract, persistence, recovery and later transfer semantics |
| Operation worker | `gpt-6-astra` / `high` | One bounded W operation and its tests; use `xhigh` for complex graph changes |
| Independent reviewer | `gpt-6-astra` / `high` | Changed-code review, negative paths and evidence sufficiency |
| Documentation/skill worker | `gpt-5.6-sol` / `medium` | Implemented command docs, verified capability guidance and skill checks |

These are recommendations, not fixed future availability; check supported model
and reasoning combinations when dispatching. Current capacity permits the controller
plus three subagents. Run roles in waves and reuse workers; no recursive hierarchy
of controllers is required.

Assign exclusive ownership of shared Swift host, CLI routing, compatibility register
and bundle manifests. Isolated P0 work may run concurrently; integrate shared changes
through one owner. Reviewers must independently inspect results. No parallel agents
may control the live MoneyWiz app/store; one operator owns live acceptance and keepalive.

## Validation and phase completion

For each operation, require complete reads, exact runtime identity, typed plans,
native preflight, atomic persistence and independent read-back before application
acceptance. Tests use synthetic/disposable stores. API database integration tests
require an explicit read-only-validated `MONEYWIZ_TEST_DB_PATH`; absence means skip.

Run relevant Python/native tests and installed-bundle checks. Run Markdown lint
using the user-wide config on modified Markdown, and `shellcheck --enable=all` on
modified shell scripts. Update command help, FUNCTIONS, compatibility/writer docs,
bundle manifests and changelog to match implemented behavior.

Record local read-back, MoneyWiz reopen/history acceptance and observed remote sync
as separate evidence. A missing remote observation is incomplete evidence. Enable
only capabilities that satisfy the existing live-write acceptance policy; do not
promote a whole model or phase based on one operation's success.

| Phase | Current state | Completion evidence |
| --- | --- | --- |
| P0 | First-delivery scope confirmed; tasks not yet refined | Pending |
| P1F | First-delivery scope and journal policy confirmed; interface/tasks to refine | Pending |
| P1 | First-delivery scope confirmed; operation tasks not yet refined | Pending |
| P2 | Roadmap only; prepare after earlier evidence | Pending |
| P3 | Roadmap only; prepare after earlier evidence | Pending |

At handoff, record completed task IDs, code/dependency revisions, tests, exact
capabilities enabled, private evidence references and remaining limitations.
Do not mark a phase complete solely because its code is implemented.
