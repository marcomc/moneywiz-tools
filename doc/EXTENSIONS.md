# Extension Roadmap

## Current capability boundary

| Capability | State |
| --- | --- |
| Read users, accounts, categories, payees, tags, transactions, holdings, and schema | Available through `moneywiz`. |
| Build a self-contained app and command symlinks | Available through Make targets. |
| Generic write helpers | Retired from the product CLI. |
| Live payee reassignment to an existing payee | Verified through Core Data. |
| Live payee reassignment that creates a destination payee | Verified through Core Data. |
| Live exact-normalized duplicate-payee merge | Planning only; native apply remains blocked. |
| Similar-name payee merge | Approval-map generation only. |
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

### Similar-name approval workflow

Exact-normalized groups now have a deterministic plan, but no native mutation
path. A future implementation also needs an explicit parser for an approved
fuzzy CSV:

1. Read only rows marked approved.
2. Validate the selected canonical payee is still valid and belongs to the
   same user.
3. Present a fresh plan because names and reference counts may have changed.
4. Apply no unapproved or stale row.

The current command intentionally exports the CSV but never consumes it.

### Additional live writers

Potential writers include categories, tags, refunds, and other relationship
updates. Each requires a narrow contract and native comparison evidence
before it is offered against the live iCloud store.

### GUI

A future GUI should call the same dispatcher and Core Data host already
bundled in MoneyWiz Tools.app. It should not introduce a second standalone
writer bundle.
