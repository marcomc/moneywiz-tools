# Payee Consolidation

## Scope

`merge-duplicate-payees` consolidates only exact duplicate groups. It does not
apply the similar-name review map.

An exact group is scoped by MoneyWiz user and is equal only after:

1. Unicode NFKC normalization.
2. Whitespace collapse.
3. Case folding.

The command discovers the current count at execution time; no duplicate-group
count is assumed by the implementation or this document.

## Canonical payee selection

For each exact group, the survivor is selected in this order:

1. A name that is not entirely uppercase.
2. A name whose whitespace, if present, uses ASCII spaces.
3. The payee with the largest known reference count.
4. The smallest payee ID.

Known reference counts include `ZSYNCOBJECT.ZPAYEE2` and
`ZSTRINGHISTORYITEM.ZPAYEE`. This makes `Ita` preferred over `ITA`, and
`Lidl` preferred over `LIDL`.

## Exact merge workflow

~~~sh
moneywiz merge-duplicate-payees --show-plan

# Run the separate similar-name analysis only when an export is needed.
moneywiz merge-duplicate-payees \
  --fuzzy-map "$HOME/payee-fuzzy-review.csv"

# Quit MoneyWiz after sync has settled.
moneywiz merge-duplicate-payees --apply --show-plan
~~~

This legacy command's `--apply` is blocked by the compatibility gate before the
native host can open or mutate the store. Live application remains pending
until operation-specific Core Data and sync acceptance evidence is recorded.

### W09 reviewed merge plans

`moneywiz payee merge` builds a version-2 plan for one explicit source and
survivor. It reads the current Core Data graph without changing the store and
includes every transaction, string-history item, scheduled handler, payment
plan and info card that refers to the source. Review that inventory and the
digest before applying it to a **marked disposable model-48 store**:

~~~sh
moneywiz --db /private/path/disposable.sqlite payee merge \
  --kind exact --source-gid SOURCE_GID --survivor-gid SURVIVOR_GID \
  --evidence-note 'Reviewed exact duplicate' --app /Applications/MoneyWiz.app \
  --model '/Applications/MoneyWiz.app/Contents/Resources/MoneyWizDataModel.momd/MoneyWizDataModel 48.mom' \
  --owner OWNER_ID --plan /private/path/merge-plan.json
moneywiz write validate --plan /private/path/merge-plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/merge-plan.json --reviewed-digest REVIEWED_SHA256 \
  --app /Applications/MoneyWiz.app \
  --model '/Applications/MoneyWiz.app/Contents/Resources/MoneyWizDataModel.momd/MoneyWizDataModel 48.mom' \
  --owner OWNER_ID --apply
~~~

For a similar-name pair, select `--kind fuzzy` and supply the exported
`--fuzzy-map PATH`. Exactly one row must match the current owner, IDs and
names, have `review_decision=approved`, name the chosen survivor in
`approved_canonical_id`, and include review notes. `pending` and `rejected`
rows produce no plan or write. Exact merges require normalized names to match
and have their own capability; fuzzy approval never authorizes a different pair.

The native host rechecks the complete reference inventory, moves each relation
in one Core Data save, deletes the source and verifies the graph in a fresh
context. Recovery distinguishes an unchanged source from a completed merge.
Stale plans and unreviewed model relationships are refused. Both W09 live
capabilities remain blocked pending separate MoneyWiz reopen and sync acceptance.

The active MoneyWiz 2026 model exposes inbound
payee references from transactions, string history, scheduled transaction
handlers, payment plans, and info cards. `User.payees` is ownership metadata.
This inventory authorizes W09 mutation only on marked disposable stores.

## Similar-name approval map

`--fuzzy-map PATH` opts into the similar-name comparison pass and writes an
editable CSV. Without that option, exact-plan display and application do not
build fuzzy candidates. Every row begins with:

| Field | Meaning |
| --- | --- |
| `review_decision` | `pending`; no automatic action is possible. |
| `approved_canonical_id` | Blank until a reviewer chooses a survivor. |
| `review_notes` | Optional rationale for the decision. |

A pair enters this map when punctuation, whitespace, and diacritic removal
make the names equal, or the resulting compact character similarity is at
least `0.88`. A simple numeric suffix, such as `Lidl2` versus `Lidl`, is
excluded. Exact-normalized pairs are excluded because they are already part
of the exact merge plan.

The legacy exact-group command never reads approval fields to write fuzzy pairs.
The W09 reviewed merge planner reads only an explicitly supplied approved row.
Exported payee names beginning with `=`, `+`, `-`, or `@` receive a leading
apostrophe so spreadsheet applications keep the untrusted name as literal
text. Classification uses a Unicode NFKC view and ignores leading Unicode
whitespace and control characters, which also catches compatibility-equivalent
sigils and hidden formula prefixes. The apostrophe is added to the original
name; other names are preserved unchanged.

## Native behavior evidence

MoneyWiz 2026 exposes **Preferences > Payees > Edit**. After selecting two payees,
it asks which one should remain. The command mirrors that survivor/source
model, but uses a deterministic canonical rule for exact groups.

## Resolving a pending candidate

`pending` means that the candidate has not been reviewed. It is not a state
that `merge-duplicate-payees --apply` can resolve.

For each row, inspect the source and candidate payees and their transactions,
then record one of these reviewer decisions:

| Decision | Values to record | Next action |
| --- | --- | --- |
| Same merchant | `review_decision=approved`; set `approved_canonical_id` to the survivor; add rationale in `review_notes`. | Search both names in **Preferences > Payees > Edit**, use the IDs to select the records, then merge and choose the survivor. |
| Different merchants | `review_decision=rejected`; add rationale in `review_notes`. | Keep both payees. |
| Not enough evidence | Leave `review_decision=pending`; optionally add a note. | Take no write action. |

The legacy group command does not parse the CSV approval fields for mutation.
The W09 planner validates one approved row for a disposable merge. Editing a
row does not change the database.

### CSV editing example

Edit the review columns of the existing row; do not add a new row or change
the detected payee IDs and names:

~~~csv
user_id,similarity,reason,left_id,left_name,right_id,right_name,review_decision,approved_canonical_id,review_notes
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,pending,,
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,approved,1037,"Same merchant; keep payee 1037."
~~~

For a rejection, use `rejected`, leave `approved_canonical_id` empty, and
explain the decision in `review_notes`:

~~~csv
1,0.919,similarity>=0.88,1037,Merchant Example A,1892,Merchant Example B,rejected,,"Different merchants."
~~~

These values document the decision but are not consumed by the current CLI.
An approved merge must be performed through MoneyWiz's native
**Preferences > Payees > Edit** workflow: search both names, use the CSV IDs to
select the exact records, invoke merge, and choose the survivor.
