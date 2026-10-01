# Investment transactions

W08 creates one investment cash event or one Buy/Sell transaction on the exact
model-48 store. Live execution is admitted for supported MoneyWiz bundles at
build 449 or newer when the canonical store identity matches. Marked disposable
fixtures are supported regardless of bundle channel.
The plan binds an InvestmentAccount or ForexAccount, its owner and store identity, the account
currency, a source-event ID, and the expected cash state. A Buy/Sell also binds
an existing holding, its symbol and asset type, prior units, quantity, price and
fee. The native host saves once and verifies the result in a fresh Core Data
context.

## Plan and apply

~~~sh
moneywiz transaction investment --request /private/path/request.json \
  --plan /private/path/plan.json
moneywiz write validate --plan /private/path/plan.json
moneywiz --db /private/path/disposable.sqlite write apply \
  --plan /private/path/plan.json --reviewed-digest REVIEWED_SHA256 --apply
moneywiz --db /private/path/disposable.sqlite write recover \
  --plan /private/path/plan.json
~~~

Keep the request and plan private. The strict version-2 request has one
`operation` with `kind` set to `investment_income`, `investment_expense`,
`investment_buy` or `investment_sell`. All four require `account_mode`
(`aggregate` or `units`), `amount`, `occurred_at`, `fee_currency`,
`expected_prior_cash`, and explicit payee, category, tag and note fields.
The reviewed account's cached balance is zero; the plan derives final cash
from the prior cash and transaction amount.
An optional `description` is persisted and checked in the receipt. Cash is
rounded to cents when deriving the ledger balance, so historical floating-point
residue does not affect the cents-based contract. Holding units remain unrounded.

Income accepts `dividend`, `interest`, `sale_proceeds` or `other_income`;
expense accepts `fee` or `other_expense`. Each has exactly one category split
and no holding, quantity, unit price or transaction fee. An optional
`investment_symbol` records the cash event's source without creating a holding.
Cash events work in either account mode.

Buy and Sell require `account_mode: "units"`, an existing holding, positive
quantity and unit price, nonnegative fee in the account currency, and explicit
prior units. Buy amount is `-(quantity × price + fee)`; Sell amount is
`quantity × price - fee`. The plan derives final units and cash, and rejects a
negative resulting unit count. Trades have no category split or cash-event
type. Zero-value, FX and assetless trades are outside this contract.

## First Buy creating a holding

`investment_buy_new_holding` uses the separate
`write.investment-buy-new-holding` capability on marked disposable model-48
stores and the reviewed Setapp runtime. It creates one manual `InvestmentHolding` and its
first Buy in the same save. Existing-holding Buy/Sell keep their existing contract.

Use the same request fields as Buy, with `holding_gid: null`, `asset_type: 0`,
`expected_prior_units: "0"`, and explicit `holding_type` and
`holding_description` strings. `holding_type` must be a choice from the native
investment editor, such as `Stock`, `ETF`, `Commodity` or `Other`.
The plan derives the native holding GID as `account_gid-symbol-0`. Quantity
supports at most eight decimal places. The holding has zero opening shares,
the reviewed unit price, and an NSDate-keyed manual price entry at UTC midnight
on the transaction date. Online-price and online-banking flags remain off.

The first Buy works in an empty InvestmentAccount or alongside other holdings.
It refuses an existing symbol in that account, a colliding GID, another owner,
stale cash, and a holding without its corresponding Buy. Replay verifies both
objects and returns their durable identities. The receipt includes
`holding_creation`; the Python client checks its GID, type, description and URI.

Native Forex accounts create currency holdings through Exchange, which is a
distinct operation. This first-Buy contract does not create Forex holdings.

Authorized fictional Setapp trials verified first Buy and subsequent Buy/Sell
through the installed client, journal replay/recovery, native app cash and units,
and operation-specific iCloud export. All new trial transactions and the empty
fictional holding were removed; existing financial history, holding metadata and
the intentionally retained TEST rows matched the baseline after app sync.
Second-device acceptance was not performed for these temporary records.

The host verifies the account and holding ownership, cash and unit history,
then checks the persisted transaction and derived state. Replay returns a
verified no-op; recovery distinguishes an unchanged store from a completed
save and refuses partial or ambiguous state. See [Writer Recovery](WRITER-RECOVERY.md)
for journal handling. Reopen MoneyWiz after a live write and confirm its balance,
history and sync state.
