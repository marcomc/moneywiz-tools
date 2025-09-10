## Field Mapping Cheat Sheet (First Draft)

This reference maps domain model fields used by the API to raw SQLite columns (primarily in `ZSYNCOBJECT`) as observed in the test database and the current model classes.

Notes
- Timestamps: Many date columns are Apple epoch floats (seconds since 2001‑01‑01). The API converts via `utils.get_datetime` / `utils.get_date`.
- Amounts: The API converts floats to `Decimal` where used in models (see `RawDataHandler`).
- Not all columns are populated for all rows of a given type; signs and FX fields carry semantics described in `doc/CONCEPTS.md`.

### Base Record (all entities)
- id ← `Z_PK`
- gid ← `ZGID`
- ent/type ← `Z_ENT` (resolved to name via `Z_PRIMARYKEY.Z_NAME`)
- created_at ← `ZOBJECTCREATIONDATE`

### Accounts (ZSYNCOBJECT with account Z_ENT)
Model: `Account` and subtypes
- display_order ← `ZDISPLAYORDER`
- group_id ← `ZGROUPID`
- name ← `ZNAME`
- currency ← `ZCURRENCYNAME`
- opening_balance ← `ZOPENINGBALANCE`
- info (optional) ← `ZINFO`
- user ← `ZUSER`

Subtypes (same columns, distinguished by type name):
- `BankChequeAccount`, `BankSavingAccount`, `CashAccount`, `CreditCardAccount` (+ `ZSTATEMENTENDDAY`), `LoanAccount`, `InvestmentAccount`, `ForexAccount`.

### Categories (ZSYNCOBJECT, `Category`)
- name ← `ZNAME2`
- parent_id ← `ZPARENTCATEGORY`
- type ← `ZTYPE2` (1=Expenses, 2=Income)
- user ← `ZUSER3`

### Payees (ZSYNCOBJECT, `Payee`)
- name ← `ZNAME5`
- user ← `ZUSER7`

### Tags (ZSYNCOBJECT, `Tag`)
- name ← `ZNAME6`
- user ← `ZUSER8`

### Investment Holding (ZSYNCOBJECT, `InvestmentHolding`)
- account ← `ZINVESTMENTACCOUNT`
- opening_number_of_shares (optional) ← `ZOPENNINGNUMBEROFSHARES`
- number_of_shares ← `ZNUMBEROFSHARES`
- symbol ← `ZSYMBOL`
- holding_type (optional) ← `ZHOLDINGTYPE`
- description ← `ZDESC`
- price_per_share_available_online ← `ZISPRICEPERSHAREAVAILABLEONLINE` (1/0)
- _investment_object_type (internal) ← `ZINVESTMENTOBJECTTYPE`
- _cost_basis_of_missing_ob_shares (internal) ← `ZCOSTBASISOFMISSINGOBSHARES`

### Transactions — Common (ZSYNCOBJECT, `Transaction` base)
- reconciled ← `ZRECONCILED` (1/0)
- amount ← `ZAMOUNT1`
- description ← `ZDESC2`
- datetime ← `ZDATE1`
- notes (optional) ← `ZNOTES1`

#### DepositTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (pos income, neg expense in DB; API uses sign as-is)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

#### WithdrawTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (neg expense, pos income)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

#### RefundTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (typically positive)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

Related link: `ZWITHDRAWREFUNDTRANSACTIONLINK (ZREFUNDTRANSACTION -> ZWITHDRAWTRANSACTION)`

#### ReconcileTransaction
- account ← `ZACCOUNT2`
- reconcile_amount (optional) ← `ZRECONCILEAMOUNT`
- reconcile_number_of_shares (optional) ← `ZRECONCILENUMBEROFSHARES`

#### TransferDepositTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (pos on deposit side)
- sender_account ← `ZSENDERACCOUNT`
- sender_transaction ← `ZSENDERTRANSACTION`
- original_amount ← `ZORIGINALAMOUNT` (abs handled in API)
- original_currency (may be blank) ← `ZORIGINALCURRENCY`
- sender_amount ← `ZORIGINALSENDERAMOUNT`
- sender_currency (may be blank) ← `ZORIGINALSENDERCURRENCY`
- original_fee (optional) ← `ZORIGINALFEE`
- original_fee_currency (optional) ← `ZORIGINALFEECURRENCY`
- original_exchange_rate ← `ZORIGINALEXCHANGERATE`

#### TransferWithdrawTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (neg on withdraw side)
- recipient_account ← `ZRECIPIENTACCOUNT1`
- recipient_transaction ← `ZRECIPIENTTRANSACTION`
- original_amount ← `ZORIGINALAMOUNT` (neg)
- original_currency (may be blank) ← `ZORIGINALCURRENCY`
- recipient_amount ← `ZORIGINALRECIPIENTAMOUNT` (abs handled/derived)
- recipient_currency (may be blank) ← `ZORIGINALRECIPIENTCURRENCY`
- original_fee (optional) ← `ZORIGINALFEE`
- original_fee_currency (optional) ← `ZORIGINALFEECURRENCY`
- original_exchange_rate ← `ZORIGINALEXCHANGERATE`

#### InvestmentBuyTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (usually negative, includes fees)
- fee ← `ZFEE2`
- investment_holding ← `ZINVESTMENTHOLDING`
- number_of_shares ← `ZNUMBEROFSHARES1`
- price_per_share ← `ZPRICEPERSHARE1`

#### InvestmentSellTransaction
- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (net after fees)
- fee ← `ZFEE2`
- investment_holding ← `ZINVESTMENTHOLDING`
- number_of_shares ← `ZNUMBEROFSHARES1`
- price_per_share ← `ZPRICEPERSHARE1`

#### InvestmentExchangeTransaction
- account ← `ZACCOUNT2`
- from_investment_holding ← `ZFROMINVESTMENTHOLDING`
- from_symbol ← `ZFROMSYMBOL`
- to_investment_holding ← `ZTOINVESTMENTHOLDING`
- to_symbol ← `ZTOSYMBOL`
- from_number_of_shares ← `ZFROMNUMBEROFSHARES`
- to_number_of_shares ← `ZTONUMBEROFSHARES`
- original_fee ← `ZORIGINALFEE`
- original_fee_currency ← `ZORIGINALFEECURRENCY`

### Relationship Tables (non-ZSYNCOBJECT)
- Category splits: `ZCATEGORYASSIGMENT(ZTRANSACTION, ZCATEGORY, ZAMOUNT)`
- Tags bridge: `Z_36TAGS(Z_36TRANSACTIONS, Z_35TAGS)`
- Refund link: `ZWITHDRAWREFUNDTRANSACTIONLINK(ZREFUNDTRANSACTION, ZWITHDRAWTRANSACTION)`
- Users: `ZUSER(Z_PK, ZSYNCLOGIN)` referenced by several entity types

### Useful Queries
- Resolve type name for a row: `SELECT Z_NAME FROM Z_PRIMARYKEY WHERE Z_ENT = <Z_ENT>`
- Resolve Z_ENT for a type: `SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = '<TypeName>'`
- Fetch all rows of specific types: `SELECT * FROM ZSYNCOBJECT WHERE Z_ENT IN ( ... )`

---

This is a first draft synthesized from the test DB and the current API models. As new entity types or fields are encountered, extend this cheat sheet accordingly.

## Z_ENT → Z_NAME (from test DB)

| Z_ENT | Z_NAME |
|------:|:-------|
| 1 | AccountBudgetLink |
| 2 | CategoryAssigment |
| 3 | CommonSettings |
| 4 | Image |
| 5 | InvestmentAccountTotalValue |
| 6 | StringHistoryItem |
| 7 | SyncCommand |
| 8 | SyncObject |
| 9 | Account |
| 10 | BankChequeAccount |
| 11 | BankSavingAccount |
| 12 | CashAccount |
| 13 | CreditCardAccount |
| 14 | LoanAccount |
| 15 | InvestmentAccount |
| 16 | ForexAccount |
| 17 | AppSettings |
| 18 | Budget |
| 19 | Category |
| 20 | CustomFormsOption |
| 21 | CustomReport |
| 22 | Group |
| 23 | InfoCard |
| 24 | InvestmentHolding |
| 25 | OnlineBank |
| 26 | OnlineBankAccount |
| 27 | OnlineBankUser |
| 28 | Payee |
| 29 | PaymentPlan |
| 30 | PaymentPlanItem |
| 31 | ScheduledTransactionHandler |
| 32 | ScheduledDepositTransactionHandler |
| 33 | ScheduledTransferTransactionHandler |
| 34 | ScheduledWithdrawTransactionHandler |
| 35 | Tag |
| 36 | Transaction |
| 37 | DepositTransaction |
| 38 | InvestmentExchangeTransaction |
| 39 | InvestmentTransaction |
| 40 | InvestmentBuyTransaction |
| 41 | InvestmentSellTransaction |
| 42 | ReconcileTransaction |
| 43 | RefundTransaction |
| 44 | TransferBudgetTransaction |
| 45 | TransferDepositTransaction |
| 46 | TransferWithdrawTransaction |
| 47 | WithdrawTransaction |
| 48 | TransactionBudgetLink |
| 49 | User |
| 50 | WithdrawRefundTransactionLink |

## Per-type “Create” Recipes

The following recipes illustrate the minimal field sets to create objects via the SQL preview tool. All commands are dry-run unless `--apply` is provided; test on a DB copy.

### DepositTransaction

JSON fields template:
```json
{
  "ZACCOUNT2": <account_id>,
  "ZAMOUNT1": <amount_pos_or_neg>,
  "ZDATE1": <apple_epoch_seconds>,
  "ZDESC2": "<description>",
  "ZPAYEE2": <payee_id_or_null>,
  "ZORIGINALAMOUNT": <orig_amount>,
  "ZORIGINALCURRENCY": "<CUR>",
  "ZORIGINALEXCHANGERATE": <rate_or_null>
}
```

