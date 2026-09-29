# Investment transactions

W08 creates one investment cash event or one Buy/Sell transaction on a marked
disposable model-48 store. The plan binds an InvestmentAccount, its owner and
store identity, the account currency, a source-event ID, and the expected cash
state. A Buy/Sell also binds an existing holding, its symbol and asset type,
prior units, quantity, price and fee. The native host saves once and verifies
the result in a fresh Core Data context. Live W08 capabilities remain blocked.

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

The host verifies the account and holding ownership, cash and unit history,
then checks the persisted transaction and derived state. Replay returns a
verified no-op; recovery distinguishes an unchanged store from a completed
save and refuses partial or ambiguous state. See [Writer Recovery](WRITER-RECOVERY.md)
for journal handling. MoneyWiz reopen and sync acceptance are still required
before any live capability can be enabled.
