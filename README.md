# KIM Sectors

Automated IDX market intelligence for KIM.

KIM Sectors is a decision-support workflow for the Sectors Hackathon 2026 **Automation & Workflows** track. It uses Sectors data to rank LQ45 candidates with a transparent momentum × broker-flow expected-value score, run reproducible backtests, and deliver a concise post-market brief.

> Research and decision support only. KIM Sectors does not place or execute trades.

## Planned workflow

1. Fetch live Sectors API data for the LQ45 universe.
2. Validate and cache market and broker data locally.
3. Calculate monthly price momentum and broker-summary expected value.
4. Rank candidates by the composite score.
5. Generate a Markdown/JSON brief and send it to Telegram.
6. Replay the same strategy over cached history with configurable backtest settings.

## Status

Fresh project scaffold. Implementation will be added during the hackathon build period.

## Local setup

```bash
conda activate sekuritasmology
cp .env.example .env
# Add credentials to .env; never commit .env.
```

The project requires Python 3.10+ and a Sectors API key. Telegram delivery is optional during local development and requires a bot token and destination chat/topic configuration.

## Commands

### `ping-sectors`

Live tracer for the Sectors connection. It authenticates with the configured
API key, fetches one LQ45 symbol's daily bars plus one broker-summary
response, validates both schemas, and prints one JSON log line per stage
(auth, fetch, validate, complete). Timestamps use `Asia/Jakarta`.

```bash
python main.py ping-sectors [--symbol BBCA] [--window-days 7]
```

Cost: 2 API credits per run (one per endpoint). Keep `--window-days` at 14 or
below; the broker-summary endpoint rejects wider windows.

Exit codes: `0` success, `2` authentication failure (including a missing
`SECTORS_API_KEY`), `3` malformed response schema, `4` request failure
(timeout, rate limit, other HTTP errors), `1` unexpected error.

### `sync-cache`

Synchronize the LQ45 universe and reusable Sectors data cache. A command without
`--fetch` is a dry-run preview: it reads existing cache files, reports missing
coverage and the estimated market-data credits, and makes no network calls or
filesystem writes. On a first run the universe is unresolved until `--fetch`
resolves it.

```bash
python main.py sync-cache --start 2026-08-01 --end 2026-08-31
python main.py sync-cache --start 2026-08-01 --end 2026-08-31 --fetch
```

The fetch operation stores validated daily bars and broker-summary days under
`data/cache/`, including source, market symbol/date, retrieval timestamp, and
schema version. It also stores effective-date LQ45 membership snapshots. Daily
requests are limited to 90 days and broker-summary requests to 14 days; later
runs reuse covered spans and request only missing dates. Use
`--refresh-universe --fetch` to append a new membership snapshot.

A first fetch reports one credit per resolved companies-screener page and one
credit per daily or broker-summary request. Preview estimates are conditional
when the universe has not yet been resolved. Existing API authentication and
request/schema exit codes remain: `0` success, `2` authentication, `3` schema,
`4` request failure, and `1` unexpected/cache failure.

### `rank`

Rank the cached LQ45 universe by trailing monthly Momentum. Reads only
validated Data Cache records, never the network. Momentum is
`(end_close / start_close - 1)` where `end_close` is the close on
`--market-date` and `start_close` is the close `--lookback` available trading
sessions earlier (default 21, requiring 22 closes ending on the market date).
Available sessions are counted, so weekend and
holiday gaps are skipped without calendar-day math.

```bash
python main.py rank --market-date 2026-08-15 [--lookback 21]
```

Eligible candidates are sorted highest to lowest Momentum with symbol,
market date, momentum, start/end dates, start/end closes, and lookback. Symbols
with insufficient history, non-positive closes, or no price on the market date
are listed under `ineligible_reasons` with human-readable reasons instead of a
silent zero. The universe snapshot effective on or before `--market-date` is
used, so a later membership change does not rewrite history. Prices after
`--market-date` are ignored.

Exit codes: `0` success, `1` unexpected/cache failure (including missing
universe membership or a future market date).

### `signal`

Rank the cached LQ45 universe by the composite `Momentum × Broker EV` signal.
Reads only validated Data Cache records, never the network. Momentum uses the
same trailing return as `rank` (`--lookback` default 21). Broker EV is raw
next-day expected value estimated from historical broker-summary observation
dates whose next-session outcome is observable by `--market-date`
(next close on or before the signal date, so delayed outcomes are excluded),
with no winsorization: `p × reward-risk − (1 − p)` where `p` is win probability
and reward-risk is average gain over average loss.

