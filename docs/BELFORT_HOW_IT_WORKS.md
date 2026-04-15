# How Belfort Works

## What Belfort is

Belfort is the trading and research house inside The Abode.

He does five jobs:
- scan the market board for symbols that are actually in play
- read fresh catalysts and headline context
- evaluate setups with bounded strategy logic
- keep paper and sim execution separate
- learn from outcomes and propose bounded strategy adjustments

## What Belfort is connected to

- Alpaca market data for quotes and latest trades
- Alpaca news headlines for fresh catalysts
- Alpaca paper broker for paper-only order submission and fill sync
- Belfort policy selector for regime-aware setup evaluation
- Belfort risk gate for order blocking and sizing checks
- Local audit logs for signal, paper, sim, learning, and adjustment history

## What Belfort trades right now

Belfort is no longer locked to a single symbol by design.

He now keeps a ranked board built from:
- benchmarks like `SPY`, `QQQ`, and `IWM`
- liquid leaders like `AAPL`, `MSFT`, `NVDA`, and `TSLA`
- a lower-price watchlist used as a small-cap proxy
- any symbols mentioned in fresh Alpaca news headlines

From that board, Belfort picks one `focus symbol` at a time.

For the first real paper-trading phase, Belfort is intentionally bounded:
- paper trading is still long-only
- the Phase 1 paper universe includes `SPY`, `QQQ`, `IWM`, liquid large-cap leaders, and a small allowlisted set of scanner-approved liquid mid-caps
- lower-price and headline-led names can still appear on the board, but they are `watch only`
- current open paper positions are grandfathered; the newer desk limits apply to new entries, adds, and replacements

The current scanner framework ranks names using:
- quote quality
- short tape momentum
- short range expansion
- relative strength versus `SPY`
- fresh catalyst pressure
- catalyst type and headline risk flags
- price bucket context
- market cap
- float
- average volume
- relative volume
- gap context
- float turnover
- pre-open opportunity score

The scanner now also keeps separate leader decks for:
- relative volume leaders
- gap leaders
- pre-open opportunity leaders

The ranking engine is now freer than the original liquid-only desk:
- Belfort can research a broader board than he can immediately paper trade
- paper eligibility is still stricter than research ranking
- more volatile names can be promoted into paper eligibility if their spread, tape behavior, float, market cap, and average volume remain acceptable
- thin, structurally fragile, or headline-risky names remain visible as `watch only` or `blocked`

The Belfort trading platform now separates that into four workspaces:
- `Trade` — watchlist, focus symbol, signal tape, current signal, account, readiness, and controls
- `Scanner` — expanded watchlist, flow leaders, setup radar, catalyst desk, and tape context
- `Research` — learning verdict, setup scorecards, bounded adjustments, readiness checklist, and blotter
- `Guide` — `How It Works`, `BRD`, and `TRD`

## How Belfort chooses what to trade

The decision path is:
1. Scanner ranks symbols using quote quality, spread, short tape movement, and fresh catalyst presence.
2. Belfort checks whether the symbol is actually outperforming or lagging `SPY`.
3. Belfort tags the headline context as things like business catalyst, earnings / numbers, or financing / dilution risk.
4. Belfort picks the current focus symbol unless he is already managing an open position.
5. The policy selector reads the focus symbol and decides which strategy lens is appropriate.
6. The risk layer decides whether the signal is allowed to trade.
7. The paper-entry policy decides whether the desk still has order capacity, buying-power room, symbol room, and turnover budget for a new entry.
8. Belfort estimates whether the setup still has enough net edge after likely spread friction and brokerage-style commission drag.
9. The scanner keeps separate leader decks for relative volume, gap pressure, and pre-open opportunity so Belfort can stalk the best opening-drive names instead of just the highest raw score.
10. Belfort also tracks broker-style paper order lifecycle updates like submitted, accepted, partial fill, filled, rejected, cancelled, and expired so the desk can show what the paper broker is actually doing.
11. Paper orders only go out during a paper-tradeable session (`pre_market`, `regular`, or `after_hours`) and only through the bounded paper path.
12. Near the overnight handoff, Belfort moves into a flatten-and-stand-down path so the next tradeable session starts with fresh buying power.

## What strategies Belfort uses

Current strategy families:
- trend / momentum lens
- mean-reversion lens
- regime router that decides which lens should lead

Current selection evidence:
- short tape direction
- efficiency ratio / regime fit
- spread quality
- relative strength versus `SPY`
- price level
- fresh catalyst pressure
- catalyst type and headline risk flags
- market cap
- float
- average volume

## When Belfort trades

### Sim lane

The sim lane can run outside regular market hours.

Use it for:
- warming up the policy selector
- proving that Belfort can scan, evaluate, log, and track outcomes
- practicing on the current focus symbol without touching paper orders

It is useful, but it is not the same as real intraday paper behavior.

### Paper lane

The paper lane is the real proving ground.

Paper trading only runs when:
- Belfort is in `paper` mode
- the operator has started the paper lane
- a paper-tradeable session is open (`pre_market`, `regular`, or `after_hours`)
- the paper broker is configured
- reconciliation is clean
- the signal engine is warmed up
- the scanner has at least one Phase 1 paper-eligible symbol
- a signal clears the risk gate
- the paper path is proven end to end
- the order remains liquid-only, long-only, and limit-order-only

### Overnight rule

Belfort is being trained as a day trader, not a swing trader.

That means:
- overnight paper inventory is treated as a readiness blocker
- the desk now tries to flatten the paper book into the overnight handoff window instead of quietly carrying risk into the next day
- if positions are still open after the market fully closes, the operator surfaces now say so directly instead of pretending the desk is clean
- new paper entries stop once Belfort enters the flatten-and-stand-down window

