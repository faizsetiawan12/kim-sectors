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

## Planned commands

```bash
python main.py run-daily
python main.py run-backtest --universe lq45 --top-k 3
```

## License

MIT. See [LICENSE](LICENSE).