```bash
python main.py signal --market-date 2026-08-15 [--lookback 21] [--min-samples 5]
```

Eligible candidates expose symbol, momentum, sample count, win probability,
average gain/loss, reward-risk ratio, raw EV, signal score, and supporting
price fields, sorted highest to lowest signal (ties break by symbol). Missing,
invalid, infinite (e.g. no losses), and under-sampled factors are listed under
`ineligible_reasons` with explicit reasons instead of silent zeros. The top
candidate is highlighted under `highlight` as research and decision support
only, without a buy or sell instruction. Prices after `--market-date` are
ignored.

Exit codes: `0` success, `1` unexpected/cache failure (including missing
universe membership, a future market date, or invalid lookback/min-samples).

### `run-daily`

Execute the post-market pipeline end to end for the LQ45 universe: fetch and
validate the data cache (live runs only), calculate Momentum × Broker EV, rank
candidates, save the Markdown and JSON Daily Market Brief under
`output/reports/daily/<market-date>.md` and `.json`, then deliver a compact
executive brief through Telegram. Artifacts are always written before any
Telegram delivery is attempted; a failed delivery exits non-zero (`5`) and the
saved briefs remain available.

```bash
python main.py run-daily
python main.py run-daily --market-date 2026-08-15
```

Without `--market-date` the brief uses today (WIB) and the live Sectors fetch
runs first, synchronizing the trailing 60 calendar days of daily and broker
data. With a past `--market-date`, the same single implementation replays from
cached data only (no network calls or API credits). `--lookback` (default 21)
and `--min-samples` (default 5) mirror the `signal` command.

Telegram delivery requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (and
optionally `TELEGRAM_MESSAGE_THREAD_ID`); without them the brief is still saved
and the notify stage is logged as `skipped`. Each artifact includes the market
date, WIB run timestamp, data freshness from cache provenance, universe
coverage, ranked candidates with score components, exclusions/warnings, and the
research-only disclaimer.

Exit codes: `0` success (including a skipped delivery), `1` unexpected/cache
failure (including a future market date or invalid lookback/min-samples), `2`
authentication, `3` schema, `4` request, `5` Telegram delivery failure.

### `run-backtest`

Replay the `Momentum × Broker EV` strategy over validated cached history with
no Sectors API calls: the replay reads only Data Cache records, so repeating
the same Backtest Run is deterministic and costs zero credits.

```bash
python main.py run-backtest --start 2026-08-01 --end 2026-08-31 \
  [--universe lq45] [--lookback 21] [--min-samples 5] [--top-k 3] \
  [--rebalance-sessions 21] [--cost-bps 10] [--slippage-bps 5]
```

- `--start`/`--end` define the inclusive replay window; `--universe` selects
  the cached universe index (default `lq45`). Momentum lookback and broker EV
  minimum samples match the `signal` command.
- `--top-k` is the portfolio size; the target portfolio holds the top-k
  eligible candidates equal-weight. `--rebalance-sessions` is the number of
  sessions between rebalances (default 21, approximately monthly).
- `--cost-bps`/`--slippage-bps` are explicit per-trade assumptions (commission
  and slippage in basis points) applied to every buy and sell.

Before any signal math the run checks cache coverage for the requested window
for every universe symbol (both daily bars and broker summaries). Missing
history is reported with the exact `sync-cache` command to fetch it; the run
refuses to calculate over gaps.

The replay is point-in-time: at each rebalance date `T` the composite signal
uses only data observable by `T` (broker EV outcomes whose next session close
is on or before `T`), matching the `signal` command. End-of-day signals enter
at the next eligible market session close, never earlier; the entry price and
timing are recorded per trade. The universe is fixed to the membership
snapshot effective on or before `--start`. If a target symbol has no close on
the entry session its entry is skipped and recorded. When a rebalance produces
no eligible candidates the portfolio liquidates to cash. Final equity is marked
to the close of the last session in the window; no terminal liquidation cost is
assumed.

The result is written to `output/reports/backtest_<universe>_<start>_<end>
_l<lookback>_k<top-k>_r<rebalance>.json` and includes the configuration,
coverage, total return, win rate, average period return, maximum drawdown
(deepest peak-to-trough decline, reported as a non-positive fraction),
observation and trade counts, an equal-weight buy-and-hold benchmark comparison
of the universe (when endpoint closes are cached), period returns, and the
per-session equity curve.

Exit codes: `0` success, `1` unexpected/cache failure (including incomplete
coverage, missing universe membership, or invalid arguments).

## License

MIT. See [LICENSE](LICENSE).
