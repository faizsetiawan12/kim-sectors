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

## Planned commands

```bash
python main.py run-daily
python main.py run-backtest --universe lq45 --top-k 3
```

## License

MIT. See [LICENSE](LICENSE).
