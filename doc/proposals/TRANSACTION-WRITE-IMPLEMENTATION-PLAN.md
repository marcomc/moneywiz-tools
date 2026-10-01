# Transaction write implementation plan

Status (2026-09-28): P0, P1F and P1/W01–W04 implementation is integrated on
`release/0.3.0` through W04 PR #9 at `1f91151`. W05 implementation of the
observed GBP investment-total variant is active on `feat/p2-w05-adjust-balance`;
its app and iCloud export acceptance is complete.
The user has confirmed that the complete P0/P1F/P1/P2/P3 roadmap, including
W01–W10, belongs to release `0.3.0`. W01–W04 are already integrated; keep each
remaining operation in a separate PR and leave new PRs open for user inspection.
Do not merge on the user's behalf. This 2026-09-28 decision supersedes the earlier
proposal to put P2/P3 in later releases.

Update (2026-09-30): the bounded W01–W09 contracts are integrated through
[PR #15](https://github.com/marcomc/moneywiz-tools/pull/15). The additional W05
ordinary balance, investment cash and existing-asset quantity variants are
integrated through PR #16 at `d037afb`; ordinary/cash/stock live trials, app
read-back, iCloud export and verified cleanup are complete. Forex quantity has
disposable-store coverage. The W06 supported-record deletion extension is
integrated through PR #17 at `9ffc516`; installed validation, fictional live
app/sync acceptance, exact cleanup and current-head Codex review are complete.
First-Buy holding creation is implemented as a separate W08 extension; installed
client trials, app/iCloud export and exact cleanup are complete. The active user
goal authorizes squash merge after local READY and
current-head clean Codex review. See the current
[Adjust Balance contract](../TRANSACTION-ADJUST-BALANCE.md) and TODO for gates.

Update (2026-10-01): `feat/investment-total-currencies` extends aggregate
investment-total Adjust Balance and latest-adjustment deletion to the reviewed
fiat/crypto catalogs. Precision and reporting rate are bound to the plan; old GBP
plans are preserved. Native EUR/crypto references, installed-client live trials,
app read-back, iCloud export/deletion and exact fictional-data cleanup passed.
Integration requires full installed validation and independent review.
Forex Exchange and second-device verification are outside this goal.

Update (2026-10-01): first-Buy holding creation is integrated through PR #18
at `1b126b1`. Aggregate investment-total creation and latest-adjustment deletion
now support the reviewed fiat/crypto currency catalogs through PR #19 at
`8328073`, preserving original GBP plans. Native non-GBP references, installed
validation, fictional live app/iCloud acceptance and exact cleanup are complete.
The release-to-main PR follows scoped remediation and current-head Codex review;
Forex Exchange holding creation and nonzero-fee transfer conversion remain
unsupported. Second-device verification is separate from the recorded app/export
proofs. Historical checkpoints below retain their original phase scope.

## Purpose and related documents

Make routine MoneyWiz reconciliation use verified CLI writes, with targeted
computer-use fallback and actionable evidence when the CLI cannot complete an
operation. Track development and application acceptance separately.

| Document | Responsibility |
| --- | --- |
| This plan | Delivery order, decisions, coordination, acceptance and progress |
| [Transaction write API proposal](TRANSACTION-WRITE-API.md) | Technical source map, W01–W10 operation contracts and evidence questions |
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
| Full implementation scope: P0/P1F/P1/P2/P3 and W01–W10 in `release/0.3.0`, with a separate PR per operation | W01–W09 confirmed on 2026-09-28; W10 added by the user on 2026-10-01 |
| Application admission | Supported official MoneyWiz bundle at build 449 or newer, with exact app/model/store checks; channel is not an admission criterion |
| Use Obsidian for private recovery/session information | Confirmed in principle |
| Create detailed TODO tasks progressively as each phase is prepared | Requested by user |
| Integrate the complete P0/P1F/P1/P2/P3 roadmap on `release/0.3.0`; separate operation branches and independent GitHub review | Confirmed by the user's 2026-09-28 scope decision; new PRs stay open for the user's merge |
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

The user authorizes coordination and implementation of the full P0/P1F/P1/P2/P3
roadmap, with separate W01–W09 PRs into `release/0.3.0`, including scoped commits,
pushes and review remediation. Leave each new PR open for user inspection; merging,
main-branch integration, release publication and fabricated production
transactions are outside this authority. Live financial writes require a separate
authorized real reconciliation scope. Routine technical choices proceed from the
confirmed requirements without repeating resolved questions.

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

P0 precedes the shared foundation (P1F), which precedes P1 operations. P2 builds
on that foundation; P3 follows with additional investment and relationship
evidence. All phases are within `release/0.3.0`; phase ordering remains a dependency
and review constraint, not a release-version split. Native-reference research may
overlap when it has an isolated, authorized test environment and no shared-writer
contention. App and sync acceptance remain separate from synthetic implementation
and are required before live capability promotion.

### Release branches and GitHub review

The first phase branch is `release/0.3.0`, created from `main` at
`5c6f346`. It carries the planning baseline: AGENTS, TODO, documentation index,
technical proposal and this implementation plan. The user selected `0.3.0` for
the new release. Product metadata will be aligned during release implementation;
this planning update does not change the installed product version.

| Work | Branch / PR target | Integration condition |
| --- | --- | --- |
| P0 documentation baseline | `release/0.3.0` | Documentation validation; separate from executable changes |
| Each W01–W10 implementation | Separate `feat/<task-id>-<topic>` branch from the current `release/0.3.0` head | PR targets `release/0.3.0`; independent GitHub review and required checks; leave open for user inspection |
| P0/P1F/P1/P2/P3 | Integrated sequentially on `release/0.3.0` | Respect prerequisites; refine phase tasks; synthetic validation does not promote live capability |
| Completed 0.3.0 delivery | Full planned scope on `release/0.3.0` | Required implementation and acceptance evidence complete; main merge and publication require separate authorization |

Use `release/0.3.0` as the review base for every operation PR, not `main` or a
separate P2/P3 release branch. Each reviewer must be independent of the
implementation agent and inspect the current PR changes. Record review evidence
on GitHub; address actionable findings and rerun affected checks before handing
the still-open PR to the user. Local tests or self-review alone do not satisfy
this requirement.

Run `$scoped-pre-pr-remediation` before PR creation and reach local `READY`.
Commit and push the implementation/remediations, create the PR, then run
`$codex-pr-review-remediation-loop` using the same coordinator and ledger.
Observe an existing active pass before requesting one; monitor each pass once.
After fixes, push and revalidate affected evidence. Before handoff, require local
`READY`, passing required checks and a verified clean Codex result for the current
pushed head. Leave the PR open; the user performs any merge after inspection.
Reuse unchanged evidence without skipping required gates.

Track each implementation branch, PR and review evidence against its TODO task.
Dependent task branches start from the advanced `release/0.3.0` head after their
prerequisites are integrated by the user. An API dependency change follows the same phase
and independent-review discipline in its own repository, with cross-referenced
PRs and a deliberate tested pin/lock update in MoneyWiz Tools.

Create each operation branch from the accepted `release/0.3.0` integration
baseline. Avoid starting dependent implementation on unreviewed or unintegrated
predecessor changes. Implementation branching and GitHub review are required
workflow steps; commit, push and PR creation are authorized, while merge, tagging
and publication remain with the user unless separately authorized.

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

W01 tasks are activated as `P1-W01-01` through `P1-W01-07` in TODO. Their
implementation scope is creation only; application and remote sync acceptance
are not authorized by the synthetic validation task. Live capabilities remain
blocked until those gates are directly evidenced. The operation contract is
recorded in [Transaction Creation](../TRANSACTION-CREATION.md).

W02 tasks are activated as `P1-W02-01` through `P1-W02-07` in TODO.
The [Transaction Editing](../TRANSACTION-EDITING.md) contract defines scalar
allowlist, unchanged relationships and reconciled rejection. Implementation and
synthetic validation do not authorize application acceptance or live writes.

W03 tasks are activated as `P1-W03-01` through `P1-W03-06` in TODO.
The [Transaction Assignment](../TRANSACTION-ASSIGNMENT.md) contract defines
exact prior/target relationships, deliberate replacement and unchanged balance.
Disposable validation does not authorize live writes.

W04 tasks are activated as `P1-W04-01` through `P1-W04-06` in TODO. Reconcile
and unreconcile have separate capability gates. The disposable contract binds a
complete full-account transaction inventory and requires exact old flags,
unchanged balance/status and independent read-back. Live source/app/sync
acceptance is separate.

Suggested order is W01, W02, W03, then W04; phase preparation may adjust it based
on fixture evidence. Reconcile and unreconcile require separate capability evidence.
Reconciled edits use the explicit correction flow. Unsupported transfer, adjustment,
scheduled and investment variants remain blocked.

Exit evidence: fixtures and negative paths for each variant, installed CLI checks,
minimal authorized TestFlight acceptance and a supervised reconciliation cycle.
Verify IDs and flags again after final edits. Report CLI coverage and GUI fallbacks
from observed outcomes; do not assume most operations have been automated.

The original first-delivery boundary ended after P1/W01–W04. By the user's
2026-09-28 decision, P2/P3 are also part of `release/0.3.0`; their operations
retain existing supported fallbacks until independently verified.

### P2: adjustments, deletion and transfers (within release 0.3.0)

| Contract | Deliverable | Evidence needed before implementation/promotion |
| --- | --- | --- |
| W05 | Create native Adjust Balance transactions | Target versus delta; cash/total/asset units; date rules for the installed build; matching-target no-op |
| W06 | Guarded deletion of supported records | Exact target and dependency inventory; native history/deletion behavior; no unrelated loss |
| W07 | Convert/link transfer and FX records | Native conversion or replacement rules; reciprocal links; actual amounts, fees, dates and duplicate prevention |
| W10 | Reassign recipient account on an existing transfer pair | Preserve both transaction identities and all non-account fields; same-owner distinct accounts; atomic reciprocal account-link update and persisted read-back |

Require complete evidence for both accounts and both legs of a transfer. Preserve
source-event identity and report old/new IDs if conversion replaces objects. An
atomic graph repair must not leave one leg or duplicate cleanup partially committed.
Adjustment rows are distinct from reconciliation flags and opening-balance edits.

Resolve the native balance, backdating, fee, deletion and conversion questions
during phase preparation and bounded reference research. Include refund/instalment
repair recipes using verified primitives and the private user policy.

W05 preparation is tracked as `P2-W05-01` through `P2-W05-06` in TODO. The
[reference contract](../TRANSACTION-ADJUST-BALANCE.md) records installed model
fields and the native examples still needed before writing an adjustment.
MoneyWiz 2026 release notes allow past dates; verify their effect in the
installed build instead of applying the older today-only rule.

Exit evidence: native before/after comparisons, stale-state and interruption tests,
both FX directions, separate source dates, fee currencies, duplicate/orphan checks,
history preservation, app reopen and operation-specific sync acceptance.

### P3: investments and payee merges (within release 0.3.0)

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

Confirmed storage and retention design; P1F command syntax is documented in
[Writer recovery](../WRITER-RECOVERY.md):

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
P1F snapshot policy: retain snapshots indefinitely. Journal expiry alone does not
authorize removing recovery snapshots; future pruning requires its own policy.

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

Use this task as the control point. For each future implementation branch and
pull request, create one user-visible Codex task as its owner. That same visible
owner handles review remediation, using bounded supporting subagents where useful,
while this task coordinates phase scope, dependencies, integration and acceptance.
Existing P0 branches predate this ownership rule and do not require duplicate
replacement tasks. Creating this roadmap does not dispatch any work.

| Role | Recommended model / reasoning | Ownership |
| --- | --- | --- |
| Main control | `gpt-6-astra` / `xhigh` | Phase scope, decisions, dependencies, integration and acceptance ledger |
| API/read worker | `gpt-5.6-sol` / `high` | P0 models, scoped loading, completeness and read regressions; escalate difficult contracts to Astra |
| Runtime identity worker | `gpt-5.6-sol` / `high` | App/store/model discovery and identity tests |
| Fixture/evidence worker | `gpt-5.6-sol` / `high` | Synthetic fixtures, native-reference comparisons and test scenarios |
| Foundation/native writer owner | `gpt-6-astra` / `xhigh` | Shared contract, persistence, recovery and later transfer semantics |
| Operation worker | `gpt-5.6-sol` / `high` | One bounded W operation and its tests; use Astra/high for difficult logic and Astra/xhigh for unresolved persistence contracts |
| Independent reviewer | `gpt-6-astra` / `high` | Changed-code review, negative paths and evidence sufficiency |
| Documentation/skill worker | `gpt-5.6-sol` / `high` | Implemented command docs, verified capability guidance and skill checks |

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
| P0 | Integrated on `release/0.3.0` | PR #3 merged at `374ebd4`; no live write promotion |
| P1F | Integrated on `release/0.3.0` | PR #4 merged; synthetic native/crash and relocated bundle evidence |
| P1 | W01–W04 code integrated on `release/0.3.0` | PR #9 merged at `1f91151`; app and sync acceptance pending |
| P2 | W05 observed variant verified on `feat/p2-w05-adjust-balance`; W06/W07 follow as separate PRs | All PRs target `release/0.3.0`; other W05 units remain blocked pending their own evidence |
| P3 | W08/W09 roadmap; prepare each after its prerequisites | Separate PRs target `release/0.3.0`; operation, app and sync evidence pending |

At handoff, record completed task IDs, code/dependency revisions, tests, exact
capabilities enabled, private evidence references and remaining limitations.
Do not mark a phase complete solely because its code is implemented.
