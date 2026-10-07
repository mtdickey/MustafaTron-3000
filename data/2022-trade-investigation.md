# 2022 ESPN trade investigation

Investigated October 7, 2026. Live authenticated requests used the local `mustafa` conda environment (Python 3.13.5). Windows ROOT/CA certificates plus certifi enabled verified HTTPS. The investigation did not change environment packages. The follow-up fix now uses executed records in the pipeline and refreshed caches; the comparisons below describe the original inferred ledger.

## Finding

`mTransactions2` is incomplete for player packages. `kona_playercard` returns all 14 executed 2022 trades with complete items. All 14 accepted proposal roots are recovered; playercard-derived counts match ESPN for all 10 teams. The weekly-roster reconstruction emits 16 trades, including four sides receiving nothing.

The collector did not discard standalone TRADE records in this live response: there were none. It discarded unlinked/canceled proposals, but the accepted trade packages were missing from that view before filtering. The executed records available through player cards were never requested.

## Exact recovery request

GET the existing 2022 league endpoint with `view=kona_playercard`. Header:

```json
{"players":{"filterIds":{"value":[2577327,4248528,4697815]}}}
```

The investigation queried all 2022 cached player IDs in batches of 100, recursively found trade transaction objects, and deduplicated by transaction ID. Repeated appearances across player cards must not be counted as separate trades. Require `status == EXECUTED`; use only `items[].type == TRADE` for the exchanged package, and preserve embedded DROP items separately. Records include actual processDate, scoringPeriodId, and relatedTransactionId. Acceptance and execution IDs differ; link through the related proposal root. `isPending` is true even on these EXECUTED records, so it is not a reliable completion filter.

## Actual trades

| Week | Team receives | Other team receives |
|---|---|---|
| 4 | joyce: Brandon Aiyuk | edwards: Kareem Hunt |
| 4 | richardson: Jeff Wilson Jr., Jerry Jeudy | edwards: Amari Cooper |
| 4 | grudee: Mike Evans | wolfe: James Robinson |
| 5 | richardson: Drake London | edwards: Raheem Mostert |
| 5 | edwards: Khalil Herbert, Chris Godwin, Christian Kirk | grudee: Darrell Henderson Jr., Dalvin Cook |
| 5 | dickey: Michael Gallup | hunter: Travis Etienne Jr. |
| 7 | dickey: Broncos D/ST, Darrell Henderson Jr. | edwards: Eagles D/ST |
| 9 | richardson: Geno Smith, Deon Jackson | grudee: Justin Tucker |
| 9 | richardson: Tua Tagovailoa | hunter: Jerry Jeudy |
| 10 | edwards: Tyler Lockett | carpenter: Raheem Mostert, Kareem Hunt |
| 10 | richardson: Chris Godwin, Tyler Lockett | edwards: Chase Claypool, Geno Smith, James Conner |
| 13 | richardson: Chris Olave, Dameon Pierce | grudee: Tyler Lockett, Jeff Wilson Jr. |
| 13 | edwards: Rachaad White | grudee: Christian Watson |
| 13 | richardson: Justin Tucker, Christian Watson, Tyler Lockett | grudee: DeAndre Hopkins |

## Count verification

| Manager | ESPN | Current inferred | Recovered |
|---|---:|---:|---:|
| grudee | 6 | 5 | 6 |
| albert | 0 | 0 | 0 |
| wilkins | 0 | 0 | 0 |
| joyce | 1 | 1 | 1 |
| hunter | 2 | 2 | 2 |
| dickey | 2 | 2 | 2 |
| edwards | 8 | 9 | 8 |
| richardson | 7 | 8 | 7 |
| carpenter | 1 | 2 | 1 |
| wolfe | 1 | 1 | 1 |

## Valuation impact

Diagnostic only: the existing valuation engine was run against recovered packages using their execution scoring period. This does not update the published report. The current engine estimates hypothetical rest-of-season lineup value and does not model every downstream trade counterfactual.

