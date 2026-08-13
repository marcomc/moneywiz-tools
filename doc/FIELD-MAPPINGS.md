# Field Mapping Cheat Sheet (First Draft)

> **Scope.** This file contains mapping evidence and SQL-oriented recipes for inspection, test fixtures, and copied databases. It is not an authorization to apply raw SQL changes to a live iCloud store. The only currently verified live payee write path is the bundled Core Data reassignment writer; see [Core Data Writer](CORE-DATA-WRITER.md) and [Live Payee Structure](LIVE-PAYEE-STRUCTURE.md).

This reference maps domain model fields used by the API to raw SQLite columns (primarily in `ZSYNCOBJECT`) as observed in the test database and the current model classes.

## Quick Index

- [Base Record](#base-record-all-entities)
- [Accounts](#accounts-zsyncobject-with-account-z_ent)
- [Categories](#categories-zsyncobject-category)
- [Payees](#payees-zsyncobject-payee)
- [Tags](#tags-zsyncobject-tag)
- [Investment Holding](#investment-holding-zsyncobject-investmentholding)
- [Transactions](#transactions--common-zsyncobject-transaction-base)
  - [Deposit](#deposittransaction-field-set)
  - [Withdraw](#withdrawtransaction-field-set)
  - [Refund](#refundtransaction-field-set)
  - [Transfer deposit](#transferdeposittransaction)
  - [Transfer withdraw](#transferwithdrawtransaction)
  - [Reconcile](#reconciletransaction-field-set)
  - [Investment buy](#investmentbuytransaction)
  - [Investment sell](#investmentselltransaction)
  - [Investment Exchange](#investmentexchangetransaction)
- [Relationship Tables](#relationship-tables-non-zsyncobject)
- [Useful Queries](#useful-queries)

Notes

- Timestamps: Many date columns are Apple epoch floats (seconds since 2001‑01‑01). The API converts via `utils.get_datetime` / `utils.get_date`.
- Amounts: The API converts floats to `Decimal` where used in models (see `RawDataHandler`).
- Not all columns are populated for all rows of a given type; signs and FX fields carry semantics described in `doc/CONCEPTS.md`.

## Base Record (all entities)

- id ← `Z_PK`
- gid ← `ZGID`
- ent/type ← `Z_ENT` (resolved to name via `Z_PRIMARYKEY.Z_NAME`)
- created_at ← `ZOBJECTCREATIONDATE`

## Accounts (ZSYNCOBJECT with account Z_ENT)

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

## Categories (ZSYNCOBJECT, `Category`)

- name ← `ZNAME2`
- parent_id ← `ZPARENTCATEGORY`
- type ← `ZTYPE2` (1=Expenses, 2=Income)
- user ← `ZUSER3`

## Payees (ZSYNCOBJECT, `Payee`)

- name ← `ZNAME5`
- user ← `ZUSER7`
- Live-write note: these are domain-field mappings only. Creating a payee in
  an iCloud store also requires the versioned persistence contract in
  `LIVE-WRITE-COMPATIBILITY.md`.

## Tags (ZSYNCOBJECT, `Tag`)

- name ← `ZNAME6`
- user ← `ZUSER8`

## Investment Holding (ZSYNCOBJECT, `InvestmentHolding`)

- account ← `ZINVESTMENTACCOUNT`
- opening_number_of_shares (optional) ← `ZOPENNINGNUMBEROFSHARES`
- number_of_shares ← `ZNUMBEROFSHARES`
- symbol ← `ZSYMBOL`
- holding_type (optional) ← `ZHOLDINGTYPE`
- description ← `ZDESC`
- price_per_share_available_online ← `ZISPRICEPERSHAREAVAILABLEONLINE` (1/0)
- _investment_object_type (internal) ← `ZINVESTMENTOBJECTTYPE`
- _cost_basis_of_missing_ob_shares (internal) ← `ZCOSTBASISOFMISSINGOBSHARES`

## Transactions — Common (ZSYNCOBJECT, `Transaction` base)

- reconciled ← `ZRECONCILED` (1/0)
- amount ← `ZAMOUNT1`
- description ← `ZDESC2`
- datetime ← `ZDATE1`
- notes (optional) ← `ZNOTES1`
- payee relationship ← `ZPAYEE2`; a direct live update must also produce the
  Core Data history and CloudKit changes described in
  `LIVE-WRITE-COMPATIBILITY.md`.

### DepositTransaction field set

- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (pos income, neg expense in DB; API uses sign as-is)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

### WithdrawTransaction field set

- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (neg expense, pos income)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

### RefundTransaction field set

- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (typically positive)
- payee (optional) ← `ZPAYEE2`
- original_currency ← `ZORIGINALCURRENCY`
- original_amount ← `ZORIGINALAMOUNT`
- original_exchange_rate (optional) ← `ZORIGINALEXCHANGERATE`

Related link: `ZWITHDRAWREFUNDTRANSACTIONLINK (ZREFUNDTRANSACTION -> ZWITHDRAWTRANSACTION)`

### ReconcileTransaction field set

- account ← `ZACCOUNT2`
- reconcile_amount (optional) ← `ZRECONCILEAMOUNT`
- reconcile_number_of_shares (optional) ← `ZRECONCILENUMBEROFSHARES`

### TransferDepositTransaction

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

### TransferWithdrawTransaction

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

### InvestmentBuyTransaction

- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (usually negative, includes fees)
- fee ← `ZFEE2`
- investment_holding ← `ZINVESTMENTHOLDING`
- number_of_shares ← `ZNUMBEROFSHARES1`
- price_per_share ← `ZPRICEPERSHARE1`

### InvestmentSellTransaction

- account ← `ZACCOUNT2`
- amount ← `ZAMOUNT1` (net after fees)
- fee ← `ZFEE2`
- investment_holding ← `ZINVESTMENTHOLDING`
- number_of_shares ← `ZNUMBEROFSHARES1`
- price_per_share ← `ZPRICEPERSHARE1`

### InvestmentExchangeTransaction

- account ← `ZACCOUNT2`
- from_investment_holding ← `ZFROMINVESTMENTHOLDING`
- from_symbol ← `ZFROMSYMBOL`
- to_investment_holding ← `ZTOINVESTMENTHOLDING`
- to_symbol ← `ZTOSYMBOL`
- from_number_of_shares ← `ZFROMNUMBEROFSHARES`
- to_number_of_shares ← `ZTONUMBEROFSHARES`
- original_fee ← `ZORIGINALFEE`
- original_fee_currency ← `ZORIGINALFEECURRENCY`

## Relationship Tables (non-ZSYNCOBJECT)

- Category splits: `ZCATEGORYASSIGMENT(ZTRANSACTION, ZCATEGORY, ZAMOUNT)`
- Tags bridge: `Z_36TAGS(Z_36TRANSACTIONS, Z_35TAGS)`
- Refund link: `ZWITHDRAWREFUNDTRANSACTIONLINK(ZREFUNDTRANSACTION, ZWITHDRAWTRANSACTION)`
- Users: `ZUSER(Z_PK, ZSYNCLOGIN)` referenced by several entity types

## Useful Queries

- Resolve type name for a row: `SELECT Z_NAME FROM Z_PRIMARYKEY WHERE Z_ENT = <Z_ENT>`
- Resolve Z_ENT for a type: `SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = '<TypeName>'`
- Fetch all rows of specific types: `SELECT * FROM ZSYNCOBJECT WHERE Z_ENT IN ( ... )`

---

This is a first draft synthesized from the test DB and the current API models. As new entity types or fields are encountered, extend this cheat sheet accordingly.

## Z_ENT → Z_NAME (from test DB)

|Z_ENT|Z_NAME|
|------:|:-------|
|1|AccountBudgetLink|
|2|CategoryAssigment|
|3|CommonSettings|
|4|Image|
|5|InvestmentAccountTotalValue|
|6|StringHistoryItem|
|7|SyncCommand|
|8|SyncObject|
|9|Account|
|10|BankChequeAccount|
|11|BankSavingAccount|
|12|CashAccount|
|13|CreditCardAccount|
|14|LoanAccount|
|15|InvestmentAccount|
|16|ForexAccount|
|17|AppSettings|
|18|Budget|
|19|Category|
|20|CustomFormsOption|
|21|CustomReport|
|22|Group|
|23|InfoCard|
|24|InvestmentHolding|
|25|OnlineBank|
|26|OnlineBankAccount|
|27|OnlineBankUser|
|28|Payee|
|29|PaymentPlan|
|30|PaymentPlanItem|
|31|ScheduledTransactionHandler|
|32|ScheduledDepositTransactionHandler|
|33|ScheduledTransferTransactionHandler|
|34|ScheduledWithdrawTransactionHandler|
|35|Tag|
|36|Transaction|
|37|DepositTransaction|
|38|InvestmentExchangeTransaction|
|39|InvestmentTransaction|
|40|InvestmentBuyTransaction|
|41|InvestmentSellTransaction|
|42|ReconcileTransaction|
|43|RefundTransaction|
|44|TransferBudgetTransaction|
|45|TransferDepositTransaction|
|46|TransferWithdrawTransaction|
|47|WithdrawTransaction|
|48|TransactionBudgetLink|
|49|User|
|50|WithdrawRefundTransactionLink|

## Retired raw-SQL routes

Earlier releases exposed raw-SQL create and update helpers. Those routes no
longer exist in either dispatcher. The field sets above remain mapping evidence
for inspection and fixture design, not runnable mutation recipes. A live
mutation requires an explicit verified capability and a dedicated Core Data
implementation.