Example (preview):
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type DepositTransaction \
  --fields '{"ZACCOUNT2":5309, "ZAMOUNT1": 12.34, "ZDATE1": 700000000, "ZDESC2":"Salary", "ZPAYEE2": null, "ZORIGINALAMOUNT": 12.34, "ZORIGINALCURRENCY":"GBP", "ZORIGINALEXCHANGERATE": 1.0}'
```

### WithdrawTransaction

Template: same as Deposit, amounts usually negative; include FX if needed.

Example:
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type WithdrawTransaction \
  --fields '{"ZACCOUNT2":5309, "ZAMOUNT1": -3.50, "ZDATE1": 700000000, "ZDESC2":"Coffee", "ZPAYEE2": 1002, "ZORIGINALAMOUNT": -3.50, "ZORIGINALCURRENCY":"GBP", "ZORIGINALEXCHANGERATE": 1.0}'
```

### RefundTransaction

Template: positive amount refund; link to original withdraw separately (see `link-refund`).

Example create + link:
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type RefundTransaction \
  --fields '{"ZACCOUNT2":7151, "ZAMOUNT1": 0.01, "ZDATE1": 700000100, "ZDESC2":"Refund of X", "ZORIGINALAMOUNT": 0.01, "ZORIGINALCURRENCY":"GBP", "ZORIGINALEXCHANGERATE": 1.0}'

# Suppose refund got Z_PK=9001; link to withdraw 7753
./moneywiz.sh sql-preview --db tests/test_db.sqlite link-refund --refund 9001 --withdraw 7753
```

### Transfer (paired)

Create both sides and cross-link with ZRECIPIENTTRANSACTION/ZSENDERTRANSACTION afterward (or use a higher-level helper when available).

TransferWithdraw side (origin account):
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type TransferWithdrawTransaction \
  --fields '{"ZACCOUNT2":4712, "ZAMOUNT1": -200.0, "ZDATE1": 700000000, "ZDESC2":"Cash top-up", "ZORIGINALAMOUNT": -200.0, "ZORIGINALCURRENCY":"USD", "ZORIGINALEXCHANGERATE": 1.0, "ZORIGINALRECIPIENTAMOUNT": 200.0, "ZRECIPIENTACCOUNT1": 7824}'
```

TransferDeposit side (destination account):
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type TransferDepositTransaction \
  --fields '{"ZACCOUNT2":7824, "ZAMOUNT1": 200.0, "ZDATE1": 700000000, "ZDESC2":"Cash top-up", "ZORIGINALAMOUNT": 200.0, "ZORIGINALCURRENCY":"USD", "ZORIGINALEXCHANGERATE": 1.0, "ZORIGINALSENDERAMOUNT": -200.0, "ZSENDERACCOUNT": 4712}'
```

After both inserts, update each side to set `ZRECIPIENTTRANSACTION` / `ZSENDERTRANSACTION` with the new counterpart Z_PK (use `sql-preview update`).

### ReconcileTransaction

```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type ReconcileTransaction \
  --fields '{"ZACCOUNT2":7523, "ZDATE1": 700010000, "ZDESC2":"New balance", "ZRECONCILEAMOUNT": 1146.45}'
```

### InvestmentBuyTransaction / InvestmentSellTransaction

Buy (amount usually negative, includes fee):
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type InvestmentBuyTransaction \
  --fields '{"ZACCOUNT2":7824, "ZAMOUNT1": -204.43, "ZDATE1": 700000000, "ZDESC2":"AAPL", "ZFEE2": 0.00, "ZINVESTMENTHOLDING": 9647, "ZNUMBEROFSHARES1": 1.0, "ZPRICEPERSHARE1": 204.43}'
```

Sell:
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type InvestmentSellTransaction \
  --fields '{"ZACCOUNT2":7824, "ZAMOUNT1": 7.95, "ZDATE1": 700100000, "ZDESC2":"SNAP", "ZFEE2": 0.00, "ZINVESTMENTHOLDING": 10182, "ZNUMBEROFSHARES1": 0.5, "ZPRICEPERSHARE1": 15.90}'
```

Exchange (shares move between holdings):
```bash
./moneywiz.sh sql-preview --db tests/test_db.sqlite insert \
  --type InvestmentExchangeTransaction \
  --fields '{"ZACCOUNT2":7824, "ZFROMINVESTMENTHOLDING": 1, "ZFROMSYMBOL":"FOO", "ZTOINVESTMENTHOLDING": 2, "ZTOSYMBOL":"BAR", "ZFROMNUMBEROFSHARES": -10.0, "ZTONUMBEROFSHARES": 10.0, "ZORIGINALFEE": 0.0, "ZORIGINALFEECURRENCY":"BAR"}'
```
