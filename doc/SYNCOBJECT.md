## ZSYNCOBJECT (SyncObject) — Deep Dive

MoneyWiz stores most business entities in a single Core Data table named `ZSYNCOBJECT`. Each row is a “SyncObject” and represents a typed entity such as an account, transaction, category, payee, tag, or investment holding.

### Typing and Identity

- `Z_ENT`: Integer type id. Maps to a human-readable type name via `Z_PRIMARYKEY` (`Z_NAME`).
- `ZGID`: Global identifier (UUID-like string) used for sync across devices.
- `Z_OPT`: Optimistic concurrency/version counter (Core Data). Incremented on updates.
- `Z_PK`: Primary key of the row.

Common columns you will encounter across entities (not exhaustive):
- `ZDATE1`: Core timestamp for the record (see Concepts for epoch details).
- `ZAMOUNT1`: Generic amount field (transactions).
- `ZDESC2`: Description (text field).
- `ZNOTES1`: Notes (optional text).
- `ZACCOUNT2`: Owning account for a transaction.
- `ZPAYEE2`: Payee for a transaction (optional).
- `ZUSER`: User id for user-scoped objects (e.g., accounts, categories, tags).

Entity-specific columns follow a naming convention rooted in the Core Data model. Examples:
- Accounts: `ZNAME`, `ZCURRENCYNAME`, `ZDISPLAYORDER`, `ZGROUPID`.
- Transactions (FX): `ZORIGINALAMOUNT`, `ZORIGINALCURRENCY`, `ZORIGINALEXCHANGERATE`, `ZORIGINALFEE`, `ZORIGINALFEECURRENCY`.
- Transfers: `ZSENDERACCOUNT`, `ZSENDERTRANSACTION`, `ZRECIPIENTACCOUNT1`, `ZRECIPIENTTRANSACTION`, `ZORIGINALSENDERAMOUNT`, `ZORIGINALRECIPIENTAMOUNT`.
- Investment: `ZINVESTMENTACCOUNT`, `ZNUMBEROFSHARES1`, `ZPRICEPERSHARE1`, `ZFEE2`, `ZFROMNUMBEROFSHARES`, `ZTONUMBEROFSHARES`.

Types observed in the API (resolved at runtime via `Z_PRIMARYKEY`):
- Accounts: `BankChequeAccount`, `BankSavingAccount`, `CashAccount`, `CreditCardAccount`, `LoanAccount`, `InvestmentAccount`, `ForexAccount`.
- Categories: `Category`.
- Payees: `Payee`.
- Tags: `Tag`.
- Investment: `InvestmentHolding`.
- Transactions: `DepositTransaction`, `WithdrawTransaction`, `RefundTransaction`, `ReconcileTransaction`, `TransferDepositTransaction`, `TransferWithdrawTransaction`, `TransferBudgetTransaction`, `InvestmentExchangeTransaction`, `InvestmentBuyTransaction`, `InvestmentSellTransaction`.

### Mapping to Models (API)

The API loads `ZSYNCOBJECT` rows and constructs typed models by looking up `Z_ENT → Z_NAME` from `Z_PRIMARYKEY`. Managers cache these objects and expose domain-specific helpers. Relationships are pulled from auxiliary tables (categories, tags, refunds).

Read path highlights:
- `Z_PRIMARYKEY` → map `Z_ENT` to type name.
- `ZSYNCOBJECT` → fetch rows for a set of type names.
- Build typed model objects from row dicts.
- Convert `ZDATE1` and other timestamps from Apple epoch (2001‑01‑01) to `datetime`.
- Convert numeric amounts to `Decimal` where precision matters.

Write path (scaffold):
- `insert_syncobject(typename, fields)` — resolve `Z_ENT` and insert into `ZSYNCOBJECT`, auto-filling `ZGID` and `Z_OPT`.
- `update_syncobject(pk, fields)` — patch fields for a row.
- `delete_syncobject(pk)` — delete a row (caution: ensure referential integrity first).
- Relationship inserts: category/tag/refund link tables (see Concepts).

### Practical Tips

- Always resolve `Z_ENT` from `Z_PRIMARYKEY` using the type name you’re targeting.
- Set `ZGID` (UUID) and `Z_OPT` for new rows; increment `Z_OPT` on updates if you enforce it.
- Respect signs and FX fields for transactions; paired transfers must be consistent across sides.
- Wrap multi-table changes in a transaction.
- Use dry‑run SQL previews to verify changes before applying to a real DB.