## How Belfort paces and sizes the desk

The paper desk is now meant to behave more like a brokerage-ready operator and less like a demo bot.

For new entries, Belfort uses:
- a config-backed daily order-capacity budget instead of the old hardwired 50-order wall
- a rolling hourly trade budget so he does not chew through the day in the first hour
- a per-symbol cooldown so he does not immediately churn back into the same name
- a desk-wide cooldown so he does not spam fresh entries across the whole book
- a turnover budget so he cannot chew through the day with low-quality notional churn
- a per-name concentration cap so one symbol cannot dominate the whole book
- a total active exposure cap and active-name limit so buying power stays diversified

These controls are applied to new buys. Existing open paper positions are grandfathered and can still be managed or exited.

## How Belfort decides a trade is too expensive

Belfort now treats trading costs as part of the setup.

Before a new entry, he compares:
- observed spread / quote quality
- expected setup edge
- likely friction from spread and order handling

If the expected edge is too small compared with the likely cost burden, he skips the trade and says so in plain English.

He also uses structure filters before promoting volatile names into the paper universe:
- market cap floor
- float floor
- average-volume floor
- relative-volume floor
- float-turnover floor
- spread ceiling
- tape-instability ceiling

He now also treats round-trip brokerage friction more realistically:
- a training commission reserve is included in the expected trade math even in paper mode
- the desk estimates whether the setup still has enough net edge after likely fees and slippage
- if Belfort has already traded too much in the last hour, the desk slows down instead of trying to brute-force the day with extra orders

## What the paper window means now

The Belfort desk now keeps a hard proof model, not just a soft status phrase.
The operator surfaces now use that same readiness truth path, so the side rail, trade desk, and open-proof panel do not contradict each other.

The paper-session proof checks:
- scanner is live
- at least one liquid symbol is paper-eligible
- signal evaluation is warmed up
- risk produced an explicit allow or block result
- paper broker configuration is healthy
- fill and position tracking are healthy
- a paper-tradeable session is open

Desk verdicts are now:
- `not_ready`
- `staged_for_open`
- `ready_for_operator_start`
- `actively_trading`

## Why Belfort may choose not to trade

Belfort should often skip trades.

Common reasons:
- the market is fully closed
- Belfort is still carrying overnight inventory from the prior session
- the scanner is still warming up
- spread or quote quality is poor
- the setup does not have enough edge
- costs outweigh the expected edge
- expected profit after likely fees is still too thin
- Belfort traded the same name too recently
- Belfort has already traded too much in the last hour
- the desk has already used too much order capacity or turnover budget
- too much of the book is already concentrated in one position
- risk blocked the order
- there is no tracked position to sell yet

Skipping trades is normal when the desk has no edge.

## How Belfort learns

Belfort learns from:
- signal history
- paper execution history
- sim execution history
- regime snapshots
- setup scorecards
- bounded proposal generation

He should learn separately for:
- paper vs sim
- regular session vs extended-hours paper vs off-session sim practice
- symbol and setup type
- trend vs mean-reversion conditions

## What the UI is meant to prove

The Belfort UI should answer these questions without making you guess:
- what symbol is Belfort focused on right now?
- why is that symbol on the board?
- is that symbol actually eligible for paper trading right now, or only `watch only`?
- what does the watched symbol actually look like on live candles?
- what named setup does Belfort think this is?
- is Belfort only observing, practicing in sim, or able to paper trade?
- what signal did he see?
- did risk block it or allow it?
- if Belfort skipped the trade, was it because of session, pacing, cost, or concentration?
- did paper submit, fill, or stay gated?
- can the operator flatten the whole paper book right now if needed?
- what is Belfort learning from the results?
- what bounded adjustment is he proposing, if any?

## How the trading platform is organized

### Trade

This is the default operator surface. It should fit in one desktop view and answer:
- what is Belfort watching right now?
- what do the current live candles look like for that watched symbol?
- what is the current signal?
- is paper or sim running?
- is Belfort staged, ready, or blocked?
- how much order capacity and buying-power room remain?
- why is Belfort not trading if the paper lane is running?

The trade desk now includes a live candle view for the watched symbol and a close-all action for the paper book.

### Scanner

This is the deeper market board. It shows:
- the expanded ranked watchlist
- scanner filters like leaders, benchmarks, lower-price watch, and news-led names
- setup radar
- catalyst desk
- tape context

### Research

This is where non-immediate trading context lives:
- learning verdict
- setup scorecards
- bounded adjustment desk
- full readiness checklist
- recent blotter

### Guide

This is the documentation surface for:
- `How It Works`
- `BRD`
- `TRD`

## Current limitations

- Relative volume and gap % are not wired yet, so intraday leader detection is still incomplete.
- Catalyst analysis is headline-based; structured SEC cash-flow and balance-sheet parsing is not built yet.
- Relative strength is short-horizon only right now; Belfort still needs deeper session-aware leader/laggard scoring.
- Sim still trains one focus symbol at a time.
- Belfort is still paper-only. Live trading is explicitly out of bounds until readiness is earned.
- The Phase 1 paper universe is broader than the original liquid-only desk, but it is still intentionally narrower than the full research board.

## The next capabilities Belfort needs

- relative volume, gap %, spread, and halt reads on top of the new structure-aware scanner
- deeper market-relative scoring beyond short `SPY` comparison
- richer setup taxonomy by environment: opening range breakout, VWAP reclaim, trend continuation, failed breakout, mean reversion
- richer catalyst parsing: offerings, dilution, earnings, guidance, contracts, and sector sympathy
- per-setup expectancy and win-rate scorecards so Belfort learns what works in each market environment
