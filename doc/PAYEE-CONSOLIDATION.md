# Payee Consolidation

## Scope

`merge-duplicate-payees` consolidates only exact duplicate groups. It does not
apply the similar-name review map.

An exact group is scoped by MoneyWiz user and is equal only after:

1. Unicode NFKC normalization.
2. Whitespace collapse.
3. Case folding.

The current inventory contains 33 such groups, but the command discovers the
current count at execution time rather than hard-coding it.

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
moneywiz merge-duplicate-payees --show-plan \
  --fuzzy-map "$HOME/payee-fuzzy-review.csv"

# Quit MoneyWiz after sync has settled.
moneywiz merge-duplicate-payees --apply --show-plan
~~~

`--apply` submits exact groups only through the bundled Core Data host. The
host moves every modeled inbound relationship that points at `Payee`, checks
that no supported reference remains on the source, then deletes the source
payee in the same Core Data save.

The active MoneyWiz 2026 model exposes inbound payee references from
transactions, string history, scheduled transaction handlers, payment plans,
and info cards. `User.payees` is ownership metadata and is removed naturally
when the source object is deleted.

## Similar-name approval map

`--fuzzy-map PATH` writes an editable CSV. Every row begins with:

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

The current command never reads the approval fields to write fuzzy pairs.
That future operation requires an explicit, separately reviewed design.

## Native behavior evidence

MoneyWiz 2026 exposes **Payees > Edit > Merge**. After selecting two payees,
it asks which one should remain. The command mirrors that survivor/source
model, but uses a deterministic canonical rule for exact groups.
