# Extension Roadmap

## Current capability boundary

| Capability | State |
| --- | --- |
| Read users, accounts, categories, payees, tags, transactions, holdings, and schema | Available through `moneywiz`. |
| Build a self-contained app and command symlinks | Available through Make targets. |
| Generic write helpers | Retired from the product CLI. |
| Live payee reassignment to an existing payee | Verified through Core Data. |
| Live payee reassignment that creates a destination payee | Verified through Core Data. |
| W01–W09 typed writer variants | Enabled on the reviewed live Setapp runtime; finite operation and runtime guards apply. |
| Live exact-normalized duplicate-payee merge | W09 reviewed pair apply enabled; legacy group apply blocked. |
| Similar-name payee merge | W09 consumes one explicitly approved CSV pair; pending and rejected rows are refused. |
| Graphical user interface | Planned. |

## Extension principles

- Keep the installed product relocatable: runtime dependencies belong inside
  MoneyWiz Tools.app.
- Separate an SQL preview or test-copy mutation from a proven live writer.
- Add live writes only after reconstructing the complete Core Data,
  persistent-history, and sync contract for that operation.
- Stop on ambiguous payee matches rather than selecting a candidate by
  heuristic.
- Record model version, entity mapping, and behavioral evidence with each
  new live writer.

## Next implementation candidates

### Existing similar-name approval workflow

W09 implements one exact or individually approved fuzzy pair. Its parser
requires an approved CSV row and checks the current identity and reference
inventory:

1. Read only rows marked approved.
2. Validate the selected canonical payee is still valid and belongs to the
   same user.
3. Present a fresh plan because names and reference counts may have changed.
4. Apply no unapproved or stale row.

The legacy group command exports the CSV without consuming it. The separate
`payee merge --kind fuzzy` planner consumes one approved row. See
[Payee Consolidation](PAYEE-CONSOLIDATION.md) for the current workflow.

### Additional live writers

The implemented refund and assignment variants are documented in
[Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md). Additional variants
require a narrow contract and native comparison evidence before live enablement.

### GUI

A future GUI should call the same dispatcher and Core Data host already
bundled in MoneyWiz Tools.app. It should not introduce a second standalone
writer bundle.
