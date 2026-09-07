# KIM Sectors

Automated IDX market intelligence for KIM.

KIM Sectors is a decision-support workflow for the Sectors Hackathon 2026 **Automation & Workflows** track. It uses Sectors data to rank LQ45 candidates with a transparent momentum × broker-flow expected-value score, run reproducible backtests, and deliver a concise post-market brief.

> Research and decision support only. KIM Sectors does not place or execute trades.

## Problem and solution

Indonesian-equity investors spend time collecting prices and broker activity, repeating calculations, checking historical behavior, and preparing a daily decision brief. This workflow turns those steps into a repeatable, inspectable pipeline while leaving the investment decision with a human.

**Sectors Financial API v2** is the core market-data dependency. The default **LQ45 Universe** is resolved from Sectors and stored with an effective date. Current and historical daily bars plus broker summaries are validated, normalized, and persisted in the local **Data Cache** (`data/cache/`). The cache is reused by later runs and backtests, so repeated research does not spend more API credits.

The pipeline is:

1. Fetch Sectors data and resolve LQ45 membership.
2. Validate response schemas and cache provenance.
3. Calculate Momentum and Broker EV.
4. Rank candidates and produce Markdown/JSON artifacts.
5. Optionally notify Telegram.
6. Replay the same point-in-time inputs with a Backtest Run.

### Formula and human boundary

Monthly Momentum is the trailing return over 21 available trading sessions:
`(end_close / start_close) - 1`.

Broker EV estimates raw next-day outcomes only from historical broker-summary observations with qualifying broker-buy activity: positive buy value or buy lots and positive net accumulation. Its formula is:
`p × reward-risk − (1 − p)`.

The composite Signal Score is:
`Momentum × Broker EV`.

Missing, invalid, infinite, or under-sampled factors are excluded with a reason. Outcomes are only used once observable at the relevant date; this prevents look-ahead bias. Rankings are research inputs, not buy/sell instructions. A human decides whether any further action is appropriate.

## Demo, live data, and credit budget

The reproducible demo path uses a controlled adapter in tests and the real Sectors path uses environment configuration. Never put credentials in README, source, reports, or Git:

```bash
conda activate kim-sectors
cp .env.example .env
# Set SECTORS_API_KEY in .env locally; do not commit .env
python main.py ping-sectors --symbol BBCA --window-days 2
python main.py run-daily --market-date 2026-08-15  # cached replay, zero credits
```

`ping-sectors` is the bounded live contract tracer: one daily request plus one broker-summary request, **2 API credits maximum**, with a 14-day window limit. It is the preferred live-data demo check. A larger `sync-cache --fetch` is always explicit and prints its estimated request cost first. Development was constrained to approximately **600 API credits**, so cache reuse, missing-span fetches, bounded windows, and explicit fetch flags are deliberate design choices. Backtest Run never calls Sectors and costs zero credits.

## Recurring post-market operation

Run the Daily Pipeline after IDX closes, Monday–Friday at **16:15 WIB** (`Asia/Jakarta`). This deployment-neutral cron entry uses the repository launcher:

```cron
CRON_TZ=Asia/Jakarta
15 16 * * 1-5 /home/faiz/KIM/repos/kim-sectors/scripts/run_daily_cron.sh >> /home/faiz/KIM/repos/kim-sectors/output/logs/daily-cron.log 2>&1
```

The command is also directly runnable:

```bash
./scripts/run_daily_cron.sh
```

The launcher does not contain credentials and returns the pipeline exit code. Use `python main.py run-daily --market-date YYYY-MM-DD` for manual replay from the Data Cache.

## Opt-in operational smoke checks

Normal tests make no network calls and do not send Telegram messages. Live checks are explicitly separated:

```bash
# Normal suite: excludes both external-service smoke markers
python -m pytest

# Sectors contract check: bounded to at most 2 API credits
RUN_LIVE_SECTORS=1 python -m pytest -m live tests/test_live_smoke.py

# Telegram check: requires both values and sends one harmless message
RUN_TELEGRAM_SMOKE=1 python -m pytest -m telegram tests/test_telegram_smoke.py
```

`SECTORS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and the optional `TELEGRAM_MESSAGE_THREAD_ID` are read only from the local environment. Missing configuration causes an opt-in smoke test to skip; no smoke test runs accidentally.

## Operational logs and limitations

Each command emits one JSON object per line with a WIB timestamp and a stage. Depending on the command, stages include `fetch`, `validate`, `scoring`, `backtesting`, `report`, and `notify`, plus `complete`. Logs contain counts, dates, statuses, and error context, never API keys or Telegram bot tokens. The Data Cache remains local and must be backed up or refreshed deliberately. Sectors availability, market holidays, incomplete history, API quota, and Telegram availability can prevent a successful live run. The workflow is not a broker integration, does not authenticate to brokerage accounts, and has no order-placement, portfolio-mutation, or automated buy/sell capability.

## Reproducible competition path

For a clean judging/demo run: configure a local Sectors API key; run the bounded `ping-sectors` tracer; use `sync-cache --start ... --end ... --fetch` only for the historical span needed; run `run-daily` to create the Markdown/JSON brief and optionally deliver Telegram; then run `run-backtest` against the same validated cache. Show the structured logs, report artifacts, formula fields, credit estimate, and the explicit human decision boundary.

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