| Ledger | Week | Manager | Received | Sent | ROS lineup point change |
|---|---:|---|---|---|---:|
| Current | 10 | edwards | Geno Smith, James Conner, Chase Claypool | Chris Godwin | +32.14 |
| Current | 10 | richardson | Chris Godwin | Geno Smith, James Conner, Chase Claypool | -26.14 |
| Current | 10 | carpenter | nothing | Tyler Lockett | -18.80 |
| Current | 10 | richardson | Tyler Lockett | nothing | +19.20 |
| Current | 10 | carpenter | Raheem Mostert, Kareem Hunt | nothing | +12.40 |
| Current | 10 | edwards | nothing | Raheem Mostert, Kareem Hunt | -10.20 |
| Current | 13 | edwards | Rachaad White | nothing | +4.90 |
| Current | 13 | grudee | nothing | Rachaad White | -10.80 |
| Current | 13 | grudee | DeAndre Hopkins, Jeff Wilson Jr. | Justin Tucker, Dameon Pierce, Chris Olave | -15.60 |
| Current | 13 | richardson | Justin Tucker, Dameon Pierce, Chris Olave | DeAndre Hopkins, Jeff Wilson Jr. | +7.20 |
| Current | 13 | edwards | nothing | Christian Watson | -13.60 |
| Current | 13 | richardson | Christian Watson | nothing | +14.90 |
| Recovered | 10 | carpenter | Raheem Mostert, Kareem Hunt | Tyler Lockett | -7.70 |
| Recovered | 10 | edwards | Tyler Lockett | Raheem Mostert, Kareem Hunt | +9.90 |
| Recovered | 10 | edwards | Geno Smith, James Conner, Chase Claypool | Tyler Lockett, Chris Godwin | +21.14 |
| Recovered | 10 | richardson | Tyler Lockett, Chris Godwin | Geno Smith, James Conner, Chase Claypool | -2.04 |
| Recovered | 13 | grudee | DeAndre Hopkins | Justin Tucker, Tyler Lockett, Christian Watson | -49.20 |
| Recovered | 13 | richardson | Justin Tucker, Tyler Lockett, Christian Watson | DeAndre Hopkins | +31.40 |
| Recovered | 13 | grudee | Tyler Lockett, Jeff Wilson Jr. | Dameon Pierce, Chris Olave | +15.40 |
| Recovered | 13 | richardson | Dameon Pierce, Chris Olave | Tyler Lockett, Jeff Wilson Jr. | -9.10 |
| Recovered | 13 | edwards | Rachaad White | Christian Watson | -10.50 |
| Recovered | 13 | grudee | Christian Watson | Rachaad White | +7.60 |

## Other probes

- Unfiltered mTransactions2, weeks 0-18: 46 TRADE_PROPOSAL, 25 TRADE_DECLINE, 16 TRADE_ACCEPT, 14 TRADE_UPHOLD; no standalone TRADE records. Only two accepted packages carry TRADE items.
- Communication/activity feed: HTTP 404 for 2022 on both reads and communication hosts, with and without trailing slash.
- Current espn-api upstream explicitly supports filling incomplete trade acceptances from player cards: https://github.com/cwendt94/espn-api/blob/master/espn_api/football/league.py (transactions, fill_trade_items). The installed conda library predates that option.

## Implementation implications

Use playercard executed trades as the authoritative ledger; weekly ownership inference should serve as a consistency check or explicitly labeled fallback. Refresh the cached transaction dataset, transform actual trade items into sides grouped by transaction/proposal ID rather than team-pair/week, remove the tolerated 2022 count drift, and rebuild trade valuations and dependent awards. Reconcile completeness against each team's ESPN counter and preserve actual execution dates. Cross-season validation below confirms this source for 2019-2025; retain an explicit fallback for 2018.

The old data notes that every team's net weekly players remain right are insufficient: week 13 combines direct and intermediate movements into incorrect counterparty packages, and Lockett completes a round trip within the week. Net ownership cannot recover the individual trades.

## Reproduction and evidence

- Probe: `scripts/investigate_2022_trades.py --playercards`, run with `C:/Users/micha/anaconda3/envs/mustafa/python.exe` and the conda Library/bin directory on PATH.
- Safe live trade evidence: `.h2h_cache/2022-trade-probe-kona_playercard.json`.
- Safe unfiltered transaction evidence: `.h2h_cache/2022-trade-probe-mTransactions2.json`.
- Evidence files omit cookies and member IDs.

## Cross-season validation

| Season | Executed trades recovered | ESPN trades (sum of team counts / 2) | Counter mismatches |
|---|---:|---:|---|
| 2018 | 0 | 5 | grudee, richardson, edwards, sedaghat |
| 2019 | 3 | 3 | none |
| 2020 | 5 | 5 | none |
| 2021 | 7 | 7 | none |
| 2022 | 14 | 14 | none |
| 2023 | 10 | 10 | none |
| 2024 | 6 | 6 | none |
| 2025 | 5 | 5 | none |

2019-2025: every recovered team counter matches ESPN exactly. 2019, 2020, 2021, 2024 and 2025 packages also match the inferred ledger. A 2023 week 10 trade differs and needs correction too. 2018: no trade transactions returned from player cards although ESPN counts 5 trades; keep a roster-inference fallback for that season.

2023 week 10 correction: Edwards sent Kenneth Gainwell and Sam LaPorta to Grudee for Keaton Mitchell, Chris Godwin, and Najee Harris. Grudee dropped Gainwell 54 minutes and 10 seconds after execution, so weekly-roster inference erased his inclusion. This shows that matching trade counts alone does not validate player packages.

## Fix implemented

The transaction fetcher now merges executed player-card records into the cache for 2019 onward. The transformer preserves separate packages and execution dates, validates every team count, and retains inference only for 2018. The 2019-2025 caches, generated website data, rankings, awards, schema descriptions, and trade-page source note have been rebuilt. Regression tests cover the intermediate transfers, Gainwell, incomplete packages, duplicate player-card records, and count mismatch rejection.
